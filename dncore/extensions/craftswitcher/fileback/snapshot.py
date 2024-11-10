import datetime
from pathlib import Path

from .abc import SnapshotStatus, FileInfo, FileDifference

__all__ = [
    "SnapshotResult",
    "compare_files_diff",
    "get_file_info",
    "scan_files",
]


class SnapshotResult(object):
    def __init__(self, old_dir: Path, new_dir: Path, files: list[FileDifference]):
        """
        old_dir: 古いファイル(前回のバックアップ)が格納されているディレクトリ

        new_dir: 新しいファイル(現在)が格納されているディレクトリ

        files: old_dirまたはnew_dirに含まれるファイルの一覧
        """
        self.old_dir = old_dir
        self.new_dir = new_dir
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

        files.append(FileDifference(Path(path), old_f_info, f_info, status))

    # deletes in new
    files.extend(FileDifference(Path(p), i, None, SnapshotStatus.DELETE) for p, i in old_files.items())
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
