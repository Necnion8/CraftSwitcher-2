import asyncio
import os
import re
import shutil
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp

from .abc import *
from .archive import ArchiveFile, ArchiveHelper
from .archive.helper import ZipArchiveHelper
from .archive.sevenziphelper import SevenZipHelper
from .event import *
from ..utils import call_event

if TYPE_CHECKING:
    from dncore.extensions.craftswitcher import ServerProcess


class FileManager(object):
    def __init__(self, loop: asyncio.AbstractEventLoop, root_dir: Path):
        self.loop = loop
        self._task_id = -1
        self.tasks = set()  # type: set[FileTask]
        self.root_dir = root_dir.resolve()
        #
        self.archive_helpers = [
            SevenZipHelper(),
            ZipArchiveHelper(),
        ]

    # util

    def realpath(self, swi_path: str, *, force=False, root_dir: Path = None):
        """
        SWIパスを正規化し、rootDirを基準にシステムパスに変換します

        安全ではないパスの場合は :class:`ValueError` が発生します

        :arg swi_path: SWIパス
        :arg force: 安全でない場合は例外を出さずに安全に処理します
        :arg root_dir: ルートディレクトリ。Noneの時は、設定されたrootDirを使用します。
        """
        return (root_dir or self.root_dir) / self.resolvepath(swi_path, force=force).lstrip("/")

    def resolvepath(self, swi_path: str, *, force=False):
        """
        SWIパスを正規化します

        安全ではないパスの場合は :class:`ValueError` を発生させます

        :arg swi_path: SWIパス
        :arg force: 例外を出さずに安全に処理します
        """
        regex = re.compile(r"^([a-zA-Z]:/*|/+)")
        swi_path = swi_path.replace("\\", "/")
        match = regex.match(swi_path)
        while match:  # 絶対パス(C:\\や/)を除外する
            swi_path = swi_path[match.end():]
            match = regex.match(swi_path)

        new_parts = []
        for part in swi_path.split("/"):
            if part == "..":
                if not new_parts:
                    if force:
                        continue
                    raise ValueError("Not allowed path")
                new_parts.pop(-1)
            else:
                new_parts.append(part)
        return "/" + "/".join(new_parts)

    def swipath(self, realpath: str | Path, *, force=False, root_dir: Path = None):
        """
        システムパスをSWIパスに変換します

        指定されたパスがrootDir外である場合は :class:`ValueError` を発生させます

        :arg realpath: システムパス
        :arg force: 例外を出さずに安全に処理します
        :arg root_dir: ルートディレクトリ。Noneの時は、設定されたrootDirを使用します。
        """
        realpath = (realpath if isinstance(realpath, Path) else Path(realpath)).resolve()

        try:
            parts = realpath.relative_to(root_dir or self.root_dir).parts
        except ValueError:
            if not force:
                raise ValueError("Not allowed path")
            return "/"

        return "/" + "/".join(parts)

    # task

    def _add_task_id(self):
        self._task_id += 1
        return self._task_id

    def _add_task_callback(self, task: FileTask):
        def _done(_):
            self.tasks.discard(task)
            if task.fut.exception() is None:
                task.result = FileTaskResult.SUCCESS
            else:
                task.result = FileTaskResult.FAILED
            call_event(FileTaskEndEvent(task, task.fut.exception()))

        task.fut.add_done_callback(_done)

    def create_task(self, event_type: FileEventType, src: Path, dst: Path | None, fut: asyncio.Future,
                    server: "ServerProcess" = None, src_swi_path: str = None, dst_swi_path: str = None, ):
        """
        ファイルタスクを作成します
        """
        if fut.done():
            raise ValueError("Already task completed")
        task = FileTask(self._add_task_id(), event_type, src, dst, fut, server, src_swi_path, dst_swi_path)
        self._add_task_callback(task)
        self.tasks.add(task)
        call_event(FileTaskStartEvent(task))
        return task

    def create_task_in_executor(self, event_type: FileEventType, src: Path, dst: Path | None, do_task, executor=None,
                                server: "ServerProcess" = None, src_swi_path: str = None, dst_swi_path: str = None, ):
        fut = self.loop.run_in_executor(executor, do_task)
        return self.create_task(event_type, src, dst, fut, server, src_swi_path, dst_swi_path)

    # method

    def copy(self, src: Path, dst: Path,
             server: "ServerProcess" = None, src_swi_path: str = None, dst_swi_path: str = None, ):
        """
        ファイルをコピーするタスクを作成し、実行します。
        """
        def _do():
            shutil.copyfile(src, dst)

        return self.create_task_in_executor(
            FileEventType.COPY, src, dst, _do, executor=None,
            server=server, src_swi_path=src_swi_path, dst_swi_path=dst_swi_path,
        )

    def move(self, src: Path, dst: Path,
             server: "ServerProcess" = None, src_swi_path: str = None, dst_swi_path: str = None, ):
        """
        ファイルをコピーするタスクを作成し、実行します。
        """
        def _do():
            shutil.move(src, dst)

        return self.create_task_in_executor(
            FileEventType.MOVE, src, dst, _do, executor=None,
            server=server, src_swi_path=src_swi_path, dst_swi_path=dst_swi_path,
        )

    def delete(self, src: Path,
               server: "ServerProcess" = None, src_swi_path: str = None, dst_swi_path: str = None, ):
        """
        ファイルを削除するタスクを作成し、実行します。
        """
        def _do():
            if src.is_dir():
                shutil.rmtree(src)
            else:
                os.remove(src)

        return self.create_task_in_executor(
            FileEventType.DELETE, src, None, _do, executor=None,
            server=server, src_swi_path=src_swi_path, dst_swi_path=dst_swi_path,
        )

    async def mkdir(self, src: Path):
        """
        ディレクトリを作成します
        """
        def _do():
            src.mkdir()

        await self.loop.run_in_executor(None, _do)

    @staticmethod
    async def fetch_download_filename(url: str):
        filename = None
        async with aiohttp.request("HEAD", url) as res:
            res.raise_for_status()
            disposition = res.content_disposition
            if disposition:
                filename = disposition.filename
        if not filename:
            filename = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
        return filename

    def download(self, src_url: str, dst: Path,
                 server: "ServerProcess" = None, src_swi_path: str = None, dst_swi_path: str = None):

        async def _download():
            async with aiohttp.request("GET", src_url) as res:
                res.raise_for_status()

                total_bytes = res.content_length
                total_read = 0

                try:
                    with dst.open("wb") as f:
                        while data := await res.content.read(1024 * 512):
                            f.write(data)
                            total_read += len(data)
                            if 0 < total_bytes:
                                task.progress = total_read / total_bytes
                except Exception:
                    try:
                        os.remove(dst)
                    except (Exception,):
                        pass
                    raise

        task = self.create_task(  # TODO: srcがPathしか受け入れられないために、ソースURLが設定できない
            FileEventType.DOWNLOAD, dst, dst, asyncio.create_task(_download()),
            server, src_swi_path, dst_swi_path, )
        return task

    # archive

    @property
    def _available_archive_helpers(self):
        return filter(lambda h: h.available(), self.archive_helpers)

    def find_archive_helper(self, path: Path, *, ignore_suffix=False) -> ArchiveHelper | None:
        """
        ファイルの拡張子に従い、利用できるヘルパーを返します
        """
        suffix_name = path.suffix[1:].lower()
        for helper in self._available_archive_helpers:
            if ignore_suffix or suffix_name in helper.available_formats():
                return helper

    async def is_archive(self, src: Path, *, ignore_suffix=False) -> bool:
        """
        指定されたファイルがアーカイブファイルかどうかチェックします
        """
        suffix_name = src.suffix[1:].lower()
        return any(
            (ignore_suffix or suffix_name in h.available_formats()) and await h.is_archive(src)
            for h in self._available_archive_helpers
        )

    async def list_archive(self, src: Path, password: str = None, *, ignore_suffix=False) -> list[ArchiveFile]:
        """
        指定されたアーカイブファイルに格納されているファイルを返します
        """
        suffix_name = src.suffix[1:].lower()

        for helper in self._available_archive_helpers:
            if suffix_name in helper.available_formats() or (ignore_suffix and await helper.is_archive(src)):
                return await helper.list_archive(src, password=password)

        raise RuntimeError("No supported archive helper")

    async def extract_archive(self, archive: Path, extract_dir: Path, password: str = None,
                              server: "ServerProcess" = None, src_swi_path: str = None, dst_swi_path: str = None,
                              *, ignore_suffix=False):
        """
        格納されてるファイルを展開します
        """
        suffix_name = archive.suffix[1:].lower()

        for helper in self._available_archive_helpers:
            if suffix_name in helper.available_formats() or (ignore_suffix and await helper.is_archive(archive)):
                break
        else:
            raise RuntimeError("No supported archive helper")

        async def _progressing():
            async for progress in helper.extract_archive(archive, extract_dir, password=password):
                task.progress = progress.progress

        task = self.create_task(
            FileEventType.EXTRACT_ARCHIVE,
            archive, extract_dir,
            asyncio.get_running_loop().create_task(_progressing()),
            server, src_swi_path, dst_swi_path,
        )
        return task

    async def make_archive(self, archive: Path, files_root: Path, files: list[Path],
                           server: "ServerProcess" = None, src_swi_path: str = None,
                           ):
        """
        ファイルを圧縮します

        格納される各ファイルのパスは files_root を基準に相対パスに変換されます
        """
        suffix_name = archive.suffix[1:].lower()

        for helper in self._available_archive_helpers:
            if suffix_name in helper.available_formats():
                break
        else:
            raise RuntimeError("No supported archive helper by suffix")

        async def _progressing():
            async for progress in helper.make_archive(archive, files_root, files):
                task.progress = progress.progress

        task = self.create_task(
            FileEventType.EXTRACT_ARCHIVE,
            archive, None,
            asyncio.get_running_loop().create_task(_progressing()),
            server, src_swi_path, None,
        )
        return task
