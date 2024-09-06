from pathlib import Path
from typing import Iterable, AsyncGenerator

from .abc import ArchiveProgress, ArchiveFile


class ArchiveHelper:
    # noinspection PyMethodMayBeStatic
    def _safe_path(self, root_dir: Path, path: Path) -> str:
        try:
            return path.resolve().relative_to(root_dir.resolve()).as_posix()
        except ValueError:
            return path.name

    def available_formats(self) -> set[str]:
        raise NotImplementedError

    async def make_archive(self, archive_path: Path, root_dir: Path, files: Iterable[Path],
                           ) -> AsyncGenerator[ArchiveProgress]:
        """
        files を root_dir で相対パスに変換し、圧縮ファイルを作成します

        圧縮フォーマットは archive_name に含まれる拡張子で決定します
        """
        raise NotImplementedError

    async def extract_archive(self, archive_path: Path, extract_dir: Path, password: str = None,
                              ) -> AsyncGenerator[ArchiveProgress]:
        """
        archive_path を開き、extract_dir に全ファイルを展開します
        """
        raise NotImplementedError

    async def list_archive(self, archive_path: Path, password: str = None, ) -> list[ArchiveFile]:
        raise NotImplementedError

    async def is_archive(self, file_path: Path) -> bool:
        raise NotImplementedError
