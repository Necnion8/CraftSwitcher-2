import asyncio
import shutil
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Any, Coroutine, NamedTuple

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, Response, Depends, Request, APIRouter
from fastapi.exceptions import WebSocketException
from fastapi.params import Form, Query
from fastapi.requests import HTTPConnection
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm

from dncore.configuration.configuration import ConfigValues
from dncore.extensions.craftswitcher import errors
from dncore.extensions.craftswitcher.database import SwitcherDatabase
from dncore.extensions.craftswitcher.files import FileManager, FileTask
from dncore.extensions.craftswitcher.publicapi import APIError, APIErrorCode, WebSocketClient, model
from dncore.extensions.craftswitcher.publicapi.event import *
from dncore.extensions.craftswitcher.utils import call_event, datetime_now

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import CraftSwitcher, ServerProcess
    from dncore.extensions.craftswitcher.config import ServerConfig
    from dncore.extensions.craftswitcher.serverprocess import ServerProcessList

log = getLogger(__name__)


class PairPath(NamedTuple):
    real: Path
    swi: str
    server: "ServerProcess | None"
    root_dir: Path | None


class APIHandler(object):
    inst: "CraftSwitcher"
    database: "SwitcherDatabase"
    servers: "ServerProcessList"
    files: "FileManager"

    def __init__(self, inst: "CraftSwitcher", api: FastAPI, database: SwitcherDatabase):
        self.inst = inst
        self.database = database
        self.servers = inst.servers
        self.files = inst.files
        self.router = api
        self._websocket_clients = set()  # type: set[WebSocketClient]
        #
        api.include_router(self._app())
        api.include_router(self._user())
        api.include_router(self._server())
        api.include_router(self._file())

        @api.exception_handler(HTTPException)
        def _on_api_error(_, exc: HTTPException):
            return JSONResponse(status_code=exc.status_code, content=dict(
                error=exc.detail,
                error_code=exc.code if isinstance(exc, APIError) else -1,
            ))

        @api.exception_handler(500)
        def _on_internal_exception_handler(_, __: Exception):
            return JSONResponse(status_code=500, content=dict(
                error="Internal Server Error",
                error_code=-1,
            ))

    # websocket

    @property
    def ws_clients(self):
        return self._websocket_clients

    async def broadcast_websocket(self, data):
        tasks = [
            client.websocket.send_json(data)
            for client in self.ws_clients
        ]

        if tasks:
            await asyncio.gather(*tasks)

    # user

    async def get_authorized_user(self, connection: HTTPConnection):
        try:
            token = connection.cookies["session"]
        except KeyError:
            pass
        else:
            user = await self.database.get_user_by_valid_token(token)
            if user:
                return user

        raise APIErrorCode.INVALID_AUTHENTICATION_CREDENTIALS.of("Invalid authentication credentials", 401)

    async def get_authorized_user_ws(self, websocket: WebSocket):
        try:
            return await self.get_authorized_user(websocket)
        except HTTPException as e:
            raise WebSocketException(1008) from e

    # api handling

    def _app(self):
        inst = self.inst  # type: CraftSwitcher
        api = APIRouter(
            tags=["App", ],
        )

        @api.get(
            "/config/server_global",
            dependencies=[Depends(self.get_authorized_user), ],
        )
        async def _get_config_server_global() -> model.ServerGlobalConfig:
            def toflat(keys: list[str], conf: "ConfigValues") -> dict[str, Any]:
                ls = {}
                for key, entry in conf.get_values().items():
                    if isinstance(entry.value, ConfigValues):
                        ls.update(toflat([*keys, key], entry.value))
                    else:
                        ls[".".join([*keys, key])] = entry.value
                return ls

            return model.ServerGlobalConfig(**toflat([], inst.config.server_defaults))

        @api.put(
            "/config/server_global",
            dependencies=[Depends(self.get_authorized_user), ],
        )
        async def _put_config_server_global(param: model.ServerGlobalConfig) -> model.ServerGlobalConfig:
            config = inst.config.server_defaults

            for key, value in param.model_dump(exclude_unset=True).items():
                conf = config

                key = key.split("__")
                while 2 <= len(key):
                    conf = getattr(conf, key.pop(0))
                setattr(conf, key[0], value)

            inst.config.save(force=True)
            return await _get_config_server_global()

        @api.websocket(
            "/ws",
            dependencies=[Depends(self.get_authorized_user_ws), ],
        )
        async def _websocket(websocket: WebSocket):
            await websocket.accept()

            client = WebSocketClient(websocket)
            log.debug("Connected WebSocket Client #%s", client.id)
            call_event(WebSocketClientConnectEvent(client))
            self._websocket_clients.add(client)

            try:
                async for data in websocket.iter_json():
                    log.debug("WS#%s -> %s", client.id, data)  # TODO: remove debug

                    try:
                        request_type = data["type"]
                    except KeyError:
                        continue

                    if request_type == "server_process_write":
                        try:
                            server_id = data["server"]
                            write_data = data["data"]
                        except KeyError:
                            continue

                        try:
                            server = inst.servers[server_id]
                        except KeyError:
                            continue
                        if server and server.state.is_running:
                            try:
                                server.wrapper.write(write_data)
                            except Exception as e:
                                server.log.warning("Exception in write to server process by WS#%s", client.id, exc_info=e)

            finally:
                self._websocket_clients.discard(client)
                call_event(WebSocketClientDisconnectEvent(client))
                log.debug("Disconnect WebSocket Client #%s", client.id)
                
        return api

    def _user(self):
        db = self.database
        api = APIRouter(
            tags=["User", ],
        )

        @api.post(
            "/login",
        )
        async def _login(request: Request, response: Response, form_data: OAuth2PasswordRequestForm = Depends()):
            user = await self.database.get_user(form_data.username)
            if not user:
                raise APIErrorCode.INVALID_AUTHENTICATION_CREDENTIALS.of("Invalid authentication credentials", 401)

            if not db.verify_hash(form_data.password, user.password):
                raise APIErrorCode.INCORRECT_USERNAME_OR_PASSWORD.of("Incorrect username or password")

            expires, token, _ = await db.update_user_token(
                user=user,
                last_login=datetime_now(),
                last_address=request.client.host,
            )

            response.set_cookie(
                key="session",
                value=token,
                max_age=expires.total_seconds(),
            )
            return dict(result=True)
        
        return api

    def _server(self):
        inst = self.inst  # type: CraftSwitcher
        servers = self.inst.servers
        api = APIRouter(
            tags=["Server", ],
            dependencies=[Depends(self.get_authorized_user), ],
        )
        
        def getserver(server_id: str):
            try:
                server = servers[server_id.lower()]
            except KeyError:
                raise APIErrorCode.SERVER_NOT_FOUND.of("Server not found", 404)

            if server is None:
                raise APIErrorCode.SERVER_NOT_LOADED.of("Server config not loaded", 404)
            return server

        @api.get(
            "/servers",
            summary="登録サーバーの一覧",
            description="登録されているサーバーを返します",
        )
        async def _list(only_loaded: bool = False, ) -> list[model.Server]:
            ls = []  # type: list[model.Server]

            for server_id, server in servers.items():
                if server:
                    try:
                        server_swi_path = inst.swipath_server(server)
                    except ValueError:
                        server_swi_path = None
                    ls.append(model.Server.create(server, server_swi_path))
                elif not only_loaded:
                    try:
                        server_dir = self.inst.config.servers[server_id]
                    except KeyError:
                        continue  # 外部から削除または変更されていた場合はリストから静かに除外する
                    ls.append(model.Server.create_no_data(server_id, inst.files.resolvepath(server_dir, force=True)))

            return ls

        @api.post(
            "/server/{server_id}/start",
            summary="サーバーを起動",
            description="サーバーを起動します",
        )
        async def _start(server_id: str, ) -> model.ServerOperationResult:
            server = getserver(server_id)

            try:
                await server.start()
            except errors.AlreadyRunningError:
                raise APIErrorCode.SERVER_ALREADY_RUNNING.of("Already running")
            except errors.OutOfMemoryError:
                raise APIErrorCode.OUT_OF_MEMORY.of("Out of memory")
            except errors.ServerLaunchError as e:
                raise APIErrorCode.SERVER_LAUNCH_ERROR.of(f"Failed to launch: {e}")
            except errors.OperationCancelledError as e:
                raise APIErrorCode.OPERATION_CANCELLED.of(f"Operation cancelled: {e}")

            return model.ServerOperationResult.success(server.id)

        @api.post(
            "/server/{server_id}/stop",
            summary="サーバーを停止",
            description="サーバーを停止します",
        )
        async def _stop(server_id: str, ) -> model.ServerOperationResult:
            server = getserver(server_id)

            try:
                await server.stop()
            except errors.NotRunningError:
                raise APIErrorCode.SERVER_NOT_RUNNING.of("Not running")
            except errors.ServerProcessingError:
                raise APIErrorCode.SERVER_PROCESSING.of("Server is processing")

            return model.ServerOperationResult.success(server.id)

        @api.post(
            "/server/{server_id}/restart",
            summary="サーバーを再起動",
            description="サーバーを再起動します",
        )
        async def _restart(server_id: str, ) -> model.ServerOperationResult:
            server = getserver(server_id)

            try:
                await server.restart()
            except errors.NotRunningError:
                raise APIErrorCode.SERVER_NOT_RUNNING.of("Not running")
            except errors.ServerProcessingError:
                raise APIErrorCode.SERVER_PROCESSING.of("Server is processing")

            return model.ServerOperationResult.success(server.id)

        @api.post(
            "/server/{server_id}/kill",
            summary="サーバーを強制終了",
            description="サーバーを強制終了します",
        )
        async def _kill(server_id: str, ) -> model.ServerOperationResult:
            server = getserver(server_id)

            try:
                await server.kill()
            except errors.NotRunningError:
                raise APIErrorCode.SERVER_NOT_RUNNING.of("Not running")

            return model.ServerOperationResult.success(server.id)

        @api.post(
            "/server/{server_id}/import",
            summary="構成済みのサーバーを追加",
            description="構成済みのサーバーを登録します",
        )
        async def _add(server_id: str, param: model.AddServerParam, ) -> model.ServerOperationResult:
            server_id = server_id.lower()
            if server_id in servers:
                raise APIErrorCode.ALREADY_EXISTS_ID.of("Already exists server id")

            server_dir = self.inst.files.realpath(param.directory)
            if not server_dir.is_dir():
                raise APIErrorCode.NOT_EXISTS_DIRECTORY.of("Not exists directory")

            try:
                config = inst.import_server_config(server_dir)
            except FileNotFoundError:
                raise APIErrorCode.NOT_EXISTS_CONFIG_FILE.of("Not exists server config")

            server = inst.create_server(server_id, server_dir, config, set_creation_date=False)
            return model.ServerOperationResult.success(server.id)

        @api.post(
            "/server/{server_id}",
            summary="サーバーを作成",
            description="サーバーを作成します",
        )
        async def _create(server_id: str, param: model.CreateServerParam, ) -> model.ServerOperationResult:
            server_id = server_id.lower()
            if server_id in servers:
                raise APIErrorCode.ALREADY_EXISTS_ID.of("Already exists server id")

            server_dir = self.inst.files.realpath(param.directory)
            if not server_dir.is_dir():
                raise APIErrorCode.NOT_EXISTS_DIRECTORY.of("Not exists directory")

            config = inst.create_server_config(server_dir)
            config.name = param.name
            config.type = param.type
            config.launch_option.java_executable = param.launch_option.java_executable
            config.launch_option.java_options = param.launch_option.java_options
            config.launch_option.jar_file = param.launch_option.jar_file
            config.launch_option.server_options = param.launch_option.server_options
            config.launch_option.max_heap_memory = param.launch_option.max_heap_memory
            config.launch_option.min_heap_memory = param.launch_option.min_heap_memory
            config.launch_option.enable_free_memory_check = param.launch_option.enable_free_memory_check
            config.launch_option.enable_reporter_agent = param.launch_option.enable_reporter_agent
            config.enable_launch_command = param.enable_launch_command
            config.launch_command = param.launch_command
            config.stop_command = param.stop_command
            config.shutdown_timeout = param.shutdown_timeout

            server = inst.create_server(server_id, server_dir, config)
            return model.ServerOperationResult.success(server.id)

        @api.delete(
            "/server/{server_id}",
            summary="サーバーを削除",
            description="サーバーを削除します",
        )
        async def _delete(server_id: str, delete_config_file: bool = False, ) -> model.ServerOperationResult:
            server = getserver(server_id)

            if server.state.is_running:
                raise APIErrorCode.SERVER_ALREADY_RUNNING.of("Already running")

            inst.delete_server(server, delete_server_config=delete_config_file)
            return model.ServerOperationResult.success(server.id)

        @api.get(
            "/server/{server_id}/config",
            summary="サーバー設定の取得",
            description="サーバーの設定を返します",
        )
        async def _get_config(server_id: str, ) -> model.ServerConfig:
            server = getserver(server_id)

            def toflat(keys: list[str], conf: "ConfigValues") -> dict[str, Any]:
                ls = {}
                for key, entry in conf.get_values().items():
                    if isinstance(entry.value, ConfigValues):
                        ls.update(toflat([*keys, key], entry.value))
                    else:
                        ls[".".join([*keys, key])] = entry.value
                return ls

            return model.ServerConfig(**toflat([], server._config))

        @api.put(
            "/server/{server_id}/config",
            summary="サーバー設定の更新",
            description="サーバーの設定を変更します",
        )
        async def _put_config(server_id: str, param: model.ServerConfig, ) -> model.ServerConfig:
            server = getserver(server_id)

            config = server._config  # type: ServerConfig
            for key, value in param.model_dump(exclude_unset=True).items():
                conf = config

                key = key.split("__")
                while 2 <= len(key):
                    conf = getattr(conf, key.pop(0))
                setattr(conf, key[0], value)

            server._config.save(force=True)
            return await _get_config(server_id)
        
        return api

    def _file(self):
        api = APIRouter(
            tags=["File", ],
            dependencies=[Depends(self.get_authorized_user), ],
        )

        def realpath(swi_path: str, root_dir: Path = None):
            try:
                return self.files.realpath(swi_path, root_dir=root_dir)
            except ValueError:
                raise APIErrorCode.NOT_ALLOWED_PATH.of(f"Unable to access: {swi_path}")

        def create_file_info(path: PairPath | Path, root_dir: Path = None):
            if isinstance(path, PairPath):
                _path = path.real
                root_dir = root_dir or path.root_dir
            else:
                _path = path

            return self.inst.create_file_info(_path, root_dir=root_dir)

        def wait_for_task(task: FileTask, timeout: float | None = 1) -> Coroutine[Any, Any, FileTask]:
            return asyncio.wait_for(asyncio.shield(task.fut), timeout=timeout)

        # param

        def get_server(server_id: str) -> "ServerProcess":
            try:
                server = self.servers[server_id.lower()]
            except KeyError:
                raise APIErrorCode.SERVER_NOT_FOUND.of("Server not found", 404)

            if server is None:
                raise APIErrorCode.SERVER_NOT_LOADED.of("Server config not loaded", 404)
            return server

        def get_pair_path(swi_path: str, *, server: "ServerProcess" = None):
            root_dir = server and server.directory or None  # type: Path | None
            try:
                real_path = self.files.realpath(swi_path, root_dir=root_dir)
            except ValueError as e:
                raise APIErrorCode.NOT_ALLOWED_PATH.of(f"{e}: {swi_path}")
            swi_path = self.files.swipath(real_path, force=True, root_dir=root_dir)
            return PairPath(real_path, swi_path, server, root_dir)

        def get_path_of_root(query: str | Query = None, *, is_dir=False, is_file=False, exists=False, no_exists=False):
            if query is None or isinstance(query, Query):
                name = query and query.alias or "path"
            else:
                name = "path"
                query = Query(description=query)

            def check(path: str = query) -> PairPath:
                p = get_pair_path(path)
                if no_exists and p.real.exists():
                    raise APIErrorCode.ALREADY_EXISTS_PATH.of(f"Already exists: {name!r}")
                elif is_dir and not p.real.is_dir():
                    raise APIErrorCode.NOT_EXISTS_DIRECTORY.of(f"Not a directory or not exists: {name!r}", 404)
                elif is_file and not p.real.is_file():
                    raise APIErrorCode.NOT_EXISTS_FILE.of(f"Not a file or not exists: {name!r}", 404)
                elif exists and not p.real.exists():
                    raise APIErrorCode.NOT_EXISTS_PATH.of(f"Not exists: {name!r}", 404)
                return p
            return check

        def get_path_of_server_root(query: str | Query = None, *, is_dir=False, is_file=False, exists=False, no_exists=False):
            if query is None or isinstance(query, Query):
                name = query and query.alias or "path"
            else:
                name = "path"
                query = Query(description=query)

            def check(path: str = query, server: "ServerProcess" = Depends(get_server)) -> PairPath:
                p = get_pair_path(path, server=server)
                if no_exists and p.real.exists():
                    raise APIErrorCode.ALREADY_EXISTS_PATH.of(f"Already exists: {name!r}")
                elif is_dir and not p.real.is_dir():
                    raise APIErrorCode.NOT_EXISTS_DIRECTORY.of(f"Not a directory or not exists: {name!r}", 404)
                elif is_file and not p.real.is_file():
                    raise APIErrorCode.NOT_EXISTS_FILE.of(f"Not a file or not exists: {name!r}", 404)
                elif exists and not p.real.exists():
                    raise APIErrorCode.NOT_EXISTS_PATH.of(f"Not exists: {name!r}", 404)
                return p
            return check

        # method

        @api.get(
            "/file/tasks",
            summary="ファイルタスクの一覧",
            description="実行中のファイル操作タスクのリストを返す",
        )
        def _file_tasks() -> list[model.FileTask]:
            return [model.FileTask.create(task) for task in self.files.tasks]

        @api.get(
            "/files",
            summary="ファイルの一覧",
            description="指定されたパスのファイルリストを返す",
        )
        async def _files(
                path: PairPath = Depends(get_path_of_root(is_dir=True)),
        ) -> model.FileDirectoryInfo:

            file_list = []
            try:
                for child in path.real.iterdir():
                    try:
                        file_list.append(create_file_info(child, path.root_dir))
                    except Exception as e:
                        log.warning("Failed to get file info: %s: %s", str(child), str(e))
            except PermissionError as e:
                raise APIErrorCode.NOT_ALLOWED_PATH.of(f"Unable to access: {e}")

            return model.FileDirectoryInfo(
                name="" if path.swi == "/" else path.real.name,
                path=self.files.swipath(path.real.parent, force=True),
                children=file_list,
            )

        @api.get(
            "/file",
            summary="ファイルデータを取得",
            description="",
        )
        def _get_file(
                path: PairPath = Depends(get_path_of_root(is_file=True)),
        ):
            return FileResponse(path.real, filename=path.real.name)

        @api.post(
            "/file",
            summary="ファイルデータを保存",
            description="",
        )
        def _post_file(
                file: UploadFile,
                path: PairPath = Depends(get_path_of_root(is_file=True)),
        ) -> model.FileInfo:

            try:
                with path.real.open("wb") as f:
                    shutil.copyfileobj(file.file, f)

            finally:
                file.file.close()

            return create_file_info(path, path.root_dir)

        @api.delete(
            "/file",
            summary="ファイルを削除",
            description="",
        )
        async def _delete_file(
                path: PairPath = Depends(get_path_of_root(exists=True)),
        ) -> model.FileOperationResult:

            task = self.files.delete(path.real, path.server, path.swi)
            try:
                await wait_for_task(task)
            except asyncio.TimeoutError:
                return model.FileOperationResult.pending(task.id)
            except Exception as e:
                log.warning(f"Failed to delete: {e}: {path}")
                return model.FileOperationResult.failed(task.id)
            else:
                return model.FileOperationResult.success(task.id, None)

        @api.post(
            "/file/mkdir",
            summary="空のディレクトリ作成",
            description="",
        )
        async def _mkdir(
                path: PairPath = Depends(get_path_of_root(no_exists=True)),
                
        ) -> model.FileOperationResult:
            try:
                await self.files.mkdir(path.real)
            except Exception as e:
                log.warning(f"Failed to mkdir: {e}: {path}")
                return model.FileOperationResult.failed(None)
            else:
                return model.FileOperationResult.success(None, create_file_info(path))

        @api.put(
            "/file/copy",
            summary="ファイル複製",
            description="",
        )
        async def _copy(
                path: PairPath = Depends(get_path_of_root(exists=True)),
                dst_path: PairPath = Depends(get_path_of_root(Query(alias="dst_path"), no_exists=True)),
        ) -> model.FileInfo:

            task = self.files.copy(
                path.real, dst_path.real,
                server=path.server, src_swi_path=path.swi, dst_swi_path=dst_path.swi,
            )
            try:
                await wait_for_task(task)
            except asyncio.TimeoutError:
                return model.FileOperationResult.pending(task.id)
            except Exception as e:
                log.warning(f"Failed to copy: {e}: {path}")
                return model.FileOperationResult.failed(task.id)
            else:
                return model.FileOperationResult.success(task.id, create_file_info(dst_path))

        @api.put(
            "/file/move",
            summary="ファイル移動",
            description="",
        )
        async def _move(
                path: PairPath = Depends(get_path_of_root(exists=True)),
                dst_path: PairPath = Depends(get_path_of_root(Query(alias="dst_path"), no_exists=True)),
        ) -> model.FileInfo:

            task = self.files.move(
                path.real, dst_path.real,
                server=path.server, src_swi_path=path.swi, dst_swi_path=dst_path.swi,
            )
            try:
                await wait_for_task(task)
            except asyncio.TimeoutError:
                return model.FileOperationResult.pending(task.id)
            except Exception as e:
                log.warning(f"Failed to move: {e}: {path}")
                return model.FileOperationResult.failed(task.id)
            else:
                return model.FileOperationResult.success(task.id, create_file_info(dst_path))

        @api.post(
            "/file/archive/files",
            summary="アーカイブ内のファイル一覧",
            description="",
        )
        async def _archive_files(
                path: PairPath = Depends(get_path_of_root("アーカイブファイルのパス", is_file=True)),
                password: str | None = Form(None),
                ignore_suffix: bool = Query(False, description="拡張子に関わらずファイルを処理する"),
        ) -> list[model.ArchiveFile]:
            try:
                arc_files = await self.files.list_archive(path.real, password=password, ignore_suffix=ignore_suffix)
            except RuntimeError as e:
                raise APIErrorCode.NO_SUPPORTED_ARCHIVE_FORMAT.of(str(e))
            return [model.ArchiveFile.create(arc_file) for arc_file in arc_files]

        @api.post(
            "/file/archive/extract",
            summary="アーカイブの展開",
            description="",
        )
        async def _archive_extract(
                path: PairPath = Depends(get_path_of_root("アーカイブファイルのパス", is_file=True)),
                output_dir: PairPath = Depends(get_path_of_root(Query(alias="output_dir", description="解凍先のフォルダパス"))),
                password: str | None = Form(None),
                ignore_suffix: bool = Query(False, description="拡張子に関わらずファイルを処理する"),
                
        ) -> model.FileOperationResult:

            if not output_dir.real.parent.is_dir():
                raise APIErrorCode.NOT_EXISTS_DIRECTORY.of("Output path parent is not exists", 404)

            try:
                task = await self.files.extract_archive(
                    path.real, output_dir.real, password,
                    server=path.server, src_swi_path=path.swi, dst_swi_path=output_dir.swi, ignore_suffix=ignore_suffix,
                )
            except RuntimeError as e:
                raise APIErrorCode.NO_SUPPORTED_ARCHIVE_FORMAT.of(str(e))
            return model.FileOperationResult.pending(task.id)

        @api.post(
            "/file/archive/make",
            summary="アーカイブファイルの作成",
            description="",
        )
        async def _archive_make(
                path: PairPath = Depends(get_path_of_root("アーカイブファイルのパス", no_exists=True)),
                files_root: PairPath = Depends(get_path_of_root(Query(alias="files_root", description="格納するファイルのルートパス"))),
                include_files: list[str] = Query(description="格納するファイルのパス"),
        ) -> model.FileOperationResult:

            try:
                include_files = [realpath(p, root_dir=files_root.root_dir) for p in include_files]
            except APIError:
                raise

            if not any(p.exists() for p in include_files):
                raise APIErrorCode.NOT_EXISTS_PATH.of("No files")

            try:
                task = await self.files.make_archive(
                    path.real, files_root.real, include_files,
                    server=path.server, src_swi_path=path.swi,
                )
            except RuntimeError as e:
                raise APIErrorCode.NO_SUPPORTED_ARCHIVE_FORMAT.of(str(e))
            return model.FileOperationResult.pending(task.id)

        # server

        @api.get(
            "/server/{server_id}/files",
            summary="ファイルの一覧",
            description="指定されたパスのファイルリストを返す",
        )
        async def _server_files(
                path: PairPath = Depends(get_path_of_server_root(is_dir=True)),
        ) -> model.FileDirectoryInfo:
            return await _files(path)

        @api.get(
            "/server/{server_id}/file",
            summary="ファイルデータを取得",
            description="",
        )
        def _server_get_file(
                path: PairPath = Depends(get_path_of_server_root(is_file=True)),
        ):
            return _get_file(path)

        @api.post(
            "/server/{server_id}/file",
            summary="ファイルデータを保存",
            description="",
        )
        def _server_post_file(
                file: UploadFile,
                path: PairPath = Depends(get_path_of_server_root(is_file=True)),
        ) -> model.FileInfo:
            return _post_file(file, path)

        @api.delete(
            "/server/{server_id}/file",
            summary="ファイルを削除",
            description="",
        )
        async def _server_delete_file(
                path: PairPath = Depends(get_path_of_server_root(exists=True)),
        ) -> model.FileOperationResult:
            return await _delete_file(path)

        @api.post(
            "/server/{server_id}/file/mkdir",
            summary="空のディレクトリ作成",
            description="",
        )
        async def _server_mkdir(
                path: PairPath = Depends(get_path_of_server_root(no_exists=True)),
        ) -> model.FileOperationResult:
            return await _mkdir(path)

        @api.put(
            "/server/{server_id}/file/copy",
            summary="ファイル複製",
            description="",
        )
        async def _server_copy(
                path: PairPath = Depends(get_path_of_server_root(exists=True)),
                dst_path: PairPath = Depends(get_path_of_server_root(Query(alias="dst_path"), no_exists=True)),
        ) -> model.FileInfo:
            return await _copy(path, dst_path)

        @api.put(
            "/server/{server_id}/file/move",
            summary="ファイル移動",
            description="",
        )
        async def _server_move(
                path: PairPath = Depends(get_path_of_server_root(exists=True)),
                dst_path: PairPath = Depends(get_path_of_server_root(Query(alias="dst_path"), no_exists=True)),
        ) -> model.FileInfo:
            return await _move(path, dst_path)

        @api.post(
            "/server/{server_id}/file/archive/files",
            summary="アーカイブ内のファイル一覧",
            description="",
        )
        async def _server_archive_files(
                path: PairPath = Depends(get_path_of_server_root("アーカイブファイルのパス", is_file=True)),
                password: str | None = Form(None),
                ignore_suffix: bool = Query(False, description="拡張子に関わらずファイルを処理する"),
        ) -> list[model.ArchiveFile]:
            return await _archive_files(path, password, ignore_suffix)

        @api.post(
            "/server/{server_id}/file/archive/extract",
            summary="アーカイブの展開",
            description="",
        )
        async def _server_archive_extract(
                path: PairPath = Depends(get_path_of_server_root("アーカイブファイルのパス", is_file=True)),
                output_dir: PairPath = Depends(get_path_of_server_root(Query(alias="output_dir", description="解凍先のフォルダパス"))),
                password: str | None = Form(None),
                ignore_suffix: bool = Query(False, description="拡張子に関わらずファイルを処理する"),

        ) -> model.FileOperationResult:
            return await _archive_extract(path, output_dir, password, ignore_suffix)

        @api.post(
            "/server/{server_id}/file/archive/make",
            summary="アーカイブファイルの作成",
            description="",
        )
        async def _server_archive_make(
                path: PairPath = Depends(get_path_of_server_root("アーカイブファイルのパス", no_exists=True)),
                files_root: PairPath = Depends(get_path_of_server_root(Query(alias="files_root", description="格納するファイルのルートパス"))),
                include_files: list[str] = Query(description="格納するファイルのパス"),
        ) -> model.FileOperationResult:
            return await _archive_make(path, files_root, include_files)

        return api
