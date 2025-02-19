import asyncio.subprocess as subprocess
import collections
import datetime
import re
import shutil
from pathlib import Path
from typing import AsyncGenerator, AsyncIterable

from ..archive import ArchiveHelper, ArchiveProgress, ArchiveFile


class SevenZipHelper(ArchiveHelper):
    SCAN_INFO_REGEX = re.compile(br"^((?P<folders>\d+) folders?, )?(?P<files>\d+) files?, (?P<bytes>\d+) bytes?")
    PROGRESS_VALUE_REGEX = re.compile(br"^(\d+)%")
    LIST_FILE_REGEX = re.compile(
        br"^(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
        br"(?P<attr>[.\w]{5}) "
        br"+(?P<size>\d+) "
        br"+(?P<csize>\d+)? "
        br"+(?P<name>.*)$"
    )

    def __init__(self, command_name="7z", ):
        self.command_name = command_name

    def available(self):
        return bool(shutil.which(self.command_name))

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
            stdout=subprocess.PIPE,
        )

        detect_encrypted_archive = False
        while line := await proc.stdout.readline():
            if line.strip() == b"Can not open encrypted archive. Wrong password?":
                detect_encrypted_archive = True

        return detect_encrypted_archive or await proc.wait() == 0

    async def make_archive(self, archive_path: Path, root_dir: Path, files: list[Path],
                           ) -> AsyncGenerator[ArchiveProgress, None]:

        proc = await subprocess.create_subprocess_exec(
            self.command_name,
            "a", str(archive_path.absolute()),
            "-bb0", "-bso2", "-bse2", "-bsp2", "-sccUTF-8", "-y",
            "--", *[str(self._safe_path(root_dir, p)) for p in files],
            stderr=subprocess.PIPE, cwd=root_dir,
        )

        last_logs = collections.deque(maxlen=10)
        try:
            eol_rex = re.compile(br"\r\n?")  # EOLもしくは行更新があれば一行とする
            files = total_bytes = None
            parsing = False
            buffer = b""
            while (chunk := await proc.stderr.read(1024)) or buffer:
                buffer += chunk

                m_eol = True
                while m_eol:
                    m_eol = eol_rex.search(buffer)
                    if m_eol:  # found eol
                        line, buffer = buffer[:m_eol.start()], buffer[m_eol.end():]
                    elif not chunk:  # ended read
                        line, buffer = buffer, b""
                    else:  # wait buffer
                        break

                    line = line.strip()

                    if not line:
                        continue

                    last_logs.append(line)

                    if line.startswith(b"Scanning the drive"):
                        parsing = True

                    elif parsing:
                        m = self.SCAN_INFO_REGEX.match(line)
                        if m:
                            parsing = False
                            # 返る値が再帰されたファイル数ではなかったので無視する
                            # _val = m.group("files")
                            # if _val:
                            #     files = int(_val)
                            _val = m.group("bytes")
                            if _val:
                                total_bytes = int(_val)

                    else:
                        m = self.PROGRESS_VALUE_REGEX.match(line)
                        if m:
                            progress = int(m.group(1)) / 100
                            yield ArchiveProgress(progress, files, total_bytes)

        finally:
            await proc.wait()

        # noinspection PyUnreachableCode
        if proc.returncode != 0:
            raise RuntimeError(f"Error exit: {proc.returncode}\n\n"
                               f"=== LAST OUTPUT ===\n"
                               + b"\n".join(last_logs).decode("utf-8") +
                               "\n=== LAST OUTPUT ===")

    async def extract_archive(self, archive_path: Path, extract_dir: Path, password: str = None,
                              ) -> AsyncGenerator[ArchiveProgress, None]:

        proc = await subprocess.create_subprocess_exec(
            self.command_name,
            "x",
            "-bb0", "-bso2", "-bse2", "-bsp2", "-y", "-sccUTF-8", f"-p{password or ''}",
            f"-o{extract_dir}",
            "--", str(archive_path),
            stderr=subprocess.PIPE,
        )

        last_logs = collections.deque(maxlen=10)
        try:
            eol_rex = re.compile(br"\r\n?")  # EOLもしくは行更新があれば一行とする
            files = total_bytes = None
            parsing = False
            buffer = b""
            while (chunk := await proc.stderr.read(1024)) or buffer:
                buffer += chunk

                m_eol = True
                while m_eol:
                    m_eol = eol_rex.search(buffer)
                    if m_eol:  # found eol
                        line, buffer = buffer[:m_eol.start()], buffer[m_eol.end():]
                    elif not chunk:  # ended read
                        line, buffer = buffer, b""
                    else:  # wait buffer
                        break

                    line = line.strip()

                    if not line:
                        continue

                    last_logs.append(line)

                    if line.startswith(b"Scanning the drive"):
                        parsing = True

                    elif parsing:
                        m = self.SCAN_INFO_REGEX.match(line)
                        if m:
                            parsing = False
                            # 返る値が再帰されたファイル数ではなかったので無視する
                            # _val = m.group("files")
                            # if _val:
                            #     files = int(_val)
                            _val = m.group("bytes")
                            if _val:
                                total_bytes = int(_val)

                    else:
                        m = self.PROGRESS_VALUE_REGEX.match(line)
                        if m:
                            progress = int(m.group(1)) / 100
                            yield ArchiveProgress(progress, files, total_bytes)

        finally:
            await proc.wait()

            # noinspection PyUnreachableCode
            if proc.returncode != 0:
                raise RuntimeError(f"Error exit: {proc.returncode}\n\n"
                                   f"=== LAST OUTPUT ===\n"
                                   + b"\n".join(last_logs).decode("utf-8") +
                                   "\n=== LAST OUTPUT ===")

    async def extract_archived_file(self, archive_path: Path, filename: str, password: str = None,
                                    *, chunk_size=1024 * 8) -> AsyncIterable[bytes]:
        for _file in await self.list_archive(archive_path, password):
            if _file.filename == filename:
                break
        else:
            raise FileNotFoundError(filename)

        proc = await subprocess.create_subprocess_exec(
            self.command_name,
            "e",
            "-so", "-y", "-sccUTF-8", f"-p{password or ''}",
            "--", str(archive_path), filename,
            stdout=subprocess.PIPE,
        )

        while chunk := await proc.stdout.read(chunk_size):
            yield chunk

        await proc.wait()

    async def list_archive(self, archive_path: Path, password: str = None, ) -> list[ArchiveFile]:

        proc = await subprocess.create_subprocess_exec(
            self.command_name,
            "l",
            "-bso1", "-bse2", "-sccUTF-8", f"-p{password or ''}",
            "--", str(archive_path),
            stdout=subprocess.PIPE,
        )

        files = []  # type: list[ArchiveFile]
        try:
            while line := await proc.stdout.readline():
                line = line.strip()
                m = self.LIST_FILE_REGEX.match(line)
                if m:
                    size = int(m.group("size").decode())
                    compressed_size = int(m.group("csize").decode()) if m.group("csize") else 0
                    filename = m.group("name").decode("utf-8").replace("\\", "/")
                    is_dir = m.group("attr").startswith(b"D")
                    modified = datetime.datetime.strptime(
                        m.group("dt").decode("utf-8"),
                        "%Y-%m-%d %H:%M:%S",
                    ).astimezone(datetime.timezone.utc)

                    files.append(ArchiveFile(filename, is_dir, size, compressed_size, modified))
                # else:
                #     print("RAW:", line)

        finally:
            await proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"Error exit: {proc.returncode}")

        return files
