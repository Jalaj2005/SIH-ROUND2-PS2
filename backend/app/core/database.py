from datetime import datetime, timezone
from functools import lru_cache
from typing import Iterator

from sqlalchemy import DateTime, Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo, so restore it)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime rejected: store timezone-aware UTC values.")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def make_engine(url: str, **kwargs) -> Engine:
    if url.startswith("sqlite"):
        kwargs.setdefault("connect_args", {"check_same_thread": False})
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs.setdefault("poolclass", StaticPool)
    else:
        kwargs.setdefault("pool_pre_ping", True)
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_conn, _record):  # enforce FKs in SQLite like PostgreSQL does
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Request-scoped session. Routers commit explicitly so audit rows and the change commit together."""
    db = get_sessionmaker()()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
