import asyncio
import datetime
import secrets
from logging import getLogger
from pathlib import Path
from typing import Callable
from uuid import UUID

from passlib.context import CryptContext
from sqlalchemy import URL, select, delete
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, AsyncEngine, create_async_engine

from .model import *
from ..files import BackupType
from ..utils import datetime_now

log = getLogger(__name__)
TOKEN_EXPIRES = datetime.timedelta(weeks=2)


class SwitcherDatabase(object):
    def __init__(self, db_dir: Path, db_filename="switcher.db"):
        self.db_path = db_dir / db_filename
        #
        self.crypt_context = CryptContext(schemes=["bcrypt"])
        self.engine = None  # type: AsyncEngine | None
        self._commit_lock = asyncio.Lock()

    async def connect(self):
        if self.engine:
            return

        log.debug("Creating database engine")
        url = URL.create(
            drivername="sqlite+aiosqlite",
            database=self.db_path.as_posix(),
            query=dict(
                charset="utf8mb4",
            ),
        )
        self.engine = create_async_engine(url, echo=False)

        async with self.engine.begin() as conn:  # type: AsyncConnection
            await conn.run_sync(Base.metadata.create_all)
        log.debug("Connected database")

    async def close(self):
        if self.engine is None:
            return

        await self.engine.dispose()
        self.engine = None
        log.debug("Closed database engine")

    def session(self) -> AsyncSession:
        return async_sessionmaker(autoflush=True, bind=self.engine)()

    # security

    def generate_hash(self, value: str | bytes):
        return self.crypt_context.hash(value)

    def verify_hash(self, value: str | bytes, hashed_value: str):
        return self.crypt_context.verify(value, hashed_value)

    @classmethod
    def generate_token(cls):
        return secrets.token_urlsafe(256)

    # user

    async def get_users(self) -> list[User]:
        async with self.session() as db:
            result = await db.execute(select(User))
            return [r[0] for r in result.all()]

    async def get_user(self, name: str) -> User | None:
        async with self.session() as db:
            result = await db.execute(select(User).where(User.name == name))
            try:
                return result.one()[0]
            except NoResultFound:
                return None

    async def get_user_by_id(self, user_id: int) -> User | None:
        async with self.session() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            try:
                return result.one()[0]
            except NoResultFound:
                return None

    async def get_user_by_valid_token(self, token: str) -> User | None:
        async with self.session() as db:
            result = await db.execute(select(User).where(User.token == token))
            try:
                user = result.one()[0]
            except NoResultFound:
                return None

            if user.token_expire is None:
                return None

            token_expire = user.token_expire.replace(tzinfo=datetime.timezone.utc)
            return user if datetime_now() < token_expire else None

    async def add_user(self, user: User):
        async with self._commit_lock:
            async with self.session() as db:
                db.add(user)
                await db.flush()
                await db.refresh(user)
                user_id = user.id
                await db.commit()
                return user_id

    async def remove_user(self, user: User | int):
        async with self._commit_lock:
            async with self.session() as db:
                if isinstance(user, User):
                    await db.delete(user)
                else:
                    await db.execute(delete(User).where(User.id == user))
                await db.commit()

    async def update_user(self, user: User | int, **new_values):
        user_id = user if isinstance(user, int) else user.id
        async with self._commit_lock:
            async with self.session() as db:
                result = await db.execute(select(User).where(User.id == user_id))
                try:
                    user = result.one()[0]
                except NoResultFound:
                    raise ValueError("Not exists user")

                for key, val in new_values.items():
                    setattr(user, key, val)
                db.add(user)
                await db.commit()

    async def update_user_token(self, user: User, **new_values):
        token = self.generate_token()
        expires = datetime_now() + TOKEN_EXPIRES
        await self.update_user(user, token=token, token_expire=expires, **new_values)
        return TOKEN_EXPIRES, token, expires

    # backupper

    async def get_backup_ids(self) -> list[tuple[UUID, UUID]]:
        """
        データベース内の全バックアップIDとソースIDを返します (作成日時順)
        """
        async with self.session() as db:
            result = await db.execute(select(Backup.id, Backup.source).order_by(Backup.created))
            return [(r[0], r[1]) for r in result.all()]

    async def get_backups_or_snapshots(self, source: UUID) -> list[Backup]:
        """
        ソースIDに関連するバックアップを返します (作成日時順)
        """
        async with self.session() as db:
            result = await db.execute(
                select(Backup)
                .where(Backup.source == source)
                .order_by(Backup.created)
            )
            return [r[0] for r in result.all()]

    async def edit_backups_or_snapshots(self, source: UUID, processor: Callable[[Backup], bool]) -> list[Backup]:
        """
        バックアップを編集します

        processor が true を返したバックアップが更新され、そのリストを返します
        """
        async with self.session() as db:
            result = await db.execute(
                select(Backup)
                .where(Backup.source == source)
                .order_by(Backup.created)
            )
            _backups = []
            for backup, *_ in result.all():
                if processor(backup):
                    _backups.append(backup)

            if _backups:
                await db.commit()
            return _backups

    async def get_last_snapshot(self, source: UUID, backup_id: UUID) -> Backup | None:
        """
        指定されたバックアップがスナップショットならそれを返し、そうでない場合は元のバックアップをたどり返します。
        """
        backup = await self.get_backup_or_snapshot(backup_id)
        if not backup or BackupType.SNAPSHOT == backup.type:
            return backup or None

        backups = {b.id: b for b in await self.get_backups_or_snapshots(source)}
        while backups:
            try:
                backup = backups.pop(backup_id)
            except KeyError:
                return None  # 前のバックアップが見つからない

            if not backup.previous_backup:
                return None  # 前のバックアップが存在しない

            if BackupType.SNAPSHOT != backup.type:
                backup_id = backup.id  # 更に前のバックアップを探す

            else:
                return backup

    async def get_backup_or_snapshot(self, backup_id: UUID) -> Backup | None:
        """
        指定IDのバックアップを返します
        """
        async with self.session() as db:
            result = await db.execute(select(Backup).where(Backup.id == backup_id))
            try:
                return result.one()[0]
            except NoResultFound:
                return None

    async def add_full_backup(self, backup: Backup):
        if backup.type != BackupType.FULL:
            raise ValueError(f"Not full type backup: {backup.type}")
        async with self._commit_lock:
            async with self.session() as db:
                db.add(backup)
                await db.flush()
                await db.refresh(backup)
                backup_id = backup.id
                await db.commit()
                return backup_id

    async def add_snapshot_backup(self, backup: Backup, files: list[SnapshotFile], errors: list[SnapshotErrorFile]):
        if backup.type != BackupType.SNAPSHOT:
            raise ValueError(f"Not snapshot type backup: {backup.type}")

        def _apply_id(s_id: UUID, f: SnapshotFile | SnapshotErrorFile):
            f.backup_id = s_id
            return f

        async with self._commit_lock:
            async with self.session() as db:
                db.add(backup)
                await db.flush()
                await db.refresh(backup)
                backup_id = backup.id
                db.add_all(_apply_id(backup_id, f) for f in files)
                db.add_all(_apply_id(backup_id, f) for f in errors)
                await db.commit()
                return backup_id

    async def remove_backup_or_snapshot(self, backup: Backup | UUID):
        """
        バックアップと、それに関連づいたスナップショットファイルを全て削除します
        """
        async with self._commit_lock:
            async with self.session() as db:
                if isinstance(backup, Backup):
                    await db.delete(backup)
                    backup_id = backup.id
                else:
                    await db.execute(delete(Backup).where(Backup.id == backup))
                    backup_id = backup

                await db.execute(delete(SnapshotFile).where(SnapshotFile.backup_id == backup_id))
                await db.execute(delete(SnapshotErrorFile).where(SnapshotErrorFile.backup_id == backup_id))
                await db.commit()

    async def get_snapshot_files(self, backup_id: UUID) -> list[SnapshotFile] | None:
        async with self.session() as db:
            result = await db.execute(select(SnapshotFile).where(SnapshotFile.backup_id == backup_id))
            try:
                return [r[0] for r in result.all()]
            except NoResultFound:
                return None

    async def get_snapshot_errors_files(self, backup_id: UUID) -> list[SnapshotErrorFile] | None:
        async with self.session() as db:
            result = await db.execute(select(SnapshotErrorFile).where(SnapshotErrorFile.backup_id == backup_id))
            try:
                return [r[0] for r in result.all()]
            except NoResultFound:
                return None

    async def get_backups_files(self, source: UUID, path: str) -> tuple[list[SnapshotFile], list[Backup]]:
        """
        ソースIDとパスを含むバックアップファイルを返します (バックアップ作成日時順)
        """
        async with self.session() as db:
            result = await db.execute(
                select(SnapshotFile, Backup)
                .where(Backup.source == source)
                .where(Backup.id == SnapshotFile.backup_id)
                .where(SnapshotFile.path == path)
                .order_by(Backup.created)
            )
            files = []
            backups = []
            for s_file, backup in result.all():
                files.append(s_file)
                backups.append(backup)
            return files, backups
