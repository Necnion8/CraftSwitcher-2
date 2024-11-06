from shutil import which
from subprocess import getoutput, getstatusoutput
from typing import NamedTuple

__all__ = [
    "list_names",
    "list_screens",
    "get_screen",
    "kill_screen",
    "new_session_commands",
    "attach_commands",
    "is_available",
    "ScreenSession",
    "ScreenStatus",
]


def list_names():
    return [
        line.strip().split("\t")[0].split(".", 1)[-1]
        for line in getoutput("screen -ls").split("\n")
        if line.startswith("\t")
    ]


def list_screens():
    screens = []
    for line in getoutput("screen -ls").split("\n"):
        if not line.startswith("\t"):
            continue

        try:
            pid_name, date, status = line.strip().split("\t")
        except ValueError:
            pid_name, status = line.strip().split("\t")
            date = None

        pid, name = pid_name.split(".", 1)
        screens.append(ScreenSession(int(pid), name, date, ScreenStatus(status)))

    return screens


def get_screen(name: str):
    for line in getoutput("screen -ls").split("\n"):
        if not line.startswith("\t"):
            continue

        try:
            pid_name, date, status = line.strip().split("\t")
        except ValueError:
            pid_name, status = line.strip().split("\t")
            date = None

        pid, name_ = pid_name.split(".", 1)
        if name == name_:
            return ScreenSession(int(pid), name, date, ScreenStatus(status))
    return None


def kill_screen(id_or_name):
    getoutput(f"screen -XS '{id_or_name}' quit")


def new_session_commands(session_name: str, *,
                         detach=False, exist_ignore=False, ) -> list[str]:
    args = [
        which("screen") or "screen",
        "-e", "^Aa",  # set command characters: Ctrl+A
        "-S", session_name,  # set name
    ]

    if detach:
        args.append("-d")
    if exist_ignore:
        args.append("-m")  # ignore $STY, create new session

    return args


def attach_commands(session_name: str, *,
                    force=False, ) -> list[str]:
    args = [
        which("screen") or "screen",
        "-e", "^Aa",  # set command characters: Ctrl+A
    ]

    if force:
        args.append("-x")  # force attach (multi display mode)

    args.extend(("-r", session_name))  # reattach
    return args


def is_available():
    code = getstatusoutput("screen -v")[0]
    return code == 0


class ScreenStatus(str):
    def is_dead(self):
        return self.lower().startswith("dead")


class ScreenSession(NamedTuple):
    pid: int
    name: str
    date: str | None
    status: ScreenStatus

    @property
    def full_name(self):
        return f"{self.pid}.{self.name}"
