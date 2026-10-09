from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, connect_args={"check_same_thread": False})
    return _engine


def _default_sql(column: Any) -> str:
    """A SQL literal for a new column's default, so existing rows get a sensible value."""
    default = column.default
    value = getattr(default, "arg", None) if default is not None else None
    if callable(value):
        try:
            value = value(None)
        except TypeError:
            value = value()
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list | dict):
        import json

        return "'" + json.dumps(value).replace("'", "''") + "'"
    return "'" + str(value).replace("'", "''") + "'"


def _add_missing_columns(engine: Engine) -> None:
    """create_all() makes new tables but never alters existing ones. New columns are
    always additive with defaults, so adding them is all the migration this app needs."""
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                type_sql = column.type.compile(dialect=engine.dialect)
                conn.execute(
                    text(
                        f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {type_sql} '
                        f"DEFAULT {_default_sql(column)}"
                    )
                )


def init_db() -> None:
    from app import models  # noqa: F401  (registers tables)

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
