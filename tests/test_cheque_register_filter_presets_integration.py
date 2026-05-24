"""Integration tests for cheque register filter preset persistence (#196)."""

from collections.abc import Iterator
from contextlib import contextmanager
import os

import pytest
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.ledger.cheque_register_filter_preset_service import (
    ChequeRegisterFilterPresetConflictError,
    ChequeRegisterFilterPresetNotFoundError,
    ChequeRegisterFilterPresetService,
)
from tallybadger.ledger.models import (
    ChequeRegisterFilterPresetDefinition,
    ChequeRegisterFilterPresetSortKey,
)

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
                    "TRUNCATE TABLE cheque_register_filter_presets RESTART IDENTITY"
                )
    yield


@pytest.fixture
def preset_service(integration_db_url: str) -> ChequeRegisterFilterPresetService:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    return ChequeRegisterFilterPresetService(connection_factory=connection_factory)


def test_create_then_list_and_update_roundtrip(
    preset_service: ChequeRegisterFilterPresetService,
) -> None:
    created = preset_service.create_preset(
        name="Open large",
        definition=ChequeRegisterFilterPresetDefinition(
            status="open",
            credit_account_ids=[1, 2],
            min_amount=0,
            max_amount=500,
            sort=[
                ChequeRegisterFilterPresetSortKey(field="amount", direction="desc"),
                ChequeRegisterFilterPresetSortKey(field="issue_date", direction="asc"),
            ],
        ),
    )
    assert created.id > 0
    assert created.definition.status == "open"
    assert created.definition.sort[0].field == "amount"

    rows = preset_service.list_presets()
    assert [r.name for r in rows] == ["Open large"]

    updated = preset_service.update_preset(
        created.id,
        name="Renamed",
        definition=ChequeRegisterFilterPresetDefinition(status="cleared", sort=[]),
    )
    assert updated.name == "Renamed"
    assert updated.definition.status == "cleared"
    assert updated.definition.sort == []


def test_duplicate_name_raises_conflict(
    preset_service: ChequeRegisterFilterPresetService,
) -> None:
    preset_service.create_preset(
        name="Duplicate",
        definition=ChequeRegisterFilterPresetDefinition(),
    )
    with pytest.raises(ChequeRegisterFilterPresetConflictError):
        preset_service.create_preset(
            name="Duplicate",
            definition=ChequeRegisterFilterPresetDefinition(),
        )


def test_invalid_sort_field_raises_value_error(
    preset_service: ChequeRegisterFilterPresetService,
) -> None:
    with pytest.raises(ValueError, match="unknown sort field"):
        preset_service.create_preset(
            name="Bad",
            definition=ChequeRegisterFilterPresetDefinition(
                sort=[ChequeRegisterFilterPresetSortKey(field="id", direction="asc")],
            ),
        )


def test_delete_missing_raises_not_found(
    preset_service: ChequeRegisterFilterPresetService,
) -> None:
    with pytest.raises(ChequeRegisterFilterPresetNotFoundError):
        preset_service.delete_preset(99999)
