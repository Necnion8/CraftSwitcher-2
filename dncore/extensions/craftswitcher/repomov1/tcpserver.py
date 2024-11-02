import asyncio
import json
import logging
import re
from asyncio import StreamWriter
from typing import Optional, Dict, List, Set

from .exceptions import ResponseError, ClosedError
from .socket_data import EmptyResponseData, SerializableData, InvalidData, get_data_class

log = logging.getLogger(__name__)


class TCPClientListener:
    async def on_receive_data(self, reporter_name: str, data: SerializableData, data_id: int) -> SerializableData:
        pass

    async def on_connect_client(self, reporter_name: str):
        pass

    async def on_disconnect_client(self, reporter_name: str, retried_old: bool):
        pass


class TCPServer(object):
    def __init__(self, host, port, loop):
        self.host = (host, port)
        self.loop = loop
        self.server_task: Optional[asyncio.AbstractServer] = None
        self._writers: Dict[str, StreamWriter] = {}  # reporterName -> StreamWriter
        self._send_futures: Dict[StreamWriter, Dict[int, asyncio.Future]] = {}
        self._send_data_id: Dict[StreamWriter, int] = {}
        self._listeners: List[TCPClientListener] = []
        self._retried_olds = set()  # type: Set[StreamWriter]

    async def start(self):
        await self.close()
        self.server_task = await asyncio.start_server(self._handler, *self.host)

    async def close(self):
        if self.server_task:
            clients = list(self._writers.values())
            [c.close() for c in clients]
            if clients:
                await asyncio.gather(*[c.wait_closed() for c in clients], return_exceptions=True)

            self.server_task.close()
            await self.server_task.wait_closed()
            self.server_task = None

    async def _handler(self, reader: asyncio.streams.StreamReader, writer: StreamWriter):
        addr = writer.get_extra_info("peername")
        log.debug(f"Connected TCPClient: {addr}")

        writer.write(b"###AUTH:CraftSwitcher1###\n")
        await writer.drain()

        name = str(addr)
        reporter_name = None
        buf = b""
        closing = False
        try:
            while not closing:
                try:
                    chunk = await reader.read(2048)
                except ConnectionError as e:
                    log.debug("ignored error connection: " + str(e))
                    break  # ignored
                if not chunk:
                    break  # closed

                buf += chunk

                while buf.find(b"\n") != -1:
                    line, buf = buf.split(b"\n", 1)

                    try:
                        if not reporter_name:
                            _line = line.decode("utf-8", errors="ignore")
                            reporter_name = self.parse_auth_message(_line)
                            if not reporter_name:
                                log.warning(f"An unsupported client has connected: {addr}")
                                log.debug("(output the first line): " + _line)
                                closing = True
                                continue

                            if reporter_name in self._writers:
                                server = get_server(reporter_name)
                                if server and server.state.is_running:
                                    log.info(f"Retrying re-instance connection: {name}")
                                    self._retried_olds.add(self._writers[reporter_name])

                                    old_writer = self._writers[reporter_name]
                                    old_writer.close()
                                    await old_writer.wait_closed()

                                else:
                                    log.warning(f"Already connected reporter name: {name}")
                                    closing = True
                                    continue

                            self._writers[reporter_name] = writer
                            name = f"reporter({reporter_name})"
                            log.debug(f"client authorized: {addr} is reporter {reporter_name} server")

                            for listener in self._listeners:
                                self.loop.create_task(listener.on_connect_client(reporter_name))

                            continue

                        split = line.decode("utf-8").split(",", 3)
                        if len(split) != 4:
                            log.warning(f"invalid data lengths received by: {name}")
                            continue

                        method, key, data_id, json_raw = split
                        try:
                            data_id = int(data_id)
                            data = json.loads(json_raw)
                        except ValueError:
                            continue

                        data_type = get_data_class(key)
                        if data_type:
                            data = data_type.from_json(data)

                            if method == "send":
                                await self.process_receive_data(reporter_name, writer, data, data_id)
                                continue

                            elif method == "response":
                                await self.process_response_data(writer, data, data_id)
                                continue

                        elif method == "send":
                            log.warning(f"warn received by {name}: unknown \"{key}\" data-type")
                            await self.send_raw_data("response", writer, InvalidData("unknown data-type"), data_id)
                            continue

                        log.warning(f"warn received by {name}: \"{line}\"")

                    except ConnectionError as e:
                        log.error(f"Client {name} handling error: {str(e)}")
                        break

                    except (Exception,):
                        log.error(f"Client {name} handling error:", exc_info=True)

        finally:
            retried_old = writer in self._retried_olds
            if retried_old:
                log.debug(f"retry old closes TCPClient: {name}")
                self._retried_olds.remove(writer)
            else:
                log.debug(f"Disconnecting TCPClient: {name}")

            for listener in self._listeners:
                self.loop.create_task(listener.on_disconnect_client(reporter_name, retried_old))

            try:
                for future in self._send_futures.get(writer, {}).values():
                    future.set_exception(ClosedError())
            finally:
                if writer in self._writers.values():
                    self._writers.pop(reporter_name, None)

                self._send_futures.pop(writer, None)
                self._send_data_id.pop(writer, None)

    # async def _on_read_line(self, reader: asyncio.StreamReader, writer: StreamWriter, line: bytes):

    @staticmethod
    def parse_auth_message(line: str):
        m = re.search(r"^###AUTH:CraftSwitcher1:REPORTER:(.+)###$", line)
        if m:
            return m.group(1)

    async def send_data(self, reporter_name: str, data: SerializableData):
        writer = self._writers[reporter_name]
        data_id = self._send_data_id.get(writer, 0) + 1
        self._send_data_id[writer] = data_id

        future = asyncio.Future()
        self._send_futures.setdefault(writer, {})[data_id] = future

        await self.send_raw_data("send", writer, data, data_id)
        await future
        return future.result()

    @staticmethod
    async def send_raw_data(method: str, writer: StreamWriter, data: SerializableData, data_id: int):
        writer.write(",".join((
            method, data.get_data_key(), str(data_id), json.dumps(data.to_json())
        )).encode("utf-8") + b"\n")
        await writer.drain()

    async def process_receive_data(self, reporter_name: str, writer: StreamWriter, data: SerializableData, data_id):
        async def async_call():
            response_data = None
            for listener in self._listeners:
                try:
                    response_data = await listener.on_receive_data(reporter_name, data, data_id)
                except (Exception,):
                    log.error("Exception in receive data handler:", exc_info=True)
                    response_data = InvalidData("internal-error")

                if response_data:
                    break

            if response_data is None:
                response_data = EmptyResponseData()
            await self.send_raw_data("response", writer, response_data, data_id)

        self.loop.create_task(async_call())

    async def process_response_data(self, writer: StreamWriter, data: SerializableData, data_id):
        future = self._send_futures.setdefault(writer, {}).pop(data_id, None)
        if future and not future.cancelled():
            if isinstance(data, InvalidData):
                future.set_exception(ResponseError(data.message))
            else:
                future.set_result(data)

    def is_connected(self, reporter_name: str):
        return reporter_name in self._writers

    def add_listener(self, listener: TCPClientListener):
        self._listeners.append(listener)


def get_server(server_id: str):
    from ..utils import getinst
    return getinst().servers.get(server_id)
