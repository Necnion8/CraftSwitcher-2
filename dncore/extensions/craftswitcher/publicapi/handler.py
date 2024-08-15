from typing import TYPE_CHECKING

from fastapi import FastAPI

from dncore.extensions.craftswitcher.publicapi import model

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import CraftSwitcher


class APIHandler(object):
    def __init__(self, inst: "CraftSwitcher", api: FastAPI):
        self.inst = inst
        self.router = api
        self._server(api)

    def _server(self, api: FastAPI):
        servers = self.inst.servers

        @api.get(
            "/servers",
            tags=["Server"],
            description="Server List",
            response_model=list[model.Server],
        )
        async def _list():
            ls = []  # type: list[model.Server]

            for server_id, server in servers.items():
                if server:
                    ls.append(model.Server.create(server))
                else:
                    try:
                        server_dir = self.inst.config.servers[server_id]
                    except KeyError:
                        continue  # 外部から削除または変更されていた場合はリストから静かに除外する
                    ls.append(model.Server.create_no_data(server_id, server_dir))

            return ls
