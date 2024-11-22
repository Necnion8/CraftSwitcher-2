from sqlalchemy import Column, Integer, String, DateTime, Uuid, TypeDecorator
from sqlalchemy.orm import declarative_base

from ..fileback.abc import SnapshotStatus, SnapshotFileErrorType, FileType
from ..files import BackupType

__all__ = [
    "Base",
    "User",
    "Backup",
    "SnapshotFile",
    "SnapshotErrorFile",
    # "TrashFile",
]

Base = declarative_base()


class EnumType(TypeDecorator):
    """Store IntEnum as Integer"""

    impl = Integer

    def __init__(self, *args, **kwargs):
        self.enum_class = kwargs.pop('enum_class')
        if kwargs.pop("map_to_int", None):
            self.enum_int_vals = [e.value for e in self.enum_class]
            self.enum_vals = list(self.enum_class)
        TypeDecorator.__init__(self, *args, **kwargs)

    def process_bind_param(self, value, dialect):
        if value is not None:
            if not isinstance(value, self.enum_class):
                raise TypeError("Value should %s type" % self.enum_class)
            try:
                return self.enum_int_vals.index(value.value)
            except AttributeError:
                return value.value

    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                return self.enum_vals[value]
            except AttributeError:
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

    id = Column(Uuid, primary_key=True)
    type = Column(EnumType(enum_class=BackupType, map_to_int=True))
    source = Column(Uuid, nullable=False)
    created = Column(DateTime(), nullable=False)
    previous_backup = Column(Uuid, nullable=True)
    path = Column(String, nullable=False)
    comments = Column(String, nullable=True, default=None)
    total_files = Column(Integer, nullable=False)
    total_files_size = Column(Integer, nullable=False)
    error_files = Column(Integer, nullable=False)
    final_size = Column(Integer, nullable=True)


class SnapshotFile(Base):
    __tablename__ = "snapshot_files"
    __table_args__ = {
        "sqlite_autoincrement": True,
    }

    backup_id = Column(Uuid, nullable=False)
    path = Column(String, nullable=False)
    type = Column(EnumType(enum_class=FileType), nullable=False)
    size = Column(Integer, nullable=True)
    status = Column(EnumType(enum_class=SnapshotStatus), nullable=False)
    modified = Column(DateTime(), nullable=True)
    hash_md5 = Column(String, nullable=True)

    __mapper_args__ = {
        "primary_key": [backup_id, path]
    }


class SnapshotErrorFile(Base):
    __tablename__ = "snapshot_error_files"
    __table_args__ = {
        "sqlite_autoincrement": True,
    }

    backup_id = Column(Uuid, nullable=False)
    path = Column(String, nullable=False)
    type = Column(EnumType(enum_class=FileType), nullable=True)
    error_type = Column(EnumType(enum_class=SnapshotFileErrorType), nullable=False)
    error_message = Column(String, nullable=True)

    __mapper_args__ = {
        "primary_key": [backup_id, path]
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
