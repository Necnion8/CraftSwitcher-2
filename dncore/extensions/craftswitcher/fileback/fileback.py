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
from ..errors import AlreadyBackupError, NoArchiveHelperError
from ..files import FileManager, BackupTask, BackupType, FileEventType
from ..utils import datetime_now, generate_uuid

if TYPE_CHECKING:
    from ..config import Backup as BackupConfig
    from ..database import SwitcherDatabase
    from ..database import model as db
    from ..serverprocess import ServerProcess

__all__ = [
    "create_backup_filename",
    "create_snapshot_backup_filename",
    "exists_to_rename",
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


def exists_to_rename(base_dir: Path):
    rename_dir = base_dir
    n = 0
    while rename_dir.exists():
        n += 1
        rename_dir = base_dir.with_name(base_dir.name + f".{n}")
    return rename_dir


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

    async def create_full_backup(self, server: "ServerProcess", comments: str = None) -> BackupTask:
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

        backup_id = generate_uuid()

        async def _do() -> UUID:
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
                await self._db.add_full_backup(Backup(
                    id=backup_id,
                    type=BackupType.FULL,
                    source=UUID(server.get_source_id()),
                    created=created_dt,
                    previous_backup_id=UUID(last_id) if (last_id := server.config.last_backup_id) else None,
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
            server.config.last_backup_id = backup_id
            server._config.save()
            return backup_id

        server.log.info("Starting backup: %s (id: %s)", archive_path, backup_id)
        fut = asyncio.get_running_loop().create_task(_do())
        task = self._tasks[server] = BackupTask(
            task_id=self._files._add_task_id(),
            src=server_dir,
            fut=fut,
            server=server,
            comments=comments,
            backup_type=BackupType.FULL,
            backup_id=backup_id,
        )

        self._files.add_task(task)
        return task

    async def delete_backup(self, server: "ServerProcess | None", backup_id: UUID):
        """
        指定されたバックアップをファイルとデータベースから削除します

        :except ValueError: 存在しないバックアップID
        """
        backup = await self._db.get_backup_or_snapshot(backup_id)
        if not backup:
            raise ValueError("Backup not found")

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

    async def get_snapshot_file_info(self, backup_id: UUID) -> dict[str, FileInfo] | None:
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

        backup_id = generate_uuid()

        async def _do() -> UUID:
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

                    def _counter(_):
                        _count[0] += 1
                        task.progress = _count[0] / len(old_files) / 4
                        return True
                    _count = [0]

                    action = "scan current files"
                    files, _scan_errors = await async_scan_files(server_dir, check=_counter if old_files else None)
                    server.log.debug("%s times %sms", action, round((time.perf_counter() - tim) * 1000))
                    tim = time.perf_counter()
                    task.progress = 1 / 4

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

                    _progress_total = sum(
                        SnapshotStatus.DELETE != diff.status and not diff.new_info.is_dir
                        for diff in files_diff
                        if diff.new_info
                    )
                    _progress_count = [0]

                    def _counter(diff: FileDifference):
                        if SnapshotStatus.DELETE != diff.status and diff.new_info and not diff.new_info.is_dir:
                            _progress_count[0] += 1
                            task.progress = 1 / 4 + (_progress_count[0] / _progress_total / (1 / .75))
                        return True

                    action = "creating snapshot files"
                    errors = await async_create_files_diff(
                        SnapshotResult(server_dir, old_dir, files_diff), dst_path,
                        check=_counter if _progress_total else None,
                    )
                    task.progress = 1

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

                    await self._db.add_snapshot_backup(Backup(
                        id=backup_id,
                        type=BackupType.SNAPSHOT,
                        source=UUID(source_id),
                        created=created_dt,
                        previous_backup_id=UUID(last_id) if (last_id := server.config.last_backup_id) else None,
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

                else:
                    server.config.last_backup_id = backup_id
                    server._config.save()

            finally:
                if self._tasks.get(server) is task:
                    _ = self._tasks.pop(server, None)

            server.log.info("Completed snapshot backup: %s (id: %s)", dst_path_name, backup_id)
            server.log.info(f"  Total {total_files_count:,} files ({total_files_size / 1024 / 1024:,.0f} MB)")
            server.log.info(f"  Copied {copied_files_count:,} files ({copied_files_size / 1024 / 1024:,.0f} MB)")
            if error_files_count:
                server.log.warning(f"  Error {error_files_count:,} files")
            server.log.info(f"  Total time: {time.perf_counter() - starts:.1f}s")
            return backup_id

        server.log.info("Starting snapshot backup: %s", dst_path_name)
        fut = asyncio.get_running_loop().create_task(_do())
        task = self._tasks[server] = BackupTask(
            task_id=self._files._add_task_id(),
            src=server_dir,
            fut=fut,
            server=server,
            comments=comments,
            backup_type=BackupType.SNAPSHOT,
            backup_id=backup_id,
        )

        self._files.add_task(task)
        return task

    async def restore_backup(self, server: "ServerProcess", backup_id: UUID) -> BackupTask:
        """
        指定されたバックアップでサーバーをリストアします

        リストアを実行する前にバックアップの検証を実行することを推奨します

        :except ValueError: 存在しないバックアップID
        :except NotImplementedError: 不明なバックアップタイプ
        """
        backup = await self._db.get_backup_or_snapshot(backup_id)
        if not backup:
            raise ValueError("Backup not found")

        if BackupType.FULL == backup.type:
            restore_process = self._restore_backup
        elif BackupType.SNAPSHOT == backup.type:
            restore_process = self._restore_snapshot
        else:
            raise NotImplementedError(f"Unknown backup type: {backup.type}")

        _log = server.log
        _log.info("Starting restore backup: %s", backup_id)

        server_dir = server.directory
        temp_dir = exists_to_rename(server_dir.with_name(server_dir.name + ".restore"))
        _log.debug("starting restore to temp: %s", temp_dir.name)

        async def _do() -> UUID:
            starts = time.perf_counter()
            try:
                try:
                    restored_server_dir = await restore_process(backup, temp_dir, task)
                except Exception as e:
                    _log.error("Error in restore process", exc_info=e)
                    raise

                renamed_server_dir = exists_to_rename(server_dir.with_name(server_dir.name + ".old"))

                _log.debug("moving server dir to old temp: %s", renamed_server_dir.name)
                # rename server dir to old server dir
                await self._files.move(server_dir, renamed_server_dir)

                try:
                    _log.debug("moving restored dir to server dir")
                    # rename restore dir to server dir
                    await self._files.move(restored_server_dir, server_dir)

                except Exception:
                    _log.warning("Failed to move directory (undoing...)")

                    _log.debug("Deleting failed server dir: %s", server_dir.name)
                    try:
                        await self._files.delete(server_dir)
                    except Exception as e:
                        _log.debug(f"Error in delete server dir: {e}")
                    _log.debug("Moving old temp to server dir (undo)")
                    try:
                        await self._files.move(renamed_server_dir, server_dir)
                    except Exception as e:
                        _log.warning(f"Error in old temp to server dir (undo): {e}")

                    raise

            except Exception as e:
                _log.error(f"Failed to restore backup: {backup_id}: {e}")

            else:
                if renamed_server_dir.exists():
                    _log.debug("Deleting old temp dir: %s", renamed_server_dir.name)
                    try:
                        await self._files.delete(renamed_server_dir)
                    except Exception as e:
                        _log.warning(f"Error in delete old temp dir: {e}")

                _log.info(
                    "Completed restore backup: %s (%s)",
                    backup_id, f"total time: {time.perf_counter() - starts:.1f}s",
                )
                server.config.last_backup_id = backup.id
                return backup.id

            finally:
                if temp_dir.exists():
                    _log.debug("Deleting temp dir: %s", temp_dir.name)
                    try:
                        await self._files.delete(temp_dir)
                    except Exception as e:
                        _log.warning(f"Error in delete temp dir: {e}")

                if self._tasks.get(server) is task:
                    _ = self._tasks.pop(server, None)

                # 現在の設定を上書きする
                server._config.save()

        fut = asyncio.get_running_loop().create_task(_do())
        task = self._tasks[server] = BackupTask(
            task_id=self._files._add_task_id(),
            src=server_dir,
            fut=fut,
            server=server,
            comments=backup.comments,
            backup_type=backup.type,
            backup_id=backup.id,
        )
        task.type = FileEventType.RESTORE_BACKUP
        self._files.add_task(task)
        return task

    async def _restore_backup(self, backup: "db.Backup", temp_dir: Path, task: BackupTask):
        backup_path = self.backups_dir / backup.path  # type: Path
        if not backup_path.is_file():
            raise FileNotFoundError(str(backup_path))

        if not temp_dir.exists():
            temp_dir.mkdir(parents=True, exist_ok=True)

        helper = self._files.find_archive_helper(backup_path)
        if not helper:
            raise NoArchiveHelperError("No supported archive helper")

        async for progress in helper.extract_archive(backup_path, temp_dir):
            task.progress = progress.progress

        # find server dir
        child_paths = [c for c in temp_dir.iterdir() if c.is_dir()]  # type: list[Path]

        # 1つしかディレクトリがない場合はそれを採用
        if len(child_paths) == 1:
            return child_paths[0]

        from ..craftswitcher import CraftSwitcher

        # swi.server.yml が含まれるディレクトリを採用
        for child in child_paths:
            for c in child.iterdir():
                if CraftSwitcher.SERVER_CONFIG_FILE_NAME == c.name:
                    return child

        # 適当に選ぶしかないので、将来的にはサーバーディレクトリを指定する情報を含める必要がある
        return child_paths[0]

    async def _restore_snapshot(self, backup: "db.Backup", temp_dir: Path, _: BackupTask):
        backup_dir = self.backups_dir / backup.path  # type: Path
        if not backup_dir.is_dir():
            raise NotADirectoryError(str(backup_dir))

        await self._files.copy(backup_dir, temp_dir)
        return temp_dir
