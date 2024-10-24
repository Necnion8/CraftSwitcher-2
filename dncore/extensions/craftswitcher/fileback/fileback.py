import asyncio
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .abc import *
from ..errors import AlreadyBackupError
from ..utils import datetime_now

if TYPE_CHECKING:
    from ..config import Backup as BackupConfig
    from ..database import SwitcherDatabase
    from ..files import FileManager
    from ..serverprocess import ServerProcess

__all__ = [
    "create_backup_filename",
    "Backupper",
]


def create_backup_filename(comments: str = None):
    backup_dt = datetime_now()
    archive_file_name = backup_dt.strftime("%Y%m%d_%H%M%S")

    if comments:
        comments = re.sub(r"[\\/:*?\"<>|]+", "_", comments)
        if comments:
            archive_file_name += f"_{comments}"

    return archive_file_name


class Backupper(object):
    def __init__(self, loop: asyncio.AbstractEventLoop,
                 *, config: "BackupConfig", database: "SwitcherDatabase", files: "FileManager",
                 backups_dir: Path, trash_dir: Path, ):
        self.loop = loop
        self.config = config
        self._db = database
        self._files = files
        self._backups_dir = backups_dir
        self._trash_dir = trash_dir
        #
        self._tasks = {}  # type: dict[ServerProcess, BackupTask]

    @property
    def backups_dir(self):
        return self._backups_dir

    @property
    def trash_dir(self):
        return self._trash_dir

    def get_running_task_by_server(self, server: "ServerProcess"):
        return self._tasks.get(server)

    async def create_backup(self, server: "ServerProcess", comments: str = None) -> BackupTask:
        """
        指定サーバーのバックアップを作成します

        :except NoArchiveHelperError: 対応するアーカイブヘルパーが見つからない
        :except AlreadyBackupError: すでにバックアップを実行している場合
        :except NotADirectoryError: サーバーディレクトリが存在しないか、ディレクトリでない場合
        """
        if server in self._tasks:
            raise AlreadyBackupError("Already running backup")

        if not server.directory.is_dir():
            raise NotADirectoryError("Server directory is not exists or directory")

        return self._start_backup_server(server, server.directory, comments=comments)

    def _start_backup_server(self, server: "ServerProcess", server_dir: Path, *, comments: str | None) -> BackupTask:
        """
        バックアップタスクを作成し、開始します。
        :except NoArchiveHelperError: 対応するアーカイブヘルパーが見つからない
        """
        archive_file_name = create_backup_filename(comments)
        suffix, helper = self._files.find_archive_helper_with_suffixes(["7z", "zip"])

        archive_file_name += f".{suffix}"
        archive_path = self.backups_dir / server.get_source_id() / archive_file_name
        if not archive_path.parent.is_dir():
            archive_path.parent.mkdir(parents=True)

        async def _do():
            try:
                async for progress in helper.make_archive(archive_path, server_dir.parent, [server_dir]):
                    task.progress = progress.progress
            except Exception as e:
                server.log.exception("Failed to server backup", exc_info=e)
            else:
                server.log.info("Completed backup: %s", archive_path)

        server.log.info("Starting backup: %s", archive_path)
        fut = asyncio.get_running_loop().create_task(_do())
        task = self._tasks[server] = BackupTask(
            task_id=self._files._add_task_id(),
            src=server_dir,
            fut=fut,
            server=server,
            comments=comments,
        )

        def _done(*_):
            if self._tasks.get(server) is task:
                self._tasks.pop(server, None)

        if not fut.done():
            fut.add_done_callback(_done)
        self._files.add_task(task)
        return task
