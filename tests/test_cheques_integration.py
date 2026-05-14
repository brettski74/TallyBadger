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
from tallybadger.ledger.models import AccountCreate, ChequeCreate, JournalEntryWrite, JournalLineIn
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
    assert len(listed_default.json()) == 1

    listed_all = api_client.get("/cheques", params={"status": "all"})
    assert listed_all.status_code == 200
    assert len(listed_all.json()) == 1

    listed_void = api_client.get("/cheques", params={"status": "void"})
    assert listed_void.status_code == 200
    assert len(listed_void.json()) == 0

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

    # Suspense is rejected for debit default.
    bad_debit = api_client.patch(
        "/ledger-settings",
        json={"default_cheque_debit_account_id": suspense.id},
    )
    assert bad_debit.status_code == 422, bad_debit.text

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
