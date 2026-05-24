"""Pytest hooks shared across backend tests.

Patches :func:`psycopg.connect` at import time so test modules that bind ``connect``
via ``from psycopg import connect`` still receive timezone-aware connections.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from tallybadger.core.timezone import configure_connection_timezone

_original_psycopg_connect = psycopg.connect


def _connect_with_timezone(conninfo: str = "", **kwargs):
    conn = _original_psycopg_connect(conninfo, **kwargs)
    configure_connection_timezone(conn)
    return conn


psycopg.connect = _connect_with_timezone  # type: ignore[assignment]


@pytest.fixture(scope="session")
def integration_db_url() -> str:
    db_url = os.environ.get("TALLYBADGER_TEST_DATABASE_URL")
    if not db_url:
        pytest.skip("TALLYBADGER_TEST_DATABASE_URL not set; skipping integration tests")
    return db_url
