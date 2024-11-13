from sqlalchemy import Column, Integer, String, DateTime, Uuid, TypeDecorator
from sqlalchemy.orm import declarative_base

from ..fileback.abc import SnapshotStatus

__all__ = [
    "Base",
    "User",
    "Backup",
    "Snapshot",
    "SnapshotFile",
    # "TrashFile",
]


Base = declarative_base()


class EnumType(TypeDecorator):
    """Store IntEnum as Integer"""

    impl = Integer

    def __init__(self, *args, **kwargs):
        self.enum_class = kwargs.pop('enum_class')
        TypeDecorator.__init__(self, *args, **kwargs)

    def process_bind_param(self, value, dialect):
        if value is not None:
            if not isinstance(value, self.enum_class):
                raise TypeError("Value should %s type" % self.enum_class)
            return value.value

    def process_result_value(self, value, dialect):
        if value is not None:
            if not isinstance(value, int):
                raise TypeError("value should have int type")
            return self.enum_class(value)


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


class Backup(Base):
    __tablename__ = "backups"
    __table_args__ = {
        "sqlite_autoincrement": True,
    }

    id = Column(Integer, primary_key=True)
    source = Column(Uuid, nullable=False)
    created = Column(DateTime(), nullable=False)
    path = Column(String, nullable=False)
    size = Column(Integer, nullable=False)
    comments = Column(String, nullable=True, default=None)


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = {
        "sqlite_autoincrement": True,
    }

    id = Column(Integer, primary_key=True)
    source = Column(Uuid, nullable=False)
    created = Column(DateTime(), nullable=False)
    directory = Column(String, nullable=False)
    comments = Column(String, nullable=True, default=None)


class SnapshotFile(Base):
    __tablename__ = "snapshot_files"
    __table_args__ = {
        "sqlite_autoincrement": True,
    }

    snapshot_id = Column(Integer, nullable=False)
    path = Column(String, nullable=False)
    status = Column(EnumType(enum_class=SnapshotStatus), nullable=False)
    modified = Column(DateTime(), nullable=True)
    size = Column(Integer, nullable=True)
    hash = Column(String, nullable=True)

    __mapper_args__ = {
        "primary_key": [snapshot_id, path]
    }


# class TrashFile(Base):
#     __tablename__ = "trash_files"
#     __table_args__ = {
#         "sqlite_autoincrement": True,
#     }
#
#     source = Column(Uuid, nullable=False)
#     deleted = Column(DateTime(), nullable=False)
#     path = Column(String, nullable=False)
#     moved_path = Column(String, nullable=False)
#     modified = Column(DateTime(), nullable=False)
#     size = Column(Integer, nullable=False)
#
#     __mapper_args__ = {
#         "primary_key": [source, moved_path]
#     }
