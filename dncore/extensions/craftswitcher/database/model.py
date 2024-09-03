from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base

__all__ = [
    "Base",
    "User",
]

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    password = Column(String, nullable=False)
    token = Column(String, nullable=True)
    token_expire = Column(DateTime(), nullable=True, index=True)
    last_login = Column(DateTime(), nullable=True, index=True)
    last_address = Column(String, nullable=True)
    permission = Column(Integer, nullable=False, default=0)
