from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.orm import declarative_base

__all__ = [
    "Base",
    "User",
    "Schedule",
]

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    __table_args__ = {
        "sqlite_autoincrement": True,
    }

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    password = Column(String, nullable=False)
    token = Column(String, nullable=True)
    token_expire = Column(DateTime(), nullable=True, index=True)
    last_login = Column(DateTime(), nullable=True, index=True)
    last_address = Column(String, nullable=True)
    permission = Column(Integer, nullable=False, default=0)


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = {
        "sqlite_autoincrement": True,
    }

    id = Column(Integer, primary_key=True)
    label = Column(String, nullable=False)
    description = Column(String, nullable=True)
    data = Column(JSON, nullable=False)
