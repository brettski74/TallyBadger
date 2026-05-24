"""Application calendar timezone — shared by PostgreSQL sessions and date parsing."""

from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

import pendulum
from psycopg import Connection, connect as _psycopg_connect, sql


def application_timezone_name() -> str:
    """Return an IANA timezone name for PostgreSQL ``TIME ZONE`` and calendar dates.

    Resolution order:

    1. :envvar:`TALLYBADGER_TIMEZONE`
    2. :envvar:`TALLYBADGER_IMPORT_TZ`
    3. Standard :envvar:`TZ`
    4. :func:`pendulum.local_timezone` (host default)
    5. ``UTC`` when nothing else works
    """
    for key in ("TALLYBADGER_TIMEZONE", "TALLYBADGER_IMPORT_TZ", "TZ"):
        raw = os.environ.get(key, "").strip()
        if raw:
            try:
                return str(pendulum.timezone(raw).name)
            except Exception:
                continue
    try:
        return str(pendulum.local_timezone().name)
    except Exception:
        return "UTC"


def configure_connection_timezone(conn: Connection) -> None:
    """Align PostgreSQL ``CURRENT_DATE`` with the application host calendar."""
    tz = application_timezone_name()
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SET TIME ZONE {}").format(sql.Literal(tz)))


def database_name_from_url(database_url: str) -> str:
    path = urlparse(database_url).path.lstrip("/")
    if not path:
        raise ValueError(f"database URL has no database name: {database_url!r}")
    return path.split("?")[0]


def role_name_from_url(database_url: str) -> str | None:
    return urlparse(database_url).username


def maintenance_database_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    return urlunparse(parsed._replace(path="/postgres"))


def configure_database_default_timezone(database_url: str) -> None:
    """Persist timezone on the database and application role for all new sessions.

    Complements per-connection :func:`configure_connection_timezone` so ad hoc clients
    (psql, GUI tools, scripts) inherit the expected calendar without extra setup.
    """
    tz = application_timezone_name()
    dbname = database_name_from_url(database_url)
    role = role_name_from_url(database_url)
    with _psycopg_connect(maintenance_database_url(database_url), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("ALTER DATABASE {} SET timezone TO {}").format(
                    sql.Identifier(dbname),
                    sql.Literal(tz),
                ),
            )
            if role:
                cur.execute(
                    sql.SQL("ALTER ROLE {} SET timezone TO {}").format(
                        sql.Identifier(role),
                        sql.Literal(tz),
                    ),
                )
