import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from .abc import *
from .archive.helper import ZipArchiveHelper
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
