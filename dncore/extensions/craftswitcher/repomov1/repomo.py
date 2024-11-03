import asyncio
from logging import getLogger

from . import errors
from .socket_data import *
from .tcpserver import TCPClientListener, TCPServer
from ..abc import ServerState
from ..serverprocess import ServerProcess
from ..utils import getinst

log = getLogger(__name__)


class ServerStatusUpdater(object):
    def __init__(self, tcp: TCPServer, server: "ServerProcess"):
        self.tcp = tcp
        self.server = server
        self.data = None  # type: StatusData | None
        self._task = None  # type: asyncio.Task | None
        self._interrupted = False

    async def run(self):
        self.server.log.debug("Started status checker")
        try:
            while not self._interrupted and self.tcp.is_connected(self.server.id):
                try:
                    response = await asyncio.wait_for(self.tcp.send_data(self.server.id, StatusData()), timeout=4)

                except asyncio.CancelledError:
                    raise

                except (ConnectionError, errors.ClosedError):
                    await asyncio.sleep(10)

                except asyncio.TimeoutError:
                    self.server.log.warning("Timeout in status check")

                except Exception as e:
                    self.server.log.exception("Error in status check", exc_info=e)
                    await asyncio.sleep(10)

                else:
                    if isinstance(response, StatusData):
                        self.data = response
                    else:
                        self.data = None

                await asyncio.sleep(2)

        finally:
            self.server.log.debug("Stopped status checker")
            self.data = None
            self._task = None

    async def start(self):
        await self.stop()
        self._interrupted = False
        self._task = asyncio.get_running_loop().create_task(self.run())

    async def stop(self):
        self._interrupted = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (Exception, ):
                pass
        self._task = None


class ReportModuleServer(TCPClientListener):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.tcp = TCPServer("localhost", 8023, loop)
        self.server_updaters = {}  # type: dict[str, ServerStatusUpdater]
        #
        self.tcp.add_listener(self)

    @property
    def servers(self) -> "dict[str, ServerProcess | None]":
        return getinst().servers

    async def open(self):
        await self.tcp.start()

    async def close(self):
        for updater in self.server_updaters.values():
            await updater.stop()
        self.server_updaters.clear()

        await self.tcp.close()

    async def on_connect_client(self, reporter_name: str):
        server = self.servers.get(reporter_name)
        if not server:
            return

        try:
            updater = self.server_updaters.pop(reporter_name)
        except KeyError:
            pass
        else:
            await updater.stop()

        updater = self.server_updaters[reporter_name] = ServerStatusUpdater(self.tcp, server)
        await updater.start()

    async def on_disconnect_client(self, reporter_name: str, retried_old: bool):
        if retried_old:
            return
        try:
            updater = self.server_updaters.pop(reporter_name)
        except KeyError:
            return
        await updater.stop()

    async def on_receive_data(self, reporter_name: str, data: SerializableData, data_id: int) -> SerializableData:
        sender_server = self.servers.get(reporter_name)

        if isinstance(data, ServerStartRequest):
            target_server = data.target_server
            server = self.servers.get(target_server)
            response = ServerStartRequest()
            if server:
                response.target_server = server.id

            if not server:
                response.success = False
                response.fail_message = "not found server"

            elif server.state.is_running:
                response.success = False
                response.fail_message = "already running server"

            else:
                try:
                    await server.start()

                except errors.ServerProcessError as e:
                    response.success = False
                    response.fail_message = errors.localize(e)

                else:
                    response.success = True
            return response

        elif isinstance(data, ServerStopRequest):
            target_server = data.target_server
            server = self.servers.get(target_server)
            response = ServerStopRequest()
            if server:
                response.target_server = server.id

            if not server:
                response.success = False
                response.fail_message = "not found server"

            elif not server.state.is_running:
                response.success = False
                response.fail_message = "already stopped server"

            else:
                try:
                    await server.stop()
                    await server.wait_for_shutdown()

                except asyncio.TimeoutError:
                    response.success = False
                    response.fail_message = "timeout stopping"
                except errors.ServerProcessError as e:
                    response.success = False
                    response.fail_message = errors.localize(e)

                else:
                    response.success = True
            return response

        elif isinstance(data, ServerRestartRequest):
            target_server = data.target_server
            server = self.servers.get(target_server)
            response = ServerRestartRequest()
            if server:
                response.target_server = server.id

            if not server:
                response.success = False
                response.fail_message = "not found server"

            elif not server.state.is_running:
                response.success = False
                response.fail_message = "stopped server"

            else:
                try:
                    await server.stop()
                    await server.wait_for_shutdown()
                    await server.start()

                except asyncio.TimeoutError:
                    response.success = False
                    response.fail_message = "timeout stopping"
                except errors.ServerProcessingError:
                    response.success = False
                    response.fail_message = "processing"
                except errors.ServerProcessError as e:
                    response.success = False
                    response.fail_message = errors.localize(e)

                else:
                    response.success = True
            return response

        elif isinstance(data, ServerListRequest):
            response = ServerListRequest()
            response.servers = [k for k, v in self.servers.items() if v]
            return response

        elif isinstance(data, ServerChangeStateData):
            state = ServerState.of_old_value(data.state)

            if sender_server:
                sender_server.state = state

            return EmptyResponseData()

        elif isinstance(data, ServerStateRequest):
            if server := self.servers.get(data.server):
                return ServerStateRequest(server.id, server.state.old_value)
            return EmptyResponseData()

        log.debug(f"onReceive: reporter=" + reporter_name + ", class=" + type(data).__name__)

    async def send_to_all(self, data: SerializableData):
        for reporter_name in self.server_updaters.keys():
            asyncio.get_running_loop().create_task(self.tcp.send_data(reporter_name, data))

    async def handle_on_server_add(self, server_id: str):
        await self.send_to_all(ServerAddData(server_id))

    async def handle_on_server_remove(self, server_id: str):
        await self.send_to_all(ServerRemoveData(server_id))

    async def handle_on_server_state_update(self, server_id: str, status: ServerState):
        await self.send_to_all(ServerChangeStateData(server_id, status))
