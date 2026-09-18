from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from sql_agent.core.config import Settings, get_settings
from sql_agent.db.models import Base
from sql_agent.db.seed import seed_database


def ensure_sqlite_parent(database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        return
    database_path = database_url.split("sqlite:///", maxsplit=1)[-1]
    if database_path and database_path != ":memory:":
        Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def build_engine(database_url: str) -> Engine:
    ensure_sqlite_parent(database_url)
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return build_engine(get_settings().database_url)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def init_database(settings: Settings | None = None, *, force_seed: bool = False) -> dict[str, int] | None:
    resolved = settings or get_settings()
    ensure_sqlite_parent(resolved.database_url)
    engine = get_engine() if resolved is get_settings() else build_engine(resolved.database_url)

    # SQLite needs query_only disabled while schema and demo data are prepared.
    if resolved.database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_configure(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    Base.metadata.create_all(engine)
    if not resolved.auto_seed:
        return None
    return seed_database(
        engine,
        force=force_seed,
        scale=resolved.seed_scale,
    )


def session_scope() -> Generator[Session, None, None]:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
    finally:
        session.close()

