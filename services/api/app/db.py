"""Database engine and sessions (SQLAlchemy 2, sync psycopg 3)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    engine = create_engine(
        s.database_url,
        pool_size=s.db_pool_size,
        max_overflow=s.db_pool_size,
        pool_pre_ping=True,
        pool_recycle=1800,
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        with dbapi_conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {int(s.db_statement_timeout_ms)}")
            cur.execute("SET TIME ZONE 'UTC'")
        dbapi_conn.commit()

    return engine


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """One unit of work: commit on success, rollback on any error."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: the handler commits explicitly; anything left open is rolled back."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
