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
from tallybadger.ledger.models import (
    AccountCreate,
    ChequeCreate,
    JournalEntryWrite,
    JournalLineIn,
    PartyCreate,
)
from tallybadger.ledger.service import LedgerService, LedgerValidationError
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


def _two_accounts(ledger_service: LedgerService) -> tuple[int, int]:
    cr = ledger_service.create_account(AccountCreate(name="Chequing", type="asset"))
    dr = ledger_service.create_account(AccountCreate(name="Expense", type="expense"))
    return cr.id, dr.id


def _fetch_cheque_defaults(integration_db_url: str) -> tuple[int | None, int | None]:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT default_cheque_credit_account_id, default_cheque_debit_account_id
                FROM ledger_settings
                WHERE id = 1
                """,
            )
            row = cur.fetchone() or {}
    return (
        row.get("default_cheque_credit_account_id"),
        row.get("default_cheque_debit_account_id"),
    )


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

    listed_default = api_client.get("/cheques")
    assert listed_default.status_code == 200
    assert len(listed_default.json()["cheques"]) == 1

    listed_all = api_client.get("/cheques", params={"status": "all"})
    assert listed_all.status_code == 200
    assert len(listed_all.json()["cheques"]) == 1

    listed_void = api_client.get("/cheques", params={"status": "void"})
    assert listed_void.status_code == 200
    assert len(listed_void.json()["cheques"]) == 0

    patch_void = api_client.patch(f"/cheques/{cid}", json={"status": "void"})
    assert patch_void.status_code == 200
    assert patch_void.json()["status"] == "void"
    assert patch_void.json()["cleared_date"] is None

    patch_open = api_client.patch(f"/cheques/{cid}", json={"status": "open"})
    assert patch_open.status_code == 200
    assert patch_open.json()["status"] == "open"


def test_create_cheque_always_open_ignores_client_status(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    create = api_client.post(
        "/cheques",
        json={
            "credit_account_id": cr_id,
            "debit_account_id": dr_id,
            "summary": "Sneaky",
            "cheque_number": 77,
            "issue_date": "2026-05-01",
            "cleared_date": "2026-05-02",
            "amount": "1.00",
            "party_id": None,
            "status": "cleared",
        },
    )
    assert create.status_code == 201, create.text
    data = create.json()
    assert data["status"] == "open"
    assert data["cleared_date"] is None


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
            "amount": "20.00",
        },
    )
    assert create.status_code == 201
    cid = create.json()["id"]
    cleared = api_client.patch(
        f"/cheques/{cid}",
        json={"status": "cleared", "cleared_date": "2026-05-03"},
    )
    assert cleared.status_code == 200, cleared.text
    bad = api_client.patch(f"/cheques/{cid}", json={"status": "void"})
    assert bad.status_code == 422


def test_journal_create_marks_cheque_cleared(
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
            "amount": "75.00",
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
    assert entry.cheque_id == cheque_id

    reg = api_client.get(f"/cheques/{cheque_id}")
    assert reg.status_code == 200
    data = reg.json()
    assert data["status"] == "cleared"
    assert data["cleared_date"] == "2026-05-05"


def test_journal_second_entry_cannot_link_same_cheque(ledger_service: LedgerService) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    ch = ledger_service.create_cheque(
        ChequeCreate(
            credit_account_id=cr_id,
            debit_account_id=dr_id,
            summary="Dup test",
            cheque_number=101,
            issue_date=date(2026, 5, 1),
            amount=Decimal("10.00"),
        )
    )
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 2),
            summary="First",
            lines=[
                JournalLineIn(account_id=dr_id, amount=Decimal("10.00")),
                JournalLineIn(account_id=cr_id, amount=Decimal("-10.00")),
            ],
            cheque_id=ch.id,
        )
    )
    with pytest.raises(LedgerValidationError, match="already cleared"):
        ledger_service.create_entry(
            JournalEntryWrite(
                entry_date=date(2026, 5, 3),
                summary="Second",
                lines=[
                    JournalLineIn(account_id=dr_id, amount=Decimal("10.00")),
                    JournalLineIn(account_id=cr_id, amount=Decimal("-10.00")),
                ],
                cheque_id=ch.id,
            )
        )


def test_journal_cannot_link_void_cheque(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    ch = api_client.post(
        "/cheques",
        json={
            "credit_account_id": cr_id,
            "debit_account_id": dr_id,
            "summary": "Voided",
            "cheque_number": 102,
            "issue_date": "2026-05-04",
            "amount": "5.00",
        },
    )
    assert ch.status_code == 201
    cheque_id = ch.json()["id"]
    voided = api_client.patch(f"/cheques/{cheque_id}", json={"status": "void"})
    assert voided.status_code == 200, voided.text

    with pytest.raises(LedgerValidationError, match="void"):
        ledger_service.create_entry(
            JournalEntryWrite(
                entry_date=date(2026, 5, 5),
                summary="Bad",
                lines=[
                    JournalLineIn(account_id=dr_id, amount=Decimal("5.00")),
                    JournalLineIn(account_id=cr_id, amount=Decimal("-5.00")),
                ],
                cheque_id=cheque_id,
            )
        )


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
            "cheque_number": 103,
            "issue_date": "2026-05-04",
            "amount": "75.00",
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


# ---------------------------------------------------------------------------
# #105 — credit/debit account eligibility + last-used defaults.
# ---------------------------------------------------------------------------


def _cheque_body(cr_id: int, dr_id: int, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "credit_account_id": cr_id,
        "debit_account_id": dr_id,
        "summary": "Eligibility test",
        "cheque_number": 500,
        "issue_date": "2026-05-10",
        "amount": "10.00",
    }
    body.update(overrides)
    return body


def test_create_cheque_rejects_non_asset_credit(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    asset_cr = ledger_service.create_account(AccountCreate(name="Chequing", type="asset"))
    bad_credit = ledger_service.create_account(AccountCreate(name="Bad Credit", type="expense"))
    debit = ledger_service.create_account(AccountCreate(name="Rent", type="expense"))

    resp = api_client.post(
        "/cheques",
        json=_cheque_body(bad_credit.id, debit.id, cheque_number=510),
    )
    assert resp.status_code == 422, resp.text
    assert "asset" in resp.text.lower()
    # Eligibility rejection must not move the stored defaults.
    assert _fetch_cheque_defaults(integration_db_url) == (None, None)
    # Sanity: a valid post still succeeds once accounts line up.
    ok = api_client.post(
        "/cheques",
        json=_cheque_body(asset_cr.id, debit.id, cheque_number=511),
    )
    assert ok.status_code == 201, ok.text


def test_create_cheque_rejects_inactive_credit(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    # Deactivate the asset credit account directly to bypass higher-level UX gates.
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("UPDATE accounts SET is_active = FALSE WHERE id = %s", (cr_id,))

    resp = api_client.post("/cheques", json=_cheque_body(cr_id, dr_id, cheque_number=520))
    assert resp.status_code == 422, resp.text
    assert "active" in resp.text.lower()


def test_create_cheque_rejects_suspense_debit(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cr = ledger_service.create_account(AccountCreate(name="Chequing", type="asset"))
    suspense = ledger_service.create_account(
        AccountCreate(name="Unallocated Debits", type="suspense"),
    )

    resp = api_client.post("/cheques", json=_cheque_body(cr.id, suspense.id, cheque_number=530))
    assert resp.status_code == 422, resp.text
    assert "suspense" in resp.text.lower()


def test_successful_create_writes_both_default_accounts(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    assert _fetch_cheque_defaults(integration_db_url) == (None, None)

    resp = api_client.post("/cheques", json=_cheque_body(cr_id, dr_id, cheque_number=540))
    assert resp.status_code == 201, resp.text

    assert _fetch_cheque_defaults(integration_db_url) == (cr_id, dr_id)


def test_patch_changing_credit_validates_and_writes_only_credit_default(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    other_asset = ledger_service.create_account(
        AccountCreate(name="Savings", type="asset"),
    )
    create = api_client.post(
        "/cheques",
        json=_cheque_body(cr_id, dr_id, cheque_number=550),
    )
    assert create.status_code == 201, create.text
    cheque_id = create.json()["id"]
    assert _fetch_cheque_defaults(integration_db_url) == (cr_id, dr_id)

    # Move debit default away from the cheque's stored debit so we can prove the
    # update path doesn't touch it when only credit changed.
    other_debit = ledger_service.create_account(AccountCreate(name="Office", type="expense"))
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ledger_settings SET default_cheque_debit_account_id = %s "
                    "WHERE id = 1",
                    (other_debit.id,),
                )

    patch = api_client.patch(
        f"/cheques/{cheque_id}",
        json={"credit_account_id": other_asset.id},
    )
    assert patch.status_code == 200, patch.text
    cr_default, dr_default = _fetch_cheque_defaults(integration_db_url)
    assert cr_default == other_asset.id
    assert dr_default == other_debit.id


def test_patch_unchanged_account_skips_validation_and_default_write(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    create = api_client.post(
        "/cheques",
        json=_cheque_body(cr_id, dr_id, cheque_number=560),
    )
    assert create.status_code == 201, create.text
    cheque_id = create.json()["id"]

    # Wipe defaults so we can detect whether the next PATCH writes anything.
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ledger_settings SET default_cheque_credit_account_id = NULL, "
                    "default_cheque_debit_account_id = NULL WHERE id = 1",
                )

    # After the cheque was saved, deactivate the credit account. The PATCH below
    # must still succeed because the cheque isn't changing the account id.
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE accounts SET is_active = FALSE WHERE id = %s",
                    (cr_id,),
                )

    patch = api_client.patch(
        f"/cheques/{cheque_id}",
        json={"summary": "Updated summary"},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["summary"] == "Updated summary"
    # No account change → defaults untouched.
    assert _fetch_cheque_defaults(integration_db_url) == (None, None)

    # And explicitly re-asserting the same account ids is also allowed (no change).
    patch2 = api_client.patch(
        f"/cheques/{cheque_id}",
        json={"credit_account_id": cr_id, "debit_account_id": dr_id},
    )
    assert patch2.status_code == 200, patch2.text
    assert _fetch_cheque_defaults(integration_db_url) == (None, None)


def test_patch_changing_only_debit_writes_only_debit_default(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    create = api_client.post(
        "/cheques",
        json=_cheque_body(cr_id, dr_id, cheque_number=570),
    )
    assert create.status_code == 201, create.text
    cheque_id = create.json()["id"]

    # Establish a known credit default that differs from the cheque's credit
    # so we can detect any spurious write to it.
    other_asset = ledger_service.create_account(AccountCreate(name="Savings", type="asset"))
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ledger_settings SET default_cheque_credit_account_id = %s "
                    "WHERE id = 1",
                    (other_asset.id,),
                )

    other_debit = ledger_service.create_account(AccountCreate(name="Utilities", type="expense"))
    patch = api_client.patch(
        f"/cheques/{cheque_id}",
        json={"debit_account_id": other_debit.id},
    )
    assert patch.status_code == 200, patch.text
    cr_default, dr_default = _fetch_cheque_defaults(integration_db_url)
    assert cr_default == other_asset.id
    assert dr_default == other_debit.id


def test_ledger_settings_patch_validates_new_cheque_defaults(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cr = ledger_service.create_account(AccountCreate(name="Chequing", type="asset"))
    suspense = ledger_service.create_account(
        AccountCreate(name="Unallocated Debits", type="suspense"),
    )
    expense = ledger_service.create_account(AccountCreate(name="Rent", type="expense"))

    # Asset is valid for credit default.
    ok_credit = api_client.patch(
        "/ledger-settings",
        json={"default_cheque_credit_account_id": cr.id},
    )
    assert ok_credit.status_code == 200, ok_credit.text
    assert ok_credit.json()["default_cheque_credit_account_id"] == cr.id

    # Expense is not asset → reject for credit default.
    bad_credit = api_client.patch(
        "/ledger-settings",
        json={"default_cheque_credit_account_id": expense.id},
    )
    assert bad_credit.status_code == 422, bad_credit.text
    credit_errors = bad_credit.json()["detail"]["errors"]
    assert len(credit_errors) == 1
    assert "Default cheque credit account" in credit_errors[0]
    assert "Rent" in credit_errors[0]

    # Suspense is rejected for debit default.
    bad_debit = api_client.patch(
        "/ledger-settings",
        json={"default_cheque_debit_account_id": suspense.id},
    )
    assert bad_debit.status_code == 422, bad_debit.text
    debit_errors = bad_debit.json()["detail"]["errors"]
    assert len(debit_errors) == 1
    assert "Default cheque debit account" in debit_errors[0]

    # Non-suspense (e.g. expense) is allowed for debit default.
    ok_debit = api_client.patch(
        "/ledger-settings",
        json={"default_cheque_debit_account_id": expense.id},
    )
    assert ok_debit.status_code == 200, ok_debit.text
    assert ok_debit.json()["default_cheque_debit_account_id"] == expense.id


def test_ledger_settings_patch_skips_validation_on_unchanged_default(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    cr = ledger_service.create_account(AccountCreate(name="Chequing", type="asset"))
    # Plant a current default, then deactivate the underlying account.
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ledger_settings SET default_cheque_credit_account_id = %s "
                    "WHERE id = 1",
                    (cr.id,),
                )
                cur.execute("UPDATE accounts SET is_active = FALSE WHERE id = %s", (cr.id,))

    # Re-affirming the same id (which is now inactive) is allowed.
    resp = api_client.patch(
        "/ledger-settings",
        json={"default_cheque_credit_account_id": cr.id},
    )
    assert resp.status_code == 200, resp.text


def _series_body(
    cr_id: int,
    dr_id: int,
    *,
    count: int | None = None,
    end_date: str | None = None,
    starting_issue_date: str = "2025-11-01",
    starting_cheque_number: int = 1001,
) -> dict:
    schedule: dict = {"increment_unit": "months", "increment_n": 1}
    if count is not None:
        schedule["count"] = count
    else:
        schedule["end_date"] = end_date
    return {
        "credit_account_id": cr_id,
        "debit_account_id": dr_id,
        "summary": "Snow removal",
        "starting_cheque_number": starting_cheque_number,
        "starting_issue_date": starting_issue_date,
        "amount": "900.00",
        "party_id": None,
        "schedule": schedule,
    }


def test_cheque_series_preview_snow_removal_five_months(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    preview = api_client.post(
        "/cheques/series/preview",
        json=_series_body(cr_id, dr_id, end_date="2026-03-31"),
    )
    assert preview.status_code == 200, preview.text
    rows = preview.json()["rows"]
    assert len(rows) == 5
    assert [r["issue_date"] for r in rows] == [
        "2025-11-01",
        "2025-12-01",
        "2026-01-01",
        "2026-02-01",
        "2026-03-01",
    ]
    assert [r["cheque_number"] for r in rows] == [1001, 1002, 1003, 1004, 1005]


def test_cheque_series_create_atomic(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    create = api_client.post(
        "/cheques/series",
        json=_series_body(cr_id, dr_id, count=3),
    )
    assert create.status_code == 201, create.text
    created = create.json()
    assert len(created) == 3
    listed = api_client.get("/cheques")
    assert listed.status_code == 200
    assert len(listed.json()["cheques"]) == 3


def test_cheque_series_rejects_over_max_count(
    api_client: TestClient,
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ledger_settings SET max_cheque_series_count = 2 WHERE id = 1",
                )
    preview = api_client.post(
        "/cheques/series/preview",
        json=_series_body(cr_id, dr_id, count=3),
    )
    assert preview.status_code == 422, preview.text
    assert "maximum is 2" in preview.text


def test_cheque_series_atomic_rollback_on_conflict(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    assert (
        api_client.post(
            "/cheques",
            json={
                "credit_account_id": cr_id,
                "debit_account_id": dr_id,
                "summary": "Existing",
                "cheque_number": 1002,
                "issue_date": "2026-01-01",
                "amount": "1.00",
            },
        ).status_code
        == 201
    )
    conflict = api_client.post(
        "/cheques/series",
        json=_series_body(cr_id, dr_id, count=3, starting_cheque_number=1001),
    )
    assert conflict.status_code == 409, conflict.text
    listed = api_client.get("/cheques")
    assert len(listed.json()["cheques"]) == 1


def test_ledger_settings_exposes_max_cheque_series_count(api_client: TestClient) -> None:
    resp = api_client.get("/ledger-settings")
    assert resp.status_code == 200
    assert resp.json()["max_cheque_series_count"] == 60


def _post_cheque(
    api_client: TestClient,
    cr_id: int,
    dr_id: int,
    **overrides: object,
) -> dict[str, object]:
    resp = api_client.post("/cheques", json=_cheque_body(cr_id, dr_id, **overrides))
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_list_cheques_omitted_status_returns_all_statuses(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    open_row = _post_cheque(api_client, cr_id, dr_id, cheque_number=601, summary="Open one")
    void_id = _post_cheque(api_client, cr_id, dr_id, cheque_number=602, summary="Void one")["id"]
    cleared_id = _post_cheque(api_client, cr_id, dr_id, cheque_number=603, summary="Cleared one")["id"]

    assert api_client.patch(f"/cheques/{void_id}", json={"status": "void"}).status_code == 200
    assert (
        api_client.patch(
            f"/cheques/{cleared_id}",
            json={"status": "cleared", "cleared_date": "2026-05-15"},
        ).status_code
        == 200
    )

    all_rows = api_client.get("/cheques").json()["cheques"]
    assert len(all_rows) == 3
    assert {row["status"] for row in all_rows} == {"open", "void", "cleared"}

    open_rows = api_client.get("/cheques", params={"status": "open"}).json()["cheques"]
    assert len(open_rows) == 1
    assert open_rows[0]["id"] == open_row["id"]


def test_list_cheques_party_ids_filter(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    party_a = ledger_service.create_party(PartyCreate(name="Alice Tenant", role="customer"))
    party_b = ledger_service.create_party(PartyCreate(name="Bob Vendor", role="vendor"))

    alice_id = _post_cheque(
        api_client,
        cr_id,
        dr_id,
        cheque_number=701,
        party_id=party_a.id,
        summary="Alice cheque",
    )["id"]
    _post_cheque(
        api_client,
        cr_id,
        dr_id,
        cheque_number=702,
        party_id=party_b.id,
        summary="Bob cheque",
    )
    no_party_id = _post_cheque(
        api_client,
        cr_id,
        dr_id,
        cheque_number=703,
        party_id=None,
        summary="No party cheque",
    )["id"]

    by_a = api_client.get("/cheques", params=[("party_ids", str(party_a.id))]).json()["cheques"]
    assert {row["id"] for row in by_a} == {alice_id}

    by_null = api_client.get("/cheques", params=[("party_ids", "null")]).json()["cheques"]
    assert {row["id"] for row in by_null} == {no_party_id}

    combined = api_client.get(
        "/cheques",
        params=[("party_ids", str(party_a.id)), ("party_ids", "null")],
    ).json()["cheques"]
    assert {row["id"] for row in combined} == {alice_id, no_party_id}

    bad = api_client.get("/cheques", params=[("party_ids", "nope")])
    assert bad.status_code == 422


def test_list_cheques_filter_options_global(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    party = ledger_service.create_party(PartyCreate(name="Zara Zulu", role="customer"))
    _post_cheque(api_client, cr_id, dr_id, cheque_number=801, party_id=party.id)
    _post_cheque(api_client, cr_id, dr_id, cheque_number=802, party_id=None)

    options = api_client.get("/cheques/filter-options")
    assert options.status_code == 200
    body = options.json()
    assert body["parties"][0] == {"id": None, "name": "(no party)"}
    assert body["parties"][1] == {"id": party.id, "name": "Zara Zulu"}
    assert body["credit_accounts"] == [{"id": cr_id, "name": "Chequing"}]
    assert body["debit_accounts"] == [{"id": dr_id, "name": "Expense"}]

    empty_list = api_client.get(
        "/cheques",
        params={"summary": "^no-such-cheque$"},
    ).json()["cheques"]
    assert empty_list == []

    options_after_filter = api_client.get("/cheques/filter-options").json()
    assert options_after_filter == body


def test_list_cheques_filters_sort_and_validation(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    cr_id, dr_id = _two_accounts(ledger_service)
    _post_cheque(
        api_client,
        cr_id,
        dr_id,
        cheque_number=901,
        issue_date="2026-01-10",
        amount="10.00",
        summary="Alpha rent",
    )
    _post_cheque(
        api_client,
        cr_id,
        dr_id,
        cheque_number=902,
        issue_date="2026-02-10",
        amount="20.00",
        summary="Beta rent",
    )

    filtered = api_client.get(
        "/cheques",
        params={
            "issue_from_date": "2026-02-01",
            "min_amount": "15.00",
            "summary": "beta",
            "sort": ["amount:desc"],
        },
    ).json()["cheques"]
    assert len(filtered) == 1
    assert filtered[0]["cheque_number"] == 902

    default_sort = api_client.get("/cheques").json()["cheques"]
    assert [row["cheque_number"] for row in default_sort] == [902, 901]

    bad_range = api_client.get(
        "/cheques",
        params={"issue_from_date": "2026-03-01", "issue_to_date": "2026-01-01"},
    )
    assert bad_range.status_code == 422

    bad_regex = api_client.get("/cheques", params={"summary": "[unclosed"})
    assert bad_regex.status_code == 422

    bad_sort = api_client.get("/cheques", params={"sort": ["not_a_field:asc"]})
    assert bad_sort.status_code == 422
