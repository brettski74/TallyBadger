"""Integration tests: cheque register API and journal linkage (#90)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import os

import pytest
from fastapi.testclient import TestClient
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.ledger.models import AccountCreate, JournalEntryWrite, JournalLineIn
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
def clean_cheque_tables(integration_db_url: str) -> Iterator[None]:
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
                      cheques,
                      accrual_obligations,
                      settlement_allocations,
                      settlement_events,
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


def _two_accounts(ledger_service: LedgerService) -> tuple[int, int]:
    cr = ledger_service.create_account(AccountCreate(name="Chequing", type="asset"))
    dr = ledger_service.create_account(AccountCreate(name="Expense", type="expense"))
    return cr.id, dr.id


def test_cheque_crud_and_void_reopen(api_client: TestClient, ledger_service: LedgerService) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    create = api_client.post(
        "/cheques",
        json={
            "credit_account_id": cr_id,
            "debit_account_id": dr_id,
            "summary": "Rent cheque",
            "cheque_number": 42,
            "issue_date": "2026-05-01",
            "cleared_date": None,
            "amount": "150.00",
            "party_id": None,
            "status": "open",
        },
    )
    assert create.status_code == 201, create.text
    cid = create.json()["id"]

    listed = api_client.get("/cheques")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    patch_void = api_client.patch(f"/cheques/{cid}", json={"status": "void"})
    assert patch_void.status_code == 200
    assert patch_void.json()["status"] == "void"
    assert patch_void.json()["cleared_date"] is None

    patch_open = api_client.patch(f"/cheques/{cid}", json={"status": "open"})
    assert patch_open.status_code == 200
    assert patch_open.json()["status"] == "open"


def test_duplicate_open_cheque_number_409(api_client: TestClient, ledger_service: LedgerService) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    body = {
        "credit_account_id": cr_id,
        "debit_account_id": dr_id,
        "summary": "First",
        "cheque_number": 7,
        "issue_date": "2026-05-01",
        "amount": "10.00",
        "status": "open",
    }
    assert api_client.post("/cheques", json=body).status_code == 201
    dup = api_client.post("/cheques", json={**body, "summary": "Second"})
    assert dup.status_code == 409


def test_cleared_cheque_cannot_void_via_api(api_client: TestClient, ledger_service: LedgerService) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    create = api_client.post(
        "/cheques",
        json={
            "credit_account_id": cr_id,
            "debit_account_id": dr_id,
            "summary": "Cleared chq",
            "cheque_number": 99,
            "issue_date": "2026-05-02",
            "cleared_date": "2026-05-03",
            "amount": "20.00",
            "status": "cleared",
        },
    )
    assert create.status_code == 201
    cid = create.json()["id"]
    bad = api_client.patch(f"/cheques/{cid}", json={"status": "void"})
    assert bad.status_code == 422


def test_journal_unlink_reopens_cleared_cheque(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    ch = api_client.post(
        "/cheques",
        json={
            "credit_account_id": cr_id,
            "debit_account_id": dr_id,
            "summary": "To clear",
            "cheque_number": 100,
            "issue_date": "2026-05-04",
            "cleared_date": "2026-05-05",
            "amount": "75.00",
            "status": "cleared",
        },
    )
    assert ch.status_code == 201
    cheque_id = ch.json()["id"]

    entry = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 5),
            summary="Clearing",
            lines=[
                JournalLineIn(account_id=dr_id, amount=Decimal("75.00")),
                JournalLineIn(account_id=cr_id, amount=Decimal("-75.00")),
            ],
            cheque_id=cheque_id,
        )
    )

    upd = api_client.put(
        f"/journal-entries/{entry.id}",
        json={
            "entry_date": "2026-05-05",
            "summary": "Clearing",
            "description": None,
            "lines": [
                {"account_id": dr_id, "party_id": None, "amount": "75.00"},
                {"account_id": cr_id, "party_id": None, "amount": "-75.00"},
            ],
            "requires_review": False,
            "review_messages": [],
            "cheque_id": None,
        },
    )
    assert upd.status_code == 200, upd.text

    reg = api_client.get(f"/cheques/{cheque_id}")
    assert reg.status_code == 200
    data = reg.json()
    assert data["status"] == "open"
    assert data["cleared_date"] is None
