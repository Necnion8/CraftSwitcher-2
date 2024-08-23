import asyncio
import os
import shutil
from pathlib import Path

from .abc import *
from .event import *
from ..utils import call_event


class FileManager(object):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self._task_id = -1
        self.tasks = set()  # type: set[FileTask]

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

    def create_task(self, event_type: FileEventType, src: Path, dst: Path | None, fut: asyncio.Future):
        """
        ファイルタスクを作成します
        """
        if fut.done():
            raise ValueError("Already task completed")
        task = FileTask(self._add_task_id(), event_type, src, dst, fut)
        self._add_task_callback(task)
        self.tasks.add(task)
        call_event(FileTaskStartEvent(task))
        return task

    def create_task_in_executor(self, event_type: FileEventType, src: Path, dst: Path | None, do_task, executor=None):
        fut = self.loop.run_in_executor(executor, do_task)
        return self.create_task(event_type, src, dst, fut)

    # method

    def copy(self, src: Path, dst: Path):
        """
        ファイルをコピーするタスクを作成し、実行します。
        """
        def _do():
            shutil.copyfile(src, dst)

        return self.create_task_in_executor(FileEventType.COPY, src, dst, _do)

    def move(self, src: Path, dst: Path):
        """
        ファイルをコピーするタスクを作成し、実行します。
        """
        def _do():
            shutil.move(src, dst)

        return self.create_task_in_executor(FileEventType.MOVE, src, dst, _do)

    def delete(self, src: Path):
        """
        ファイルを削除するタスクを作成し、実行します。
        """
        def _do():
            if src.is_dir():
                shutil.rmtree(src)
            else:
                os.remove(src)

        return self.create_task_in_executor(FileEventType.DELETE, src, None, _do)

    async def mkdir(self, src: Path):
        """
        ディレクトリを作成します
        """
        def _do():
            src.mkdir()

        await self.loop.run_in_executor(None, _do)
