import asyncio

import uvicorn


class UvicornServer(object):
    def __init__(self):
        self._server = None  # type: uvicorn.Server | None
        self._runner = None  # type: asyncio.Task | None

    async def start(self, app: "ASGIApplication | Callable | str", *,
                    host="127.0.0.1", port=8000, path="",
                    ssl_keyfile: str = None, ssl_certfile: str = None, ):
        if self._runner and not self._runner.done():
            raise RuntimeError("Already started server")

        config = uvicorn.Config(
            app, host, port, root_path=path, server_header=False,
            ssl_keyfile=ssl_keyfile, ssl_certfile=ssl_certfile,
        )
        self._server = server = uvicorn.Server(config)
        self._runner = asyncio.get_event_loop().create_task(server.serve())

    async def shutdown(self):
        if self._server:
            await self._server.shutdown()
        if self._runner:
            self._runner.cancel()
        self._server = self._runner = None

