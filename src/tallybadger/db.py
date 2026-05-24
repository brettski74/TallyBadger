from collections.abc import Iterator
from contextlib import contextmanager

from psycopg import Connection, connect as _psycopg_connect
from psycopg.rows import dict_row

from tallybadger.core.config import get_settings
from tallybadger.core.timezone import configure_connection_timezone


def connect_database(conninfo: str = "", **kwargs) -> Connection:
    """Open a PostgreSQL connection with application timezone configured."""
    conn = _psycopg_connect(conninfo, **kwargs)
    configure_connection_timezone(conn)
    return conn


@contextmanager
def get_connection() -> Iterator[Connection]:
    settings = get_settings()
    with connect_database(settings.database_url, row_factory=dict_row) as conn:
        yield conn
