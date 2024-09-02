import asyncio
from logging import getLogger
from pathlib import Path

from sqlalchemy import URL, select, delete
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .model import Base, User

log = getLogger(__name__)


class SwitcherDatabase(object):
    def __init__(self, db_dir: Path, db_filename="switcher.db"):
        self.db_path = db_dir / db_filename
        #
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

    # user

    async def get_users(self) -> list[User]:
        async with self.session() as db:
            result = await db.execute(select(User))
            return [r[0] for r in result.all()]

    async def add_user(self, user: User):
        async with self._commit_lock:
            async with self.session() as db:
                db.add(user)
                await db.commit()

    async def remove_user(self, user: User | int):
        async with self._commit_lock:
            async with self.session() as db:
                if isinstance(user, User):
                    await db.delete(user)
                else:
                    await db.execute(delete(User).where(User.id == user))
                await db.commit()

    async def update_user(self, user: User):
        async with self._commit_lock:
            async with self.session() as db:
                db.add(user)
                await db.commit()
