import asyncio
import datetime
import gzip
import inspect
import logging.handlers
import os
from io import TextIOWrapper, StringIO
from pathlib import Path
from threading import Lock
from typing import TextIO, Callable, Any

from dncore.util.file import creation_file_date

__all__ = ["DaysRotatingFileHandler", "PackageNameInserter", "RedirectStream", "get_caller_logger", "taskmessage"]


class DaysRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    HANDLERS = []

    def __init__(self, latest_name):
        self.rotate_latest(Path(latest_name))
        logging.handlers.TimedRotatingFileHandler.__init__(
            self, latest_name, when="midnight", encoding="utf-8", delay=True)
        DaysRotatingFileHandler.HANDLERS.append(self)

    def rotate(self, source, dest):
        creation = creation_file_date(source)
        handlers = self.close_all()
        os.rename(source, dest)

        parent = Path(dest).parent
        with open(dest, "rb") as f_in:
            with gzip.open(parent / "{0.year:04}-{0.month:02}-{0.day:02}.log.gz".format(creation), "wb") as f_out:
                f_out.writelines(f_in)

        os.remove(dest)
        self.open_all(handlers)

    @staticmethod
    def rotate_latest(path: Path):
        if not path.is_file():
            return
        creation = creation_file_date(path)

        if creation.date() >= datetime.date.today():
            return

        parent = Path(path.parent)

        with path.open("rb") as f_in:
            with gzip.open(parent / "{0.year:04}-{0.month:02}-{0.day:02}.log.gz".format(creation), "wb") as f_out:
                f_out.writelines(f_in)

        os.remove(str(path))

    def close_all(self):
        filename = self.baseFilename
        handlers = []

        for handler in DaysRotatingFileHandler.HANDLERS:
            if isinstance(handler, logging.FileHandler):
                if filename == handler.baseFilename:
                    handler.close()
                    handlers.append(handler)

        return handlers

    # noinspection PyMethodMayBeStatic,PyProtectedMember
    def open_all(self, handlers: list[logging.FileHandler]):
        for handler in handlers:
            handler._open()


class PackageNameInserter(logging.Filter):
    def __init__(self, size=30):
        logging.Filter.__init__(self)
        self._caches = {}
        self.size = size

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            name = self._caches[record.name]
        except KeyError:
            name = record.name[18:] if record.name.startswith("dncore.extensions.") else record.name
            parts = name.split(".")
            idx = 1
            while self.size < len(".".join(parts)) and idx < len(parts):
                parts[idx] = parts[idx][:2]
                idx += 1

            name = ".".join(parts)
            name = name + " " * (self.size - len(name))
            self._caches[record.name] = name

        record.logname = name
        return True


class RedirectStream(TextIOWrapper):
    def __init__(self, stream: TextIO, logger: Callable[[Any], None]):
        TextIOWrapper.__init__(self, StringIO(), encoding="utf8")
        self.stream = stream
        self.logger = logger
        self.lock = Lock()
        self.buf = ""

    def write(self, data: str) -> int:
        with self.lock:
            self.buf += data
            while "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                self.logger(line)
        return len(data)


class TaskMessage:
    def __init__(self, logger: Callable, *args, delay=3.0):
        self.task = asyncio.create_task(self._delay(delay, logger, args))

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.task.done():
            self.task.cancel()

    async def _delay(self, delay, logger, args):
        await asyncio.sleep(delay)
        logger(*args)


def get_caller_logger():
    f = inspect.currentframe()
    try:
        return logging.getLogger(f.f_back.f_back.f_code.co_name)
    finally:
        del f


taskmessage = TaskMessage
