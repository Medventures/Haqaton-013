from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite:"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
