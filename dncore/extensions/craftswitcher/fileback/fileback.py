import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import Backup as BackupConfig

if TYPE_CHECKING:
    from ..database import SwitcherDatabase


class Backupper(object):
    def __init__(self, loop: asyncio.AbstractEventLoop,
                 *, database: "SwitcherDatabase", config: BackupConfig,
                 backups_dir: Path, trash_dir: Path, ):
        self.loop = loop
        self._db = database
        self.config = config
        self._backups_dir = backups_dir
        self._trash_dir = trash_dir

    @property
    def backups_dir(self):
        return self._backups_dir

    @property
    def trash_dir(self):
        return self._trash_dir
