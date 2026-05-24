"""Unit tests for application timezone configuration."""

from datetime import date

import psycopg
import pytest

from tallybadger.core.timezone import (
    application_timezone_name,
    configure_connection_timezone,
    configure_database_default_timezone,
)


def test_application_timezone_name_is_iana_string() -> None:
    tz = application_timezone_name()
    assert tz
    assert "/" in tz or tz in {"UTC", "GMT"}


@pytest.mark.integration
def test_configure_connection_timezone_aligns_current_date(integration_db_url: str) -> None:
    configure_database_default_timezone(integration_db_url)
    with psycopg.connect(integration_db_url) as conn:
        configure_connection_timezone(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT CURRENT_DATE")
            row = cur.fetchone()
            assert row is not None
            assert row[0] == date.today()


@pytest.mark.integration
def test_database_default_timezone_without_session_set(integration_db_url: str) -> None:
    configure_database_default_timezone(integration_db_url)
    with psycopg.connect(integration_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT CURRENT_DATE")
            row = cur.fetchone()
            assert row is not None
            assert row[0] == date.today()
