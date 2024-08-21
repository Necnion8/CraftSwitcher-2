from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException

from dncore.configuration.configuration import ConfigValueEntry, ConfigValues
from dncore.extensions.craftswitcher import errors
from dncore.extensions.craftswitcher.publicapi import model

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import CraftSwitcher
    from dncore.extensions.craftswitcher.config import ServerConfig


class APIHandler(object):
    def __init__(self, inst: "CraftSwitcher", api: FastAPI):
        self.inst = inst
        self.router = api
        self._app(api)
        self._server(api)

    def _app(self, api: FastAPI):
        tags = ["App"]
        inst = self.inst  # type: CraftSwitcher

        @api.get(
            "/config/server_global",
            tags=tags,
            summary="",
            description="",
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
            tags=tags,
            summary="",
            description="",
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

    def _server(self, api: FastAPI):
        tags = ["Server"]
        inst = self.inst  # type: CraftSwitcher
        servers = self.inst.servers
        
        def getserver(server_id: str):
            try:
                server = servers[server_id.lower()]
            except KeyError:
                raise HTTPException(status_code=404, detail="Server not found")

            if server is None:
                raise HTTPException(status_code=404, detail="Server config not loaded")
            return server

        @api.get(
            "/servers",
            tags=tags,
            summary="登録サーバーの一覧",
            description="登録されているサーバーを返します",
        )
        async def _list(only_loaded: bool = False) -> list[model.Server]:
            ls = []  # type: list[model.Server]

            for server_id, server in servers.items():
                if server:
                    ls.append(model.Server.create(server))
                elif not only_loaded:
                    try:
                        server_dir = self.inst.config.servers[server_id]
                    except KeyError:
                        continue  # 外部から削除または変更されていた場合はリストから静かに除外する
                    ls.append(model.Server.create_no_data(server_id, server_dir))

            return ls

        @api.post(
            "/server/{server_id}/start",
            tags=tags,
            summary="サーバーを起動",
            description="サーバーを起動します",
        )
        async def _start(server_id: str) -> model.ServerOperationResult:
            server = getserver(server_id)

            try:
                await server.start()
            except errors.AlreadyRunningError:
                raise HTTPException(status_code=400, detail="Already running")
            except errors.OutOfMemoryError:
                raise HTTPException(status_code=400, detail="Out of memory")
            except errors.ServerLaunchError as e:
                raise HTTPException(status_code=400, detail=f"Failed to launch: {e}")
            except errors.OperationCancelledError as e:
                raise HTTPException(status_code=400, detail=f"Operation cancelled: {e}")

            return model.ServerOperationResult(result=True)

        @api.post(
            "/server/{server_id}/stop",
            tags=tags,
            summary="サーバーを停止",
            description="サーバーを停止します",
        )
        async def _stop(server_id: str) -> model.ServerOperationResult:
            server = getserver(server_id)

            try:
                await server.stop()
            except errors.NotRunningError:
                raise HTTPException(status_code=400, detail="Not running")
            except errors.ServerProcessingError:
                raise HTTPException(status_code=400, detail="Server is processing")

            return model.ServerOperationResult.success(server.id)

        @api.post(
            "/server/{server_id}/restart",
            tags=tags,
            summary="サーバーを再起動",
            description="サーバーを再起動します",
        )
        async def _restart(server_id: str) -> model.ServerOperationResult:
            server = getserver(server_id)

            try:
                await server.restart()
            except errors.NotRunningError:
                raise HTTPException(status_code=400, detail="Not running")
            except errors.ServerProcessingError:
                raise HTTPException(status_code=400, detail="Server is processing")

            return model.ServerOperationResult.success(server.id)

        @api.post(
            "/server/{server_id}/kill",
            tags=tags,
            summary="サーバーを強制終了",
            description="サーバーを強制終了します",
        )
        async def _kill(server_id: str) -> model.ServerOperationResult:
            server = getserver(server_id)

            try:
                await server.kill()
            except errors.NotRunningError:
                raise HTTPException(status_code=400, detail="Not running")

            return model.ServerOperationResult.success(server.id)

        @api.post(
            "/server/{server_id}/import",
            tags=tags,
            summary="構成済みのサーバーを追加",
            description="構成済みのサーバーを登録します",
        )
        async def _add(server_id: str, param: model.AddServerParam) -> model.ServerOperationResult:
            server_id = server_id.lower()
            if server_id in servers:
                raise HTTPException(status_code=400, detail="Already exists server id")

            if not Path(param.directory).is_dir():
                raise HTTPException(status_code=400, detail="Not exists directory")

            try:
                config = inst.import_server_config(param.directory)
            except FileNotFoundError:
                raise HTTPException(status_code=400, detail="Not exists server config")

            server = inst.create_server(server_id, param.directory, config, set_creation_date=False)
            return model.ServerOperationResult.success(server.id)

        @api.post(
            "/server/{server_id}",
            tags=tags,
            summary="サーバーを作成",
            description="サーバーを作成します",
        )
        async def _create(server_id: str, param: model.CreateServerParam) -> model.ServerOperationResult:
            server_id = server_id.lower()
            if server_id in servers:
                raise HTTPException(status_code=400, detail="Already exists server id")

            if not Path(param.directory).is_dir():
                raise HTTPException(status_code=400, detail="Not exists directory")

            config = inst.create_server_config(param.directory)
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

            server = inst.create_server(server_id, param.directory, config)
            return model.ServerOperationResult.success(server.id)

        @api.delete(
            "/server/{server_id}",
            tags=tags,
            summary="サーバーを削除",
            description="サーバーを削除します",
        )
        async def _delete(server_id: str, delete_config_file: bool = False) -> model.ServerOperationResult:
            server = getserver(server_id)

            if server.state.is_running:
                raise HTTPException(status_code=400, detail="Already running")

            inst.delete_server(server, delete_server_config=delete_config_file)
            return model.ServerOperationResult.success(server.id)

        @api.get(
            "/server/{server_id}/config",
            tags=tags,
            summary="サーバー設定の取得",
            description="サーバーの設定を返します",
        )
        async def _get_config(server_id: str) -> model.ServerConfig:
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
            tags=tags,
            summary="サーバー設定の更新",
            description="サーバーの設定を変更します",
        )
        async def _put_config(server_id: str, param: model.ServerConfig) -> model.ServerConfig:
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
