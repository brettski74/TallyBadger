"""Integration tests for ledger_settings.default_cash_account_id (#276)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.ledger.models import AccountCreate, AccountUpdate
from tallybadger.ledger.service import LedgerService
from tallybadger.main import app

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
def clean_ledger_tables(integration_db_url: str) -> Iterator[None]:
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    TRUNCATE TABLE
                      import_templates,
                      journal_lines,
                      journal_entry_review_messages,
                      journal_entry_attachments,
                      attachments,
                      journal_entries,
                      import_batches,
                      cheques,
                      accrual_obligations,
                      settlement_allocations,
                      party_match_patterns,
                      accrual_plans,
                      parties,
                      cel_rule_sets,
                      ledger_settings,
                      accounts
                    RESTART IDENTITY CASCADE
                    """
                )
                cur.execute("INSERT INTO ledger_settings (id) VALUES (1)")
    yield


@pytest.fixture
def api_client(integration_db_url: str) -> Iterator[TestClient]:
    from tallybadger.api.routes.ledger import get_ledger_service

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    app.dependency_overrides[get_ledger_service] = lambda: LedgerService(
        connection_factory=connection_factory,
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_ledger_service, None)


@pytest.fixture
def ledger_service(integration_db_url: str) -> LedgerService:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    return LedgerService(connection_factory=connection_factory)


def test_ledger_settings_default_cash_account_round_trip_via_api(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    assert api_client.get("/ledger-settings").json()["default_cash_account_id"] is None

    cash = ledger_service.create_account(AccountCreate(name="Chequing", type="asset"))
    set_resp = api_client.patch(
        "/ledger-settings",
        json={"default_cash_account_id": cash.id},
    )
    assert set_resp.status_code == 200, set_resp.text
    assert set_resp.json()["default_cash_account_id"] == cash.id
    assert api_client.get("/ledger-settings").json()["default_cash_account_id"] == cash.id

    clear_resp = api_client.patch(
        "/ledger-settings",
        json={"default_cash_account_id": None},
    )
    assert clear_resp.status_code == 200, clear_resp.text
    assert clear_resp.json()["default_cash_account_id"] is None
    assert api_client.get("/ledger-settings").json()["default_cash_account_id"] is None


def test_ledger_settings_default_cash_account_accepts_liability(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    loc = ledger_service.create_account(AccountCreate(name="Line of Credit", type="liability"))
    resp = api_client.patch(
        "/ledger-settings",
        json={"default_cash_account_id": loc.id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["default_cash_account_id"] == loc.id


def test_ledger_settings_default_cash_account_rejects_ineligible_type(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    expense = ledger_service.create_account(AccountCreate(name="Rent", type="expense"))
    resp = api_client.patch(
        "/ledger-settings",
        json={"default_cash_account_id": expense.id},
    )
    assert resp.status_code == 422, resp.text
    errors = resp.json()["detail"]["errors"]
    assert len(errors) == 1
    assert errors[0] == (
        f'Ledger setting "Default cash account" requires an asset or liability account. '
        f'"Rent" ({expense.id}) is an expense account.'
    )


def test_ledger_settings_default_cash_account_rejects_inactive_on_change(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Old Bank", type="asset"))
    ledger_service.update_account(cash.id, AccountUpdate(is_active=False))
    resp = api_client.patch(
        "/ledger-settings",
        json={"default_cash_account_id": cash.id},
    )
    assert resp.status_code == 422, resp.text
    errors = resp.json()["detail"]["errors"]
    assert len(errors) == 1
    assert errors[0] == (
        f'Ledger setting "Default cash account" cannot use deactivated account '
        f'"Old Bank" ({cash.id}).'
    )


def test_ledger_settings_default_cash_account_skips_validation_on_unchanged(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Chequing", type="asset"))
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ledger_settings SET default_cash_account_id = %s WHERE id = 1",
                    (cash.id,),
                )
                cur.execute("UPDATE accounts SET is_active = FALSE WHERE id = %s", (cash.id,))

    resp = api_client.patch(
        "/ledger-settings",
        json={"default_cash_account_id": cash.id},
    )
    assert resp.status_code == 200, resp.text
