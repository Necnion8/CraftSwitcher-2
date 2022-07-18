import inspect
import re
import traceback
from logging import getLogger
from pathlib import Path
from typing import TypeVar, Any

import unicodedata

__all__ = ["typename", "traceback_simple_format", "SafeSet", "SafeList", "get_text_width", "strip_text_width", "safe_format", "Duration"]
TRACEBACK_FILE_LINE = re.compile(r"^ {2}File \"(.+)\", line \d+, in .+$")
T = TypeVar("T")


def typename(*types: type):
    return ", ".join(map(lambda t: t.__name__, types))


def traceback_simple_format():
    current = Path().absolute()

    def replace(match):
        try:
            new = str(Path(match.group(1)).absolute().relative_to(current))
        except ValueError:
            new = str(Path(match.group(1)).name)

        line = match.group(0)
        s, e = match.span(1)
        return line[:s] + new + line[e:]

    # return TRACEBACK_FILE_LINE.sub(replace, traceback.format_exc())
    return "\n".join(TRACEBACK_FILE_LINE.sub(replace, line) for line in traceback.format_exc().splitlines())


def get_text_width(text: str):
    """
    https://note.nkmk.me/python-unicodedata-east-asian-width-count/
    """
    return round(sum(1 + 1.25 * (unicodedata.east_asian_width(c) in 'FWA') for c in text))


def strip_text_width(text: str, width: int):
    total_width = 0
    total = []
    for c in text:
        total_width += 1 + 1.25 * (unicodedata.east_asian_width(c) in 'FWA')
        if total_width < width:
            total.append(c)
            continue
        return "".join(total) + " ..."
    return text


def safe_format(m: str, values: dict[str, Any]):
    if not m:
        return m

    try:
        return str(m).format_map(values)
    except (KeyError, ValueError, AttributeError) as e:
        m2 = m.replace("\n", "\\n")
        f = inspect.currentframe()
        try:
            log = getLogger(f.f_back.f_globals["__name__"])
        finally:
            del f
        log.warning(f"テキストをフォーマットできませんでした: {m2!r}")
        log.warning(f"  理由: {type(e).__name__}: {e}")
        log.warning(f"  変数: {', '.join(values)}")
        return m


class SafeSet(set[T]):
    def remove(self, element: T) -> None:
        try:
            return super().remove(element)
        except KeyError:
            pass


class SafeList(list[T]):
    def remove(self, __value: T) -> None:
        try:
            return super().remove(__value)
        except ValueError:
            pass

    def pop(self, __index: int = ...) -> T | None:
        try:
            return super().pop() if __index is ... else super().pop(__index)
        except KeyError:
            pass

    def get(self, __index: int = 0, default=None) -> T | None:
        try:
            return self[__index]
        except IndexError:
            return default


class Duration(object):
    @classmethod
    def empty(cls):
        return cls(None)

    def __init__(self, seconds: int | None):
        self.total_seconds = seconds or 0
        self.null = seconds is None

        m, s = divmod(self.total_seconds, 60)
        h, m = divmod(m, 60)

        self.second = int(s)
        self.minute = int(m)
        self.hour = int(h)

    def __str__(self):
        if self.null:
            return "--:--"

        if self.hour > 0:
            return "{0.hour}:{0.minute:02}:{0.second:02}".format(self)
        return "{0.minute:02}:{0.second:02}".format(self)

    def __repr__(self):
        hours, minutes, seconds = self.hour, self.minute, self.second
        return f"<{type(self).__name__} {hours=} {minutes=} {seconds=}>"
