"""Integration tests: PUT accrual journal entry settlement (#278)."""

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
    AccrualPlanCreate,
    LedgerSettingsUpdate,
    PartyCreate,
    SettlementAllocationIn,
    SettlementWrite,
)
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
def clean_tables(integration_db_url: str) -> Iterator[None]:
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    TRUNCATE TABLE
                      settlement_allocations,
                      accrual_obligations,
                      journal_entry_review_messages,
                      journal_lines,
                      journal_entries,
                      import_batches,
                      accrual_plans,
                      cheques,
                      parties,
                      accounts,
                      cel_rule_sets
                    RESTART IDENTITY CASCADE
                    """,
                )
                cur.execute(
                    "INSERT INTO ledger_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
                )
    yield


@pytest.fixture
def api_client(integration_db_url: str) -> Iterator[TestClient]:
    from tallybadger.api.routes.ledger import get_ledger_service

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    def _ledger() -> LedgerService:
        return LedgerService(connection_factory=connection_factory)

    app.dependency_overrides[get_ledger_service] = _ledger
    yield TestClient(app)
    app.dependency_overrides.pop(get_ledger_service, None)


@pytest.fixture
def ledger_service(integration_db_url: str) -> LedgerService:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    return LedgerService(connection_factory=connection_factory)


def _count_rows(integration_db_url: str, table: str) -> int:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
            return int(cur.fetchone()["c"])


def _setup_rent_accrual(
    api_client: TestClient,
) -> tuple[int, int, int, int, int, int, int, int]:
    account_ids: dict[str, int] = {}
    for name, acct_type in (
        ("Cash", "asset"),
        ("Cash B", "asset"),
        ("Rent Revenue", "revenue"),
        ("Accounts Receivable", "asset"),
        ("Unearned Revenue", "liability"),
    ):
        resp = api_client.post(
            "/accounts",
            json={"name": name, "type": acct_type, "is_active": True},
        )
        assert resp.status_code == 201, resp.text
        account_ids[name] = int(resp.json()["id"])

    cash_id = account_ids["Cash"]
    cash_b_id = account_ids["Cash B"]
    ar_id = account_ids["Accounts Receivable"]
    rent_id = account_ids["Rent Revenue"]
    ur_id = account_ids["Unearned Revenue"]

    pr = api_client.post(
        "/parties",
        json={"name": "Pamela Tenant", "role": "customer", "is_active": True},
    )
    assert pr.status_code == 201, pr.text
    party_id = pr.json()["id"]

    assert (
        api_client.patch(
            "/ledger-settings",
            json={
                "accounts_receivable_account_id": ar_id,
                "unearned_revenue_account_id": ur_id,
            },
        ).status_code
        == 200
    )

    plan = api_client.post(
        "/accrual-plans",
        json={
            "name": "July rent",
            "direction": "revenue",
            "party_id": party_id,
            "target_account_id": rent_id,
            "frequency": "monthly_day",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
            "amount": "1500.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    assert plan.status_code == 201, plan.text

    obligations = api_client.get(f"/obligations/{party_id}").json()
    assert len(obligations) == 1
    obligation_id = obligations[0]["id"]
    accrual_entry_id = obligations[0]["source_entry_id"]
    return party_id, cash_id, cash_b_id, ar_id, obligation_id, accrual_entry_id, rent_id, ur_id


def _accrual_put_payload(
    *,
    entry_date: date,
    summary: str,
    rent_id: int,
    party_id: int,
    obligation_id: int | None,
    cash_lines: list[tuple[int, Decimal]],
    bridge_account_id: int | None = None,
    bridge_amount: Decimal | None = None,
    fixed_lines: list[tuple[int, Decimal]] | None = None,
    cheque_id: int | None = None,
) -> dict:
    """Build accrual PUT body: obligation_id on cash lines, optional bridge without obligation."""
    accrual_amount = Decimal("1500.00")
    lines: list[dict] = [
        {"account_id": rent_id, "party_id": party_id, "amount": str(-accrual_amount)},
    ]
    if fixed_lines:
        for account_id, amount in fixed_lines:
            lines.append({"account_id": account_id, "party_id": party_id, "amount": str(amount)})
    if bridge_account_id is not None and bridge_amount is not None and bridge_amount != Decimal("0"):
        lines.append(
            {
                "account_id": bridge_account_id,
                "party_id": party_id,
                "amount": str(bridge_amount),
            }
        )
    for cash_id, amount in cash_lines:
        line: dict = {
            "account_id": cash_id,
            "party_id": party_id,
            "amount": str(amount),
        }
        if obligation_id is not None:
            line["obligation_id"] = obligation_id
        lines.append(line)
    body: dict = {
        "entry_date": entry_date.isoformat(),
        "summary": summary,
        "lines": lines,
    }
    if cheque_id is not None:
        body["cheque_id"] = cheque_id
    return body


def _settlement_payload_bridge_shape(
    *,
    entry_date: date,
    cash_id: int,
    ar_id: int,
    party_id: int,
    obligation_id: int,
    amount: Decimal,
    summary: str = "July rent",
) -> dict:
    """Normal settlement JE shape (obligation on bridge) — must be rejected on accrual PUT."""
    return {
        "entry_date": entry_date.isoformat(),
        "summary": summary,
        "lines": [
            {"account_id": cash_id, "party_id": party_id, "amount": str(amount)},
            {
                "account_id": ar_id,
                "party_id": party_id,
                "amount": str(-amount),
                "obligation_id": obligation_id,
            },
        ],
    }


def _create_separate_settlement(
    api_client: TestClient,
    *,
    party_id: int,
    cash_id: int,
    ar_id: int,
    obligation_id: int,
    amount: Decimal,
    entry_date: date = date(2026, 7, 16),
) -> int:
    post = api_client.post(
        "/journal-entries",
        json={
            "entry_date": entry_date.isoformat(),
            "summary": "Separate settlement",
            "lines": [
                {"account_id": cash_id, "party_id": party_id, "amount": str(amount)},
                {
                    "account_id": ar_id,
                    "party_id": party_id,
                    "amount": str(-amount),
                    "obligation_id": obligation_id,
                },
            ],
        },
    )
    assert post.status_code == 201, post.text
    return int(post.json()["id"])


def test_put_accrual_partial_settlement(
    api_client: TestClient,
) -> None:
    party_id, cash_id, _, ar_id, obligation_id, accrual_entry_id, rent_id, _ = _setup_rent_accrual(
        api_client
    )

    put = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            bridge_account_id=ar_id,
            bridge_amount=Decimal("1000.00"),
            cash_lines=[(cash_id, Decimal("500.00"))],
        ),
    )
    assert put.status_code == 200, put.text

    entry = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    assert entry["source_obligation_id"] == obligation_id
    assert Decimal(entry["open_amount"]) == Decimal("1000.00")
    assert len(entry["settlement_allocations"]) == 1
    by_account = {line["account_id"]: Decimal(line["amount"]) for line in entry["lines"]}
    assert by_account[ar_id] == Decimal("1000.00")
    assert by_account[cash_id] == Decimal("500.00")


def test_put_accrual_full_collapse_single_cash(
    api_client: TestClient,
) -> None:
    party_id, cash_id, _, ar_id, obligation_id, accrual_entry_id, rent_id, _ = _setup_rent_accrual(
        api_client
    )

    put = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            cash_lines=[(cash_id, Decimal("1500.00"))],
        ),
    )
    assert put.status_code == 200, put.text

    entry = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    assert Decimal(entry["open_amount"]) == Decimal("0.00")
    account_ids = {line["account_id"] for line in entry["lines"]}
    assert ar_id not in account_ids
    assert len(entry["lines"]) == 2


def test_put_accrual_unsettle(
    api_client: TestClient,
) -> None:
    party_id, cash_id, _, ar_id, obligation_id, accrual_entry_id, rent_id, _ = _setup_rent_accrual(
        api_client
    )

    settle = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            bridge_account_id=ar_id,
            bridge_amount=Decimal("1000.00"),
            cash_lines=[(cash_id, Decimal("500.00"))],
        ),
    )
    assert settle.status_code == 200, settle.text

    unsettle = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=None,
            bridge_account_id=ar_id,
            bridge_amount=Decimal("1500.00"),
            cash_lines=[],
        ),
    )
    assert unsettle.status_code == 200, unsettle.text

    entry = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    assert entry["settlement_allocations"] == []
    assert Decimal(entry["open_amount"]) == Decimal("1500.00")
    by_account = {line["account_id"]: Decimal(line["amount"]) for line in entry["lines"]}
    assert by_account[ar_id] == Decimal("1500.00")
    assert cash_id not in by_account


def test_put_accrual_adjust_settlement_amount(
    api_client: TestClient,
) -> None:
    party_id, cash_id, _, ar_id, obligation_id, accrual_entry_id, rent_id, _ = _setup_rent_accrual(
        api_client
    )

    assert (
        api_client.put(
            f"/journal-entries/{accrual_entry_id}",
            json=_accrual_put_payload(
                entry_date=date(2026, 7, 1),
                summary="July rent",
                rent_id=rent_id,
                party_id=party_id,
                obligation_id=obligation_id,
                bridge_account_id=ar_id,
                bridge_amount=Decimal("1000.00"),
                cash_lines=[(cash_id, Decimal("500.00"))],
            ),
        ).status_code
        == 200
    )

    adjust = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            bridge_account_id=ar_id,
            bridge_amount=Decimal("700.00"),
            cash_lines=[(cash_id, Decimal("800.00"))],
        ),
    )
    assert adjust.status_code == 200, adjust.text

    entry = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    assert Decimal(entry["open_amount"]) == Decimal("700.00")
    by_account = {line["account_id"]: Decimal(line["amount"]) for line in entry["lines"]}
    assert by_account[cash_id] == Decimal("800.00")


def test_put_accrual_exceeds_open_amount_rejected(
    api_client: TestClient,
) -> None:
    party_id, cash_id, _, ar_id, obligation_id, accrual_entry_id, rent_id, _ = _setup_rent_accrual(
        api_client
    )

    put = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            bridge_account_id=ar_id,
            bridge_amount=Decimal("-500.00"),
            cash_lines=[(cash_id, Decimal("2000.00"))],
        ),
    )
    assert put.status_code == 422, put.text


def test_put_accrual_rejects_bridge_shape_settlement(
    api_client: TestClient,
) -> None:
    party_id, cash_id, _, ar_id, obligation_id, accrual_entry_id, _, _ = _setup_rent_accrual(api_client)

    put = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_settlement_payload_bridge_shape(
            entry_date=date(2026, 7, 1),
            cash_id=cash_id,
            ar_id=ar_id,
            party_id=party_id,
            obligation_id=obligation_id,
            amount=Decimal("500.00"),
        ),
    )
    assert put.status_code == 422, put.text


def test_put_accrual_rejects_header_and_pnl_edits(
    api_client: TestClient,
) -> None:
    party_id, cash_id, _, ar_id, obligation_id, accrual_entry_id, rent_id, _ = _setup_rent_accrual(
        api_client
    )

    bad_date = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 2),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            bridge_account_id=ar_id,
            bridge_amount=Decimal("1000.00"),
            cash_lines=[(cash_id, Decimal("500.00"))],
        ),
    )
    assert bad_date.status_code == 422, bad_date.text

    bad_pnl = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json={
            "entry_date": "2026-07-01",
            "summary": "July rent",
            "lines": [
                {"account_id": rent_id, "party_id": party_id, "amount": "-1400.00"},
                {"account_id": ar_id, "party_id": party_id, "amount": "900.00"},
                {
                    "account_id": cash_id,
                    "party_id": party_id,
                    "amount": "500.00",
                    "obligation_id": obligation_id,
                },
            ],
        },
    )
    assert bad_pnl.status_code == 422, bad_pnl.text


def test_put_accrual_order_partial_elsewhere_then_remainder(
    api_client: TestClient,
) -> None:
    party_id, cash_id, _, ar_id, obligation_id, accrual_entry_id, rent_id, _ = _setup_rent_accrual(
        api_client
    )

    _create_separate_settlement(
        api_client,
        party_id=party_id,
        cash_id=cash_id,
        ar_id=ar_id,
        obligation_id=obligation_id,
        amount=Decimal("500.00"),
    )

    put = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            bridge_account_id=ar_id,
            bridge_amount=Decimal("500.00"),
            cash_lines=[(cash_id, Decimal("1000.00"))],
        ),
    )
    assert put.status_code == 200, put.text

    entry = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    assert Decimal(entry["open_amount"]) == Decimal("0.00")


def test_put_accrual_order_partial_on_accrual_then_remainder_elsewhere(
    api_client: TestClient,
) -> None:
    party_id, cash_id, _, ar_id, obligation_id, accrual_entry_id, rent_id, _ = _setup_rent_accrual(
        api_client
    )

    partial = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            bridge_account_id=ar_id,
            bridge_amount=Decimal("1000.00"),
            cash_lines=[(cash_id, Decimal("500.00"))],
        ),
    )
    assert partial.status_code == 200, partial.text

    remainder = api_client.post(
        "/journal-entries",
        json={
            "entry_date": "2026-07-16",
            "summary": "Remainder settlement",
            "lines": [
                {"account_id": cash_id, "party_id": party_id, "amount": "1000.00"},
                {
                    "account_id": ar_id,
                    "party_id": party_id,
                    "amount": "-1000.00",
                    "obligation_id": obligation_id,
                },
            ],
        },
    )
    assert remainder.status_code == 201, remainder.text

    entry = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    assert Decimal(entry["open_amount"]) == Decimal("0.00")


def test_put_accrual_partial_prepaid_shape_settles_ar_only(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    party_id, cash_id, _, ar_id, obligation_id, accrual_entry_id, rent_id, ur_id = _setup_rent_accrual(
        api_client
    )

    ledger_service.record_settlement(
        SettlementWrite(
            party_id=party_id,
            settlement_type="receipt",
            event_date=date(2026, 6, 26),
            amount=Decimal("500.00"),
            cash_account_id=cash_id,
            allocations=[
                SettlementAllocationIn(obligation_id=obligation_id, amount=Decimal("500.00")),
            ],
            note="early receipt",
        )
    )

    put = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            fixed_lines=[(ur_id, Decimal("500.00"))],
            bridge_account_id=ar_id,
            bridge_amount=Decimal("0.00"),
            cash_lines=[(cash_id, Decimal("1000.00"))],
        ),
    )
    assert put.status_code == 200, put.text

    entry = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    by_account = {line["account_id"]: Decimal(line["amount"]) for line in entry["lines"]}
    assert by_account[ur_id] == Decimal("500.00")
    assert by_account[cash_id] == Decimal("1000.00")
    assert ar_id not in by_account or by_account.get(ar_id, Decimal("0")) == Decimal("0")


def test_put_accrual_multi_cash_full_collapse(
    api_client: TestClient,
) -> None:
    party_id, cash_id, cash_b_id, ar_id, obligation_id, accrual_entry_id, rent_id, _ = _setup_rent_accrual(
        api_client
    )

    put = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            cash_lines=[
                (cash_id, Decimal("900.00")),
                (cash_b_id, Decimal("600.00")),
            ],
        ),
    )
    assert put.status_code == 200, put.text

    entry = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    assert len(entry["settlement_allocations"]) == 1
    alloc_id = entry["settlement_allocations"][0]["id"]
    linked = [line for line in entry["lines"] if line.get("settlement_allocation_id") == alloc_id]
    assert len(linked) == 2
    assert sum(abs(Decimal(line["amount"])) for line in linked) == Decimal("1500.00")


def test_put_accrual_reduce_cash_reintroduces_bridge(
    api_client: TestClient,
) -> None:
    party_id, cash_id, _, ar_id, obligation_id, accrual_entry_id, rent_id, _ = _setup_rent_accrual(
        api_client
    )

    assert (
        api_client.put(
            f"/journal-entries/{accrual_entry_id}",
            json=_accrual_put_payload(
                entry_date=date(2026, 7, 1),
                summary="July rent",
                rent_id=rent_id,
                party_id=party_id,
                obligation_id=obligation_id,
                cash_lines=[(cash_id, Decimal("1500.00"))],
            ),
        ).status_code
        == 200
    )

    reduce = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            bridge_account_id=ar_id,
            bridge_amount=Decimal("500.00"),
            cash_lines=[(cash_id, Decimal("1000.00"))],
        ),
    )
    assert reduce.status_code == 200, reduce.text

    entry = api_client.get(f"/journal-entries/{accrual_entry_id}").json()
    by_account = {line["account_id"]: Decimal(line["amount"]) for line in entry["lines"]}
    assert by_account[ar_id] == Decimal("500.00")
    assert by_account[cash_id] == Decimal("1000.00")


def test_put_accrual_cheque_requires_single_cash_line(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    party_id, cash_id, cash_b_id, ar_id, obligation_id, accrual_entry_id, rent_id, _ = _setup_rent_accrual(
        api_client
    )
    bank = ledger_service.create_account(AccountCreate(name="Chequing", type="asset"))

    ch = api_client.post(
        "/cheques",
        json={
            "credit_account_id": bank.id,
            "debit_account_id": ar_id,
            "summary": "Rent cheque",
            "cheque_number": 7,
            "issue_date": "2026-07-01",
            "amount": "500.00",
        },
    )
    assert ch.status_code == 201, ch.text
    cheque_id = ch.json()["id"]

    no_cash = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=None,
            bridge_account_id=ar_id,
            bridge_amount=Decimal("1500.00"),
            cash_lines=[],
            cheque_id=cheque_id,
        ),
    )
    assert no_cash.status_code == 422, no_cash.text

    multi = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            cash_lines=[
                (cash_id, Decimal("300.00")),
                (cash_b_id, Decimal("200.00")),
            ],
            cheque_id=cheque_id,
        ),
    )
    assert multi.status_code == 422, multi.text

    ok = api_client.put(
        f"/journal-entries/{accrual_entry_id}",
        json=_accrual_put_payload(
            entry_date=date(2026, 7, 1),
            summary="July rent",
            rent_id=rent_id,
            party_id=party_id,
            obligation_id=obligation_id,
            bridge_account_id=ar_id,
            bridge_amount=Decimal("1000.00"),
            cash_lines=[(cash_id, Decimal("500.00"))],
            cheque_id=cheque_id,
        ),
    )
    assert ok.status_code == 200, ok.text

    reg = api_client.get(f"/cheques/{cheque_id}").json()
    assert reg["status"] == "cleared"
