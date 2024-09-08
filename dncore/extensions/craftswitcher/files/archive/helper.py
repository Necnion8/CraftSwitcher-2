import asyncio
import concurrent.futures
import os.path
import zipfile
from pathlib import Path
from typing import AsyncGenerator, Any

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

    async def make_archive(self, archive_path: Path, root_dir: Path, files: list[Path],
                           ) -> AsyncGenerator[ArchiveProgress, None]:
        """
        files を root_dir で相対パスに変換し、圧縮ファイルを作成します

        圧縮フォーマットは archive_name に含まれる拡張子で決定します
        """
        raise NotImplementedError

    async def extract_archive(self, archive_path: Path, extract_dir: Path, password: str = None,
                              ) -> AsyncGenerator[ArchiveProgress, None]:
        """
        archive_path を開き、extract_dir に全ファイルを展開します
        """
        raise NotImplementedError

    async def list_archive(self, archive_path: Path, password: str = None, ) -> list[ArchiveFile]:
        raise NotImplementedError

    async def is_archive(self, file_path: Path) -> bool:
        raise NotImplementedError


# zipfile


class ZipArchiveHelper(ArchiveHelper):
    def __init__(self):
        self.executor = concurrent.futures.ThreadPoolExecutor()

    def __del__(self):
        self.executor.shutdown()

    def available_formats(self) -> set[str]:
        return {"zip", }

    async def is_archive(self, file_path: Path) -> bool:
        return await asyncio.get_running_loop().run_in_executor(self.executor, zipfile.is_zipfile, file_path)

    async def make_archive(self, archive_path: Path, root_dir: Path, files: list[Path],
                           ) -> AsyncGenerator[ArchiveProgress, None]:

        def _search():
            _total_size = 0
            new_files = []
            for _file in files:
                for _child in _file.glob("**/*"):
                    new_files.append(_child)
                    _total_size += os.path.getsize(_child)
            return new_files, _total_size

        loop = asyncio.get_running_loop()
        files, total_size = await loop.run_in_executor(self.executor, _search)
        file_count = len(files)
        completed = asyncio.Queue()

        def _in_thread():
            with zipfile.ZipFile(archive_path, "w") as fz:
                for child in files:
                    fz.write(child, self._safe_path(root_dir, child))
                    completed.put_nowait(child)

        fut = loop.run_in_executor(self.executor, _in_thread)

        completed_count = 0
        while not fut.done() or not completed.empty():
            try:
                await asyncio.wait_for(completed.get(), .2)
            except asyncio.TimeoutError:
                continue

            completed_count += 1
            yield ArchiveProgress(completed_count / file_count, file_count, total_size)

        await fut

    async def extract_archive(self, archive_path: Path, extract_dir: Path, password: str = None,
                              ) -> AsyncGenerator[ArchiveProgress, None]:
        _args = [None]  # type: list[Any]
        completed = asyncio.Queue()

        def _in_thread():
            with zipfile.ZipFile(archive_path, "r") as fz:
                if password is not None:
                    fz.setpassword(password.encode("utf-8"))

                files = fz.namelist()
                _args[0] = len(files)

                for count, child in enumerate(files):
                    fz.extract(child, extract_dir)  # FIXME: unsafe path eg. '..' and absolute path
                    completed.put_nowait(child)

        fut = asyncio.get_running_loop().run_in_executor(self.executor, _in_thread)

        completed_count = 0
        while not fut.done() or not completed.empty():
            try:
                await asyncio.wait_for(completed.get(), timeout=.2)
            except asyncio.TimeoutError:
                continue

            completed_count += 1

            if _args:
                total_count = _args[0]
                yield ArchiveProgress(completed_count / total_count, total_count)
            else:
                yield ArchiveProgress(0)

        await fut

    async def list_archive(self, archive_path: Path, password: str = None, ) -> list[ArchiveFile]:
        def _in_thread():
            with zipfile.ZipFile(archive_path, "r") as zf:
                return [ArchiveFile(fi.filename, fi.file_size, fi.compress_size) for fi in zf.infolist()]
        return await asyncio.get_running_loop().run_in_executor(self.executor, _in_thread)
