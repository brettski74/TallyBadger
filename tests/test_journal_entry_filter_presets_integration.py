"""Integration tests for journal entry filter preset persistence (#107)."""

from collections.abc import Iterator
from contextlib import contextmanager
import os

import pytest
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.ledger.journal_entry_filter_preset_service import (
    JournalEntryFilterPresetConflictError,
    JournalEntryFilterPresetNotFoundError,
    JournalEntryFilterPresetService,
)
from tallybadger.ledger.models import JournalEntryFilterPresetDefinition

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def integration_db_url() -> str:
    db_url = os.environ.get("TALLYBADGER_TEST_DATABASE_URL")
    if not db_url:
        pytest.skip("TALLYBADGER_TEST_DATABASE_URL not set; skipping integration tests")
    return db_url


@pytest.fixture(scope="session", autouse=True)
def migrated_database(integration_db_url: str) -> None:
    apply_sql_migrations(integration_db_url)


@pytest.fixture(autouse=True)
def clean_database(integration_db_url: str) -> Iterator[None]:
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "TRUNCATE TABLE journal_entry_filter_presets RESTART IDENTITY"
                )
    yield


@pytest.fixture
def preset_service(integration_db_url: str) -> JournalEntryFilterPresetService:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    return JournalEntryFilterPresetService(connection_factory=connection_factory)


def test_create_then_list_and_update_roundtrip(
    preset_service: JournalEntryFilterPresetService,
) -> None:
    created = preset_service.create_preset(
        name="Needs review under 500",
        definition=JournalEntryFilterPresetDefinition(
            needs_review=True,
            amount_low=0,
            amount_high=500,
            account_ids=[1, 2],
            cheque_association="without_cheque",
        ),
    )
    assert created.id > 0
    assert created.name == "Needs review under 500"
    assert created.definition.needs_review is True
    assert created.definition.amount_high == 500
    assert created.definition.cheque_association == "without_cheque"

    rows = preset_service.list_presets()
    assert [r.name for r in rows] == ["Needs review under 500"]

    updated = preset_service.update_preset(
        created.id,
        name="Renamed preset",
        definition=JournalEntryFilterPresetDefinition(needs_review=None, amount_high=None),
    )
    assert updated.name == "Renamed preset"
    assert updated.definition.needs_review is None
    assert updated.definition.amount_high is None


def test_duplicate_name_raises_conflict(
    preset_service: JournalEntryFilterPresetService,
) -> None:
    preset_service.create_preset(
        name="Duplicate",
        definition=JournalEntryFilterPresetDefinition(),
    )
    with pytest.raises(JournalEntryFilterPresetConflictError):
        preset_service.create_preset(
            name="Duplicate",
            definition=JournalEntryFilterPresetDefinition(),
        )


def test_delete_missing_raises_not_found(
    preset_service: JournalEntryFilterPresetService,
) -> None:
    with pytest.raises(JournalEntryFilterPresetNotFoundError):
        preset_service.delete_preset(99999)


def test_preset_roundtrips_date_math_expressions(
    preset_service: JournalEntryFilterPresetService,
) -> None:
    created = preset_service.create_preset(
        name="Last seven days",
        definition=JournalEntryFilterPresetDefinition(
            from_date="now-7d",
            to_date="now",
        ),
    )
    assert created.definition.from_date == "now-7d"
    assert created.definition.to_date == "now"

    loaded = preset_service.get_preset(created.id)
    assert loaded.definition.from_date == "now-7d"
    assert loaded.definition.to_date == "now"


def test_preset_legacy_iso_dates_coerced_to_strings(
    preset_service: JournalEntryFilterPresetService,
) -> None:
    from datetime import date

    created = preset_service.create_preset(
        name="Fixed range",
        definition=JournalEntryFilterPresetDefinition.model_validate(
            {"from_date": date(2026, 1, 1), "to_date": date(2026, 1, 31)},
        ),
    )
    assert created.definition.from_date == "2026-01-01"
    assert created.definition.to_date == "2026-01-31"


def test_preset_invalid_date_expression_rejected() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="could not parse"):
        JournalEntryFilterPresetDefinition(from_date="not-valid", to_date="now")


def test_preset_roundtrips_sort_keys(
    preset_service: JournalEntryFilterPresetService,
) -> None:
    created = preset_service.create_preset(
        name="By amount desc",
        definition=JournalEntryFilterPresetDefinition(
            needs_review=True,
            sort=[
                {"field": "amount", "direction": "desc"},
                {"field": "entry_date", "direction": "asc"},
            ],
        ),
    )
    assert len(created.definition.sort) == 2
    assert created.definition.sort[0].field == "amount"
    assert created.definition.sort[0].direction == "desc"

    loaded = preset_service.get_preset(created.id)
    assert loaded.definition.sort[1].field == "entry_date"


def test_invalid_sort_field_raises_value_error(
    preset_service: JournalEntryFilterPresetService,
) -> None:
    with pytest.raises(ValueError, match="unknown sort field"):
        preset_service.create_preset(
            name="Bad",
            definition=JournalEntryFilterPresetDefinition(
                sort=[{"field": "created_at", "direction": "asc"}],
            ),
        )
