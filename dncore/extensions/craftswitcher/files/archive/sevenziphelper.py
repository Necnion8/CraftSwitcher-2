import asyncio.subprocess as subprocess
import re
import shutil
from pathlib import Path
from typing import AsyncGenerator

from ..archive import ArchiveHelper, ArchiveProgress, ArchiveFile


class SevenZipHelper(ArchiveHelper):
    SCAN_INFO_REGEX = re.compile(br"^(\d+) folders?, (\d+) files?, (\d+) byte")
    PROGRESS_VALUE_REGEX = re.compile(br"^(\d+)%")
    LIST_FILE_REGEX = re.compile(br"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \..{4} +(\d+) +(\d+)? +(.*)$")

    def __init__(self, command_name="7z", ):
        self.command_name = command_name

    def available_formats(self) -> set[str]:
        if not shutil.which(self.command_name):
            return set()

        return {"7z", "zip", }

    async def is_archive(self, file_path: Path) -> bool:
        proc = await subprocess.create_subprocess_exec(
            self.command_name,
            "t",
            "-bso1", "-bse1",
            "-y", "-x!*", "-p"
            "--", str(file_path),
        )

        detect_encrypted_archive = False
        while line := await proc.stdout.read():
            if line.strip() == b"Can not open encrypted archive. Wrong password?":
                detect_encrypted_archive = True

        return detect_encrypted_archive or await proc.wait() == 0

    async def make_archive(self, archive_path: Path, root_dir: Path, files: list[Path],
                           ) -> AsyncGenerator[ArchiveProgress, None]:

        proc = await subprocess.create_subprocess_exec(
            self.command_name,
            "a", str(archive_path),
            "-bb1", "-bso2", "-bse2", "-so",
            *[str(self._safe_path(root_dir, p)) for p in files],
            stderr=subprocess.PIPE,
        )

        files = total_bytes = 0
        try:
            parsing = False
            while line := await proc.stderr.readline():
                line = line.strip()
                if line.startswith(b"Scanning the drive:"):
                    parsing = True

                elif parsing:
                    m = self.SCAN_INFO_REGEX.match(line)
                    if m:
                        parsing = False
                        _, files, total_bytes = map(int, m.groups())

                else:
                    m = self.PROGRESS_VALUE_REGEX.match(line)
                    if m:
                        progress = int(m.group(1))
                        yield ArchiveProgress(progress, files, total_bytes)

        finally:
            await proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"Error exit: {proc.returncode}")

    async def extract_archive(self, archive_path: Path, extract_dir: Path, password: str = None,
                              ) -> AsyncGenerator[ArchiveProgress, None]:

        proc = await subprocess.create_subprocess_exec(
            self.command_name,
            "x", str(archive_path),
            "-bb1", "-bso2", "-bse2", "-si", f"-p{password or ''}",
            stderr=subprocess.PIPE,
        )

        files = total_bytes = 0
        try:
            parsing = False
            while line := await proc.stderr.readline():
                line = line.strip()
                if line.startswith(b"Scanning the drive:"):
                    parsing = True

                elif parsing:
                    m = self.SCAN_INFO_REGEX.match(line)
                    if m:
                        parsing = False
                        _, files, total_bytes = map(int, m.groups())

                else:
                    m = self.PROGRESS_VALUE_REGEX.match(line)
                    if m:
                        progress = int(m.group(1))
                        yield ArchiveProgress(progress, files, total_bytes)

        finally:
            await proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"Error exit: {proc.returncode}")

    async def list_archive(self, archive_path: Path, password: str = None, ) -> list[ArchiveFile]:

        proc = await subprocess.create_subprocess_exec(
            self.command_name,
            "l",
            "-bso1", "-bse2", f"-p{password or ''}",
            "--", str(archive_path),
            stdout=subprocess.PIPE,
        )

        files = []  # type: list[ArchiveFile]
        try:
            while line := await proc.stdout.readline():
                line = line.strip()
                m = self.LIST_FILE_REGEX.match(line)
                if m:
                    size = int(m.group(1).decode())
                    compressed_size = int(m.group(2).decode()) if m.group(2) else 0
                    filename = m.group(3).decode("utf-8")

                    files.append(ArchiveFile(filename, size, compressed_size))
                # else:
                #     print("RAW:", line)

        finally:
            await proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"Error exit: {proc.returncode}")

        return files
