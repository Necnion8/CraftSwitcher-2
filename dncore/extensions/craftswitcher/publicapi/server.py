import asyncio
import mimetypes
from urllib.parse import quote

import uvicorn
from starlette.exceptions import HTTPException
from starlette.responses import StreamingResponse as _StreamingResponse, ContentStream
from starlette.staticfiles import StaticFiles


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


class FallbackStaticFiles(StaticFiles):
    fallback_path = "index.html"

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code == 404:
                return await super().get_response(self.fallback_path, scope)
            raise


class StreamingResponse(_StreamingResponse):
    def __init__(self, content: ContentStream, filename: str, headers: dict[str, str] = None):
        media_type = mimetypes.guess_type(filename)[0] or None
        headers = headers or {}
        self.set_attached_file_header(headers, filename)
        super().__init__(content, headers=headers, media_type=media_type)

    @staticmethod
    def set_attached_file_header(headers: dict[str, str], filename: str):
        content_disposition_filename = quote(filename)
        if content_disposition_filename != filename:
            content_disposition = "attachment; filename*=utf-8''{}".format(content_disposition_filename)
        else:
            content_disposition = 'attachment; filename="{}"'.format(filename)
        headers.setdefault("content-disposition", content_disposition)
