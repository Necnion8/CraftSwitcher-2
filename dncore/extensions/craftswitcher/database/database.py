import asyncio
import datetime
import secrets
from logging import getLogger
from pathlib import Path

from passlib.context import CryptContext
from sqlalchemy import URL, select, delete
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .model import *
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

    async def get_backup(self, backup_id: int) -> Backup | None:
        async with self.session() as db:
            result = await db.execute(select(Backup).where(Backup.id == backup_id))
            try:
                return result.one()[0]
            except NoResultFound:
                return None

    async def add_backup(self, backup: Backup):
        async with self._commit_lock:
            async with self.session() as db:
                db.add(backup)
                await db.flush()
                await db.refresh(backup)
                backup_id = backup.id
                await db.commit()
                return backup_id

    async def remove_backup(self, backup: Backup | int):
        async with self._commit_lock:
            async with self.session() as db:
                if isinstance(backup, Backup):
                    await db.delete(backup)
                else:
                    await db.execute(delete(Backup).where(Backup.id == backup))
                await db.commit()
