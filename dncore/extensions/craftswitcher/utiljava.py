import asyncio
import asyncio.subprocess as subprocess
import re
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

from .abc import JavaExecutableInfo
from .utils import subprocess_encoding

if TYPE_CHECKING:
    pass

__all__ = [
    "parse_java_major_version",
    "check_java_executable",
    "get_java_home",
    "JavaPreset",
]
log = getLogger(__name__)


def parse_java_major_version(s: str):
    """
    "1.8" や "22.0.1" などのテキストからメジャーバージョンを出力します

    解析できない場合は -1 を返します
    """
    if s is None:
        return -1
    try:
        return int(s)
    except ValueError:
        pass
    m = re.search(r"^(\d+\.\d+)", s)
    if m:
        v = float(m.group(1))
        # eg. 17, 22 OR 1.8 -> 8
        return int(v) if 1 < int(v) else int(v * 10) % 10
    return -1


async def check_java_executable(path: Path) -> "JavaExecutableInfo | None":
    encoding = subprocess_encoding()
    path = path.resolve()
    p = await asyncio.create_subprocess_exec(
        path, "-XshowSettings:properties", "-version",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )

    java_home = str(path.parent.parent)

    if await p.wait() == 0:
        data_values = [
            ["java.specification.version =", None],
            ["java.home =", None],
            ["java.class.version =", None],
            ["java.runtime.version =", None],
            ["java.vendor =", None],
            ["java.vendor.version =", None],
        ]

        try:
            while line := await p.stdout.readline():
                line = line.strip().decode(encoding)
                for index, (prefix, value) in enumerate(data_values):
                    if value is None and line.startswith(prefix):
                        value = line[len(prefix)+1:].strip()
                        data_values[index][1] = value
                        continue

            specification_version = data_values[0][1]
            java_home_path = data_values[1][1] or java_home
            runtime_version = data_values[3][1] or None

            java_major_version = parse_java_major_version(specification_version or runtime_version)

        except Exception as e:
            log.warning("Failed to check java executable: %s", str(path), exc_info=e)
            # try simple check

        else:
            return JavaExecutableInfo(
                path=(Path(java_home_path) / "bin" / path.name).resolve(),
                specification_version=specification_version,
                java_home_path=java_home_path,
                java_major_version=java_major_version,
                class_version=float(data_values[2][1] or 0) or None,
                runtime_version=runtime_version,
                vendor=data_values[4][1] or None,
                vendor_version=data_values[5][1] or None,
            )

    p = await asyncio.create_subprocess_exec(
        path, "-version",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    match = None
    try:
        while line := await p.stdout.readline():
            line = line.strip().decode(encoding)
            m = re.search("version \"(.+)\"", line)
            if m:
                match = m

        if match:  # last
            runtime_version = match.group(1)
            return JavaExecutableInfo(
                path=path,
                runtime_version=runtime_version,
                java_home_path=java_home,
                java_major_version=parse_java_major_version(runtime_version),
            )
    except Exception as e:
        log.warning("Failed to check java executable (simple test): %s", str(path), exc_info=e)

    return None


async def get_java_home(exe_path: Path) -> str | None:
    info = await check_java_executable(exe_path)
    return info and info.java_home_path or None


class JavaPreset(object):
    def __init__(self, name: str, info: "JavaExecutableInfo | None", config: "JavaPresetConfig | None"):
        self.name = name
        self.info = info
        self.config = config

    @property
    def path(self) -> Path:
        if not self.info:
            raise ValueError("No executable info")
        return self.info.path

    @property
    def runtime_version(self) -> str:
        if not self.info:
            raise ValueError("No executable info")
        return self.info.runtime_version

    @property
    def major_version(self) -> int:
        if not self.info:
            raise ValueError("No executable info")
        return self.info.java_major_version
