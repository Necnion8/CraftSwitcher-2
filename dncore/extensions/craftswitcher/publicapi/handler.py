from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException

from dncore.extensions.craftswitcher import errors
from dncore.extensions.craftswitcher.publicapi import model

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import CraftSwitcher


class APIHandler(object):
    def __init__(self, inst: "CraftSwitcher", api: FastAPI):
        self.inst = inst
        self.router = api
        self._server(api)

    def _server(self, api: FastAPI):
        tags = ["Server"]
        inst = self.inst  # type: CraftSwitcher
        servers = self.inst.servers

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
            try:
                server = servers[server_id.lower()]
            except KeyError:
                raise HTTPException(status_code=404, detail="Server not found")

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
            try:
                server = servers[server_id.lower()]
            except KeyError:
                raise HTTPException(status_code=404, detail="Server not found")

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
            try:
                server = servers[server_id.lower()]
            except KeyError:
                raise HTTPException(status_code=404, detail="Server not found")

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
            try:
                server = servers[server_id.lower()]
            except KeyError:
                raise HTTPException(status_code=404, detail="Server not found")

            try:
                await server.kill()
            except errors.NotRunningError:
                raise HTTPException(status_code=400, detail="Not running")

            return model.ServerOperationResult.success(server.id)

        @api.post(
            "/server/{server_id}/create",
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

        @api.post(
            "/server/{server_id}/add",
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
