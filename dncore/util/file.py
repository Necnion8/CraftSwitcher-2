import datetime
import os
import platform
from pathlib import Path

__all__ = ["creation_file_date"]


def creation_file_date(path: Path | str):
    """
    Try to get the date that a file was created, falling back to when it was
    last modified if that isn't possible.
    See http://stackoverflow.com/a/39501288/1709587 for explanation.
    """
    if platform.system() == 'Windows':
        creation = os.path.getctime(str(path))
    else:
        stat = os.stat(str(path))
        try:
            # noinspection PyUnresolvedReferences
            creation = stat.st_birthtime

        except AttributeError:
            # We're probably on Linux. No easy way to get creation dates here,
            # so we'll settle for when its content was last modified.
            creation = stat.st_mtime

    return datetime.datetime.fromtimestamp(creation)
