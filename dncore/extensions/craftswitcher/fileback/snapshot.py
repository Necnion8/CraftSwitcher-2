import asyncio
import datetime
import shutil
from logging import getLogger
from pathlib import Path

from .abc import SnapshotStatus, FileInfo, FileDifference

__all__ = [
    "SnapshotResult",
    "compare_files_diff",
    "get_file_info",
    "scan_files",
    "async_scan_files",
    "create_files_diff",
    "async_create_files_diff",
]
log = getLogger(__name__)


class SnapshotResult(object):
    def __init__(self, src_dir: Path, old_dir: Path | None, files: list[FileDifference]):
        """
        :param src_dir: 現在のファイルが格納されているディレクトリ
        :param old_dir: 古いファイル(前回のバックアップ)が格納されているディレクトリ
        :param files: old_dirまたはnew_dirに含まれるファイルの一覧
        """
        self.src_dir = src_dir
        self.old_dir = old_dir
        self.files = files


def compare_files_diff(old_files: dict[str, FileInfo], new_files: dict[str, FileInfo]):
    files = []  # type: list[FileDifference]
    old_files = dict(old_files)

    for path, f_info in new_files.items():
        try:
            old_f_info = old_files.pop(path)
        except KeyError:
            # new
            old_f_info = None
            status = SnapshotStatus.CREATE
        else:
            # update or no updated
            status = SnapshotStatus.LINK if f_info == old_f_info else SnapshotStatus.UPDATE

        files.append(FileDifference(path, old_f_info, f_info, status))

    # deletes in new
    files.extend(FileDifference(p, i, None, SnapshotStatus.DELETE) for p, i in old_files.items())
    return files


def get_file_info(path: Path):
    stat = path.stat()
    return FileInfo(
        stat.st_size,
        datetime.datetime.fromtimestamp(stat.st_mtime).astimezone(datetime.timezone.utc),
    )


def scan_files(src_dir: Path) -> dict[str, FileInfo]:
    return {p.relative_to(src_dir).as_posix(): get_file_info(p)
            for p in src_dir.glob("**/*") if p.is_file()}


async def async_scan_files(src_dir: Path) -> dict[str, FileInfo]:
    return await asyncio.get_running_loop().run_in_executor(None, scan_files, src_dir)


def create_files_diff(result: SnapshotResult, dst_dir: Path):
    """
    スキャン結果をもとにファイルを処理します
    :param result: スナップショットスキャンの結果
    :param dst_dir: 新しいスナップショットの作成先ディレクトリ
    """
    if not dst_dir.is_dir():
        raise NotADirectoryError("destination directory is not exists or directory")

    errors = []  # type: list[tuple[FileDifference, Exception]]
    for file in result.files:
        if SnapshotStatus.LINK == file.status:
            try:
                old_file_path = result.old_dir / file.path
                dst_file_path = dst_dir / file.path
                try:
                    dst_file_path.parent.mkdir(parents=True, exist_ok=True)
                    dst_file_path.hardlink_to(old_file_path)
                except Exception as e:
                    log.warning("Failed to link file: %s:%s: %s TO %s",
                                type(e).__name__, str(e), old_file_path, dst_file_path)
                    errors.append((file, e))
            except Exception as e:
                log.warning("Failed to link file: %s:%s: %s",
                            type(e).__name__, str(e), file.path)
                errors.append((file, e))

        elif file.status in (SnapshotStatus.CREATE, SnapshotStatus.UPDATE, ):
            try:
                src_file_path = result.src_dir / file.path
                dst_file_path = dst_dir / file.path
                try:
                    dst_file_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file_path, dst_file_path)
                except Exception as e:
                    log.warning("Failed to copy file: %s:%s: %s TO %s",
                                type(e).__name__, str(e), src_file_path, dst_file_path)
                    errors.append((file, e))
            except Exception as e:
                log.warning("Failed to copy file: %s:%s: %s",
                            type(e).__name__, str(e), file.path)
                errors.append((file, e))

        elif SnapshotStatus.DELETE == file.status:
            pass

        else:
            errors.append((file, NotImplementedError(f"Unknown snapshot status: {file.status.name}")))
            log.warning("Unknown snapshot status: %s: %s", file.status, file.path)

    return errors


async def async_create_files_diff(result: SnapshotResult, dst_dir: Path):
    """
    スキャン結果をもとにファイルを処理します
    :param result: スナップショットスキャンの結果
    :param dst_dir: 新しいスナップショットの作成先ディレクトリ
    """
    return await asyncio.get_running_loop().run_in_executor(None, create_files_diff, result, dst_dir)
