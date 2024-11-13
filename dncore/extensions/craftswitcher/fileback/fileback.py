import asyncio
import datetime
import re
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from .abc import *
from .snapshot import *
from ..errors import AlreadyBackupError
from ..utils import datetime_now

if TYPE_CHECKING:
    from ..config import Backup as BackupConfig
    from ..database import SwitcherDatabase
    from ..files import FileManager
    from ..serverprocess import ServerProcess

__all__ = [
    "create_backup_filename",
    "create_snapshot_backup_filename",
    "Backupper",
]
log = getLogger(__name__)


def create_backup_filename(comments: str = None):
    backup_dt = datetime_now()
    archive_file_name = backup_dt.strftime("%Y%m%d_%H%M%S")

    if comments:
        comments = re.sub(r"[\\/:*?\"<>|]+", "_", comments)
        if comments:
            archive_file_name += f"_{comments}"

    return archive_file_name


def create_snapshot_backup_filename():
    return create_backup_filename(None)


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

        server_dir = server.directory
        if not server_dir.is_dir():
            raise NotADirectoryError("Server directory is not exists or directory")

        from ..database.model import Backup

        archive_file_name = create_backup_filename(comments)
        suffix, helper = self._files.find_archive_helper_with_suffixes(["7z", "zip"])

        archive_file_name += f".{suffix}"
        archive_path_name = Path(server.get_source_id()) / archive_file_name
        archive_path = self.backups_dir / archive_path_name
        if not archive_path.parent.is_dir():
            log.debug("creating backup directory: %s", archive_path.parent)
            archive_path.parent.mkdir(parents=True)

        async def _do() -> int:
            try:
                async for progress in helper.make_archive(archive_path, server_dir.parent, [server_dir]):
                    task.progress = progress.progress
            except Exception as e:
                server.log.exception("Failed to server backup", exc_info=e)
                raise
            finally:
                if self._tasks.get(server) is task:
                    _ = self._tasks.pop(server, None)

            try:
                backup_id = await self._db.add_backup(Backup(
                    source=UUID(server.get_source_id()),
                    created=datetime_now(),
                    path=archive_path_name.as_posix(),
                    size=archive_path.stat().st_size,
                    comments=comments or None,
                ))

            except Exception as e:
                server.log.error("Failed to add backup to database", exc_info=e)
                raise

            server.log.info("Completed backup: %s (id: %s)", archive_path, backup_id)
            return backup_id

        server.log.info("Starting backup: %s", archive_path)
        fut = asyncio.get_running_loop().create_task(_do())
        task = self._tasks[server] = BackupTask(
            task_id=self._files._add_task_id(),
            src=server_dir,
            fut=fut,
            server=server,
            comments=comments,
        )

        self._files.add_task(task)
        return task

    async def delete_backup(self, server: "ServerProcess", backup_id: int):
        """
        指定されたIDのバックアップをファイルとデータベースから削除します

        :except ValueError: 存在しないバックアップID
        """
        backup = await self._db.get_backup(backup_id)
        if not backup:
            raise ValueError("Not found backup")

        server.log.debug("Deleting backup: %s", backup_id)
        backup_path = Path(self.backups_dir / backup.path)
        if backup_path.is_file():
            try:
                await self._files.delete(backup_path, server)
            except Exception as e:
                server.log.warning(f"Failed to delete backup file: {e}: {backup_path}")
        else:
            log.warning("Backup file not exists: %s", backup_path)

        await self._db.remove_backup(backup)
        server.log.info("Completed delete backup: %s (id: %s)", backup_path, backup.id)

    async def get_snapshot_file_info(self, snapshot_id: int) -> dict[str, FileInfo] | None:
        files = await self._db.get_snapshot_files(snapshot_id)
        if files is None:
            return

        return {
            file.path: FileInfo(file.size, file.modified.replace(tzinfo=datetime.timezone.utc))
            for file in files if SnapshotStatus.DELETE != file.status
        }

    async def test_create_snapshot(self, server: "ServerProcess", comments: str = None) -> BackupTask:
        """
        指定サーバーのスナップショットバックアップを作成します

        :except NoArchiveHelperError: 対応するアーカイブヘルパーが見つからない
        :except AlreadyBackupError: すでにバックアップを実行している場合
        :except NotADirectoryError: サーバーディレクトリが存在しないか、ディレクトリでない場合
        """
        if server in self._tasks:
            raise AlreadyBackupError("Already running backup")

        server_dir = server.directory
        if not server_dir.is_dir():
            raise NotADirectoryError("Server directory is not exists or directory")

        from ..database.model import Snapshot, SnapshotFile

        source_id = server.get_source_id()
        snap_dir = Path(source_id) / "snapshots"
        dst_dir_name = create_snapshot_backup_filename()
        dst_path_name = snap_dir / dst_dir_name
        dst_path = self.backups_dir / dst_path_name
        if not dst_path.is_dir():
            log.debug("creating backup directory: %s", dst_path)
            dst_path.mkdir(parents=True)

        created = datetime_now()

        # last snapshot
        snapshots = await self._db.get_snapshots(UUID(source_id))
        last_snapshot = snapshots[-1] if snapshots else None

        async def _do():
            action = "get snapshot latest"
            try:
                if last_snapshot:
                    old_files = await self.get_snapshot_file_info(last_snapshot.id)
                    old_dir = self.backups_dir / snap_dir / last_snapshot.directory  # type: Path | None
                else:
                    old_files = None
                    old_dir = None

                action = "scan current files"
                files = await async_scan_files(server_dir)

                action = "process diff"
                snap_files = [
                    SnapshotFile(
                        path=entry.path,
                        status=entry.status,
                        modified=i.update if (i := entry.new_info) else None,
                        size=i.size if (i := entry.new_info) else None,
                        hash=None,
                    ) for entry in compare_files_diff(old_files or {}, files)
                ]

                action = "creating snapshot files"
                errors = await async_create_files_diff(
                    SnapshotResult(server_dir, old_dir, snap_files), dst_path,
                )  # TODO: エラーをフロントエンドにレポートする

            except Exception as e:
                server.log.exception(f"Failed to server snapshot backup: in {action}", exc_info=e)
                raise
            finally:
                if self._tasks.get(server) is task:
                    _ = self._tasks.pop(server, None)

            try:
                snapshot_id = await self._db.add_snapshot(Snapshot(
                    id=None,
                    source=UUID(source_id),
                    created=created,
                    directory=dst_dir_name,
                    comments=comments,
                ), snap_files)  # TODO: エラーしたファイルをデータベースに登録しないように除外する

            except Exception as e:
                server.log.error("Failed to add snapshot backup to database", exc_info=e)
                raise

            server.log.info("Completed snapshot backup: %s (id: %s)", dst_path_name, snapshot_id)
            return snapshot_id

        server.log.info("Starting snapshot backup: %s", dst_path_name)
        fut = asyncio.get_running_loop().create_task(_do())
        task = self._tasks[server] = BackupTask(
            task_id=self._files._add_task_id(),
            src=server_dir,
            fut=fut,
            server=server,
            comments=comments,
        )

        self._files.add_task(task)
        return task
