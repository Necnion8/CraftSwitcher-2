import asyncio
import datetime
import re
import time
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from .abc import *
from .snapshot import *
from ..errors import AlreadyBackupError
from ..files import FileManager, BackupTask, BackupType
from ..utils import datetime_now

if TYPE_CHECKING:
    from ..config import Backup as BackupConfig
    from ..database import SwitcherDatabase
    from ..serverprocess import ServerProcess

__all__ = [
    "create_backup_filename",
    "create_snapshot_backup_filename",
    "Backupper",
]
log = getLogger(__name__)


def create_backup_filename(dt: datetime.datetime, comments: str = None):
    archive_file_name = dt.strftime("%Y%m%d_%H%M%S")

    if comments:
        comments = re.sub(r"[\\/:*?\"<>|]+", "_", comments)
        if comments:
            archive_file_name += f"_{comments}"

    return archive_file_name


def create_snapshot_backup_filename(dt: datetime.datetime):
    return create_backup_filename(dt, None)


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
        指定サーバーのフルバックアップを作成します

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

        created_dt = datetime_now()
        archive_file_name = create_backup_filename(created_dt, comments)
        suffix, helper = self._files.find_archive_helper_with_suffixes(["zip"])

        archive_file_name += f".{suffix}"
        archive_path_name = Path(server.get_source_id()) / archive_file_name
        archive_path = self.backups_dir / archive_path_name
        if not archive_path.parent.is_dir():
            server.log.debug("creating backup directory: %s", archive_path.parent)
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
                backup_id = await self._db.add_full_backup(Backup(
                    id=None,
                    type=BackupType.FULL,
                    source=UUID(server.get_source_id()),
                    created=created_dt,
                    path=archive_path_name.as_posix(),
                    comments=comments or None,
                    total_files=-1,  # TODO: put from archiver
                    total_files_size=-1,
                    error_files=-1,
                    final_size=archive_path.stat().st_size,
                ))

            except Exception as e:
                server.log.error("Failed to add backup to database", exc_info=e)
                if archive_path.is_file():
                    try:
                        await self._files.delete(archive_path)
                    except Exception as e:
                        server.log.warning(f"Failed to delete failed backup file: {e}")
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
            backup_type=BackupType.FULL,
        )

        self._files.add_task(task)
        return task

    async def delete_backup(self, server: "ServerProcess | None", backup_id: int):
        """
        指定されたバックアップをファイルとデータベースから削除します

        :except ValueError: 存在しないバックアップID
        """
        backup = await self._db.get_backup_or_snapshot(backup_id)
        if not backup:
            raise ValueError("Not found backup")

        _log = server and server.log or log
        _log.info("Deleting backup: %s", backup_id)
        await self._db.remove_backup_or_snapshot(backup)

        backup_path = Path(self.backups_dir / backup.path)
        if backup_path.exists():
            try:
                await self._files.delete(backup_path, server)
            except Exception as e:
                _log.warning(f"Failed to delete backup file: {e}: {backup_path}")
        else:
            _log.warning("Backup file not exists: %s", backup_path)

        _log.info("Completed delete backup: %s (id: %s)", backup_path, backup.id)

    async def get_snapshot_file_info(self, backup_id: int) -> dict[str, FileInfo] | None:
        """
        データベースからスナップショットのファイル一覧を取得します
        :return: ファイルパスとFileInfoのマップ
        """
        files = await self._db.get_snapshot_files(backup_id)
        if files is None:
            return

        return {
            file.path: FileInfo(
                size=file.size,
                modified_datetime=file.modified.replace(tzinfo=datetime.timezone.utc),
                is_dir=file.type.value == 1,
            ) for file in files if SnapshotStatus.DELETE != file.status
        }

    async def create_snapshot(self, server: "ServerProcess", comments: str = None) -> BackupTask:
        """
        指定サーバーのスナップショットバックアップを作成します

        データベースから前回のリストを参照し、存在する場合は増分処理(ハードリンク)します。

        :except NoArchiveHelperError: 対応するアーカイブヘルパーが見つからない
        :except AlreadyBackupError: すでにバックアップを実行している場合
        :except NotADirectoryError: サーバーディレクトリが存在しないか、ディレクトリでない場合
        """
        if server in self._tasks:
            raise AlreadyBackupError("Already running backup")

        server_dir = server.directory
        if not server_dir.is_dir():
            raise NotADirectoryError("Server directory is not exists or directory")

        from ..database.model import Backup, SnapshotFile, SnapshotErrorFile

        created_dt = datetime_now()
        source_id = server.get_source_id()
        dst_path_name = Path(source_id) / "snapshots" / create_snapshot_backup_filename(created_dt)
        dst_path = self.backups_dir / dst_path_name
        if not dst_path.is_dir():
            server.log.debug("creating backup directory: %s", dst_path)
            dst_path.mkdir(parents=True)

        async def _do():
            starts = time.perf_counter()
            try:
                action = "get snapshot latest"
                try:
                    tim = time.perf_counter()
                    old_files = old_dir = None
                    for _backup in reversed((await self._db.get_backups_or_snapshots(UUID(source_id))) or []):
                        if BackupType.SNAPSHOT == _backup.type:
                            last_snapshot = _backup
                            old_files = await self.get_snapshot_file_info(last_snapshot.id)
                            old_dir = self.backups_dir / last_snapshot.path  # type: Path | None
                            break

                    server.log.debug("%s times %sms", action, round((time.perf_counter() - tim) * 1000))
                    tim = time.perf_counter()

                    action = "scan current files"
                    files, _scan_errors = await async_scan_files(server_dir)
                    server.log.debug("%s times %sms", action, round((time.perf_counter() - tim) * 1000))
                    tim = time.perf_counter()

                    action = "process diff"
                    files_diff = compare_files_diff(old_files or {}, files)
                    snap_files = {
                        entry.path: SnapshotFile(
                            path=entry.path,
                            status=entry.status,
                            modified=i.modified_datetime if (i := entry.new_info) else None,
                            size=i.size if (i := entry.new_info) else None,
                            type=[
                                FileType.FILE, FileType.DIRECTORY
                            ][(i := (entry.new_info or entry.old_info)) and i.is_dir],
                        ) for entry in files_diff
                    }
                    server.log.debug("%s times %sms", action, round((time.perf_counter() - tim) * 1000))
                    tim = time.perf_counter()

                    action = "creating snapshot files"
                    errors = await async_create_files_diff(
                        SnapshotResult(server_dir, old_dir, files_diff), dst_path,
                    )

                    server.log.debug("%s times %sms", action, round((time.perf_counter() - tim) * 1000))

                except Exception as e:
                    server.log.exception(f"Failed to server snapshot backup: in {action}", exc_info=e)
                    if dst_path.is_dir():
                        try:
                            await self._files.delete(dst_path)
                        except Exception as e:
                            server.log.warning(f"Failed to delete failed backup file: {e}")
                    raise

                try:
                    snap_error_files = [SnapshotErrorFile(
                        path=_p,
                        error_type=SnapshotFileErrorType.SCAN,
                        error_message=f"{type(_e).__name__}: {_e}",
                        type=None,
                    ) for _p, _e in _scan_errors.items()]  # type: list[SnapshotErrorFile]

                    for _file, _error, _err_type in errors:
                        snap_files.pop(_file.path)
                        snap_error_files.append(SnapshotErrorFile(
                            path=_file.path,
                            error_type=_err_type,
                            error_message=f"{type(_error).__name__}: {_error}",
                            type=FileType.DIRECTORY if _file.new_info and _file.new_info.is_dir else FileType.FILE,
                        ))

                    total_files_count = len(files) + len(_scan_errors)
                    error_files_count = len(_scan_errors) + len(errors)
                    total_files_size = sum(i.size for i in files.values())
                    _copied_files = [
                        f.new_info.size for f in files_diff
                        if f.new_info and f.status in (SnapshotStatus.CREATE, SnapshotStatus.UPDATE)
                    ]
                    copied_files_count = len(_copied_files)
                    copied_files_size = sum(_copied_files)

                    snapshot_id = await self._db.add_snapshot_backup(Backup(
                        id=None,
                        type=BackupType.SNAPSHOT,
                        source=UUID(source_id),
                        created=created_dt,
                        path=dst_path_name.as_posix(),
                        comments=comments,
                        total_files=total_files_count,
                        total_files_size=total_files_size,
                        error_files=error_files_count,
                        final_size=None,
                    ), list(snap_files.values()), snap_error_files)

                except Exception as e:
                    server.log.error("Failed to add snapshot backup to database", exc_info=e)
                    if dst_path.is_dir():
                        try:
                            await self._files.delete(dst_path)
                        except Exception as e:
                            server.log.warning(f"Failed to delete failed backup file: {e}")
                    raise
            finally:
                if self._tasks.get(server) is task:
                    _ = self._tasks.pop(server, None)

            server.log.info("Completed snapshot backup: %s (id: %s)", dst_path_name, snapshot_id)
            server.log.info(f"  Total {total_files_count:,} files ({total_files_size / 1024 / 1024:,.0f} MB)")
            server.log.info(f"  Copied {copied_files_count:,} files ({copied_files_size / 1024 / 1024:,.0f} MB)")
            if error_files_count:
                server.log.warning(f"  Error {error_files_count:,} files")
            server.log.info(f"  Total time: {time.perf_counter() - starts:.1f}s")
            return snapshot_id

        server.log.info("Starting snapshot backup: %s", dst_path_name)
        fut = asyncio.get_running_loop().create_task(_do())
        task = self._tasks[server] = BackupTask(
            task_id=self._files._add_task_id(),
            src=server_dir,
            fut=fut,
            server=server,
            comments=comments,
            backup_type=BackupType.SNAPSHOT,
        )

        self._files.add_task(task)
        return task
