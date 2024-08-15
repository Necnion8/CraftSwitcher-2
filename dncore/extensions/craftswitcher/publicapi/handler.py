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
        async def _start(server_id: str) -> model.OperationResult:
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

            return model.OperationResult(result=True)

        @api.post(
            "/server/{server_id}/stop",
            tags=tags,
            summary="サーバーを停止",
            description="サーバーを停止します",
        )
        async def _stop(server_id: str) -> model.OperationResult:
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

            return model.OperationResult(result=True)

        @api.post(
            "/server/{server_id}/restart",
            tags=tags,
            summary="サーバーを再起動",
            description="サーバーを再起動します",
        )
        async def _restart(server_id: str) -> model.OperationResult:
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

            return model.OperationResult(result=True)
