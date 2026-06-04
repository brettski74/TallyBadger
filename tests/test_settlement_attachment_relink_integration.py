"""Integration tests: accrual attachments re-linked on settlement (#260)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import hashlib
import os

import pytest
from fastapi.testclient import TestClient
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.import_rules.cel_rule_set_service import CelRuleSetService
from tallybadger.ledger.models import (
    AccountCreate,
    AccrualPlanCreate,
    JournalEntryWrite,
    JournalLineIn,
    LedgerSettingsUpdate,
    PartyCreate,
    SettlementAllocationIn,
    SettlementWrite,
)
from tallybadger.ledger.service import LedgerService
from tallybadger.main import app

pytestmark = pytest.mark.integration

_MINIMAL_PDF = b"%PDF-1.1\n1 0 obj<<>>endobj trailer<<>>\n%%EOF"


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
                      journal_entry_attachments,
                      attachments,
                      journal_lines,
                      journal_entries,
                      import_batches,
                      accrual_plans,
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
def ledger_service(integration_db_url: str) -> LedgerService:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    return LedgerService(connection_factory=connection_factory)


@pytest.fixture
def import_api_client(integration_db_url: str) -> Iterator[TestClient]:
    from tallybadger.api.routes.cel_rule_sets import get_cel_rule_set_service
    from tallybadger.api.routes.import_csv import get_cel_rule_set_service as get_csv_cel_service
    from tallybadger.api.routes.import_csv import get_ledger_service as get_import_ledger_service
    from tallybadger.api.routes.ledger import get_ledger_service as get_ledger_ledger_service

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    def _ledger() -> LedgerService:
        return LedgerService(connection_factory=connection_factory)

    app.dependency_overrides[get_import_ledger_service] = _ledger
    app.dependency_overrides[get_ledger_ledger_service] = _ledger
    app.dependency_overrides[get_cel_rule_set_service] = lambda: CelRuleSetService(
        connection_factory=connection_factory,
    )
    app.dependency_overrides[get_csv_cel_service] = lambda: CelRuleSetService(
        connection_factory=connection_factory,
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_import_ledger_service, None)
    app.dependency_overrides.pop(get_ledger_ledger_service, None)
    app.dependency_overrides.pop(get_cel_rule_set_service, None)
    app.dependency_overrides.pop(get_csv_cel_service, None)


def _setup_rent_accrual(ledger_service: LedgerService) -> tuple[int, int, int, int, int]:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(accounts_receivable_account_id=ar.id),
    )
    party = ledger_service.create_party(
        PartyCreate(name="Pamela Tenant", role="customer", is_active=True),
    )
    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="July rent",
            direction="revenue",
            party_id=party.id,
            target_account_id=rent.id,
            frequency="monthly_day",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            amount=Decimal("1500.00"),
            summary_template="{plan}",
            day_of_month=1,
        ),
    )
    ob = ledger_service.list_open_obligations(party.id)[0]
    assert ob.source_entry_id is not None
    return party.id, cash.id, ar.id, ob.id, ob.source_entry_id


def test_record_settlement_relinks_attachment_to_settlement_je(
    ledger_service: LedgerService,
) -> None:
    party_id, cash_id, _ar_id, ob_id, accrual_entry_id = _setup_rent_accrual(ledger_service)
    att = ledger_service.add_journal_entry_attachment(
        accrual_entry_id,
        file_bytes=_MINIMAL_PDF,
        upload_filename="bill.pdf",
        summary="July bill scan",
        external_reference=None,
    )

    result = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party_id,
            settlement_type="receipt",
            event_date=date(2026, 7, 15),
            amount=Decimal("1500.00"),
            cash_account_id=cash_id,
            allocations=[SettlementAllocationIn(obligation_id=ob_id, amount=Decimal("1500.00"))],
            note=None,
        ),
    )
    assert result.entry_id != accrual_entry_id

    accrual_atts = ledger_service.list_journal_entry_attachments(accrual_entry_id)
    settle_atts = ledger_service.list_journal_entry_attachments(result.entry_id)
    assert len(accrual_atts) == 1
    assert len(settle_atts) == 1
    assert accrual_atts[0].id == att.id
    assert settle_atts[0].id == att.id


def test_partial_settlements_relink_to_each_settlement_je(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    party_id, cash_id, _ar_id, ob_id, accrual_entry_id = _setup_rent_accrual(ledger_service)
    att = ledger_service.add_journal_entry_attachment(
        accrual_entry_id,
        file_bytes=_MINIMAL_PDF,
        upload_filename="bill.pdf",
        summary="bill",
        external_reference=None,
    )

    first = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party_id,
            settlement_type="receipt",
            event_date=date(2026, 7, 10),
            amount=Decimal("500.00"),
            cash_account_id=cash_id,
            allocations=[SettlementAllocationIn(obligation_id=ob_id, amount=Decimal("500.00"))],
            note=None,
        ),
    )
    second = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party_id,
            settlement_type="receipt",
            event_date=date(2026, 7, 20),
            amount=Decimal("1000.00"),
            cash_account_id=cash_id,
            allocations=[SettlementAllocationIn(obligation_id=ob_id, amount=Decimal("1000.00"))],
            note=None,
        ),
    )
    assert first.entry_id != second.entry_id
    for entry_id in (first.entry_id, second.entry_id):
        linked = ledger_service.list_journal_entry_attachments(entry_id)
        assert len(linked) == 1
        assert linked[0].id == att.id

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT link_count FROM attachments WHERE id = %s", (att.id,))
            assert int(cur.fetchone()["link_count"]) == 3


def test_unlink_from_settlement_je_preserves_attachment_while_accrual_linked(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    party_id, cash_id, _ar_id, ob_id, accrual_entry_id = _setup_rent_accrual(ledger_service)
    att = ledger_service.add_journal_entry_attachment(
        accrual_entry_id,
        file_bytes=_MINIMAL_PDF,
        upload_filename="bill.pdf",
        summary="bill",
        external_reference=None,
    )
    result = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party_id,
            settlement_type="receipt",
            event_date=date(2026, 7, 15),
            amount=Decimal("1500.00"),
            cash_account_id=cash_id,
            allocations=[SettlementAllocationIn(obligation_id=ob_id, amount=Decimal("1500.00"))],
            note=None,
        ),
    )
    ledger_service.unlink_journal_entry_attachment(result.entry_id, att.id)
    assert ledger_service.list_journal_entry_attachments(result.entry_id) == []
    assert len(ledger_service.list_journal_entry_attachments(accrual_entry_id)) == 1

    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM attachments WHERE id = %s", (att.id,))
            assert int(cur.fetchone()["c"]) == 1


def test_import_line_settlement_relinks_attachment(
    ledger_service: LedgerService,
) -> None:
    party_id, cash_id, ar_id, ob_id, accrual_entry_id = _setup_rent_accrual(ledger_service)
    att = ledger_service.add_journal_entry_attachment(
        accrual_entry_id,
        file_bytes=_MINIMAL_PDF,
        upload_filename="bill.pdf",
        summary="bill",
        external_reference=None,
    )
    payload = JournalEntryWrite(
        entry_date=date(2026, 7, 15),
        summary="Rent receipt",
        lines=[
            JournalLineIn(account_id=cash_id, party_id=party_id, amount=Decimal("1500.00")),
            JournalLineIn(
                account_id=ar_id,
                party_id=party_id,
                amount=Decimal("-1500.00"),
                obligation_id=ob_id,
            ),
        ],
    )
    batch_id, created = ledger_service.create_import_batch_with_entries(
        basename="settle.csv",
        content_sha256=hashlib.sha256(b"settle").digest(),
        payloads=[payload],
        confirm_duplicate_content=False,
    )
    assert batch_id > 0
    settle_entry_id = created[0].id
    assert settle_entry_id != accrual_entry_id
    linked = ledger_service.list_journal_entry_attachments(settle_entry_id)
    assert len(linked) == 1
    assert linked[0].id == att.id


def test_csv_auto_settlement_relinks_attachment(
    import_api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    for payload in (
        {"name": "Cash", "type": "asset", "is_active": True},
        {"name": "Rent Revenue", "type": "revenue", "is_active": True},
        {"name": "Accounts Receivable", "type": "asset", "is_active": True},
    ):
        assert import_api_client.post("/accounts", json=payload).status_code == 201
    by_name = {a["name"]: a["id"] for a in import_api_client.get("/accounts").json()}
    import_api_client.patch(
        "/ledger-settings",
        json={"accounts_receivable_account_id": by_name["Accounts Receivable"]},
    )
    party_id = import_api_client.post(
        "/parties",
        json={"name": "Pamela Tenant", "role": "customer", "is_active": True},
    ).json()["id"]
    import_api_client.post(
        "/accrual-plans",
        json={
            "name": "July rent",
            "direction": "revenue",
            "party_id": party_id,
            "target_account_id": by_name["Rent Revenue"],
            "frequency": "monthly_day",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
            "amount": "1500.00",
            "summary_template": "{plan}",
            "day_of_month": 1,
        },
    )
    accrual_entry_id = import_api_client.get(f"/obligations/{party_id}").json()[0]["source_entry_id"]
    att = ledger_service.add_journal_entry_attachment(
        accrual_entry_id,
        file_bytes=_MINIMAL_PDF,
        upload_filename="bill.pdf",
        summary="bill",
        external_reference=None,
    )

    expression = (
        '{"set": {'
        '"settlement": "receipt", '
        '"summary": attributes["summary"], '
        '"amount": attributes["amount"], '
        '"date": attributes["date"], '
        '"cr-account": "Rent Revenue", '
        '"cr-party": "Pamela Tenant"'
        "}}"
    )
    rule_set_id = import_api_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "auto", "rule_set": {"rules": [{"sort_order": 10, "expression": expression}]}},
    ).json()["id"]
    result = import_api_client.post(
        "/imports/csv/execute",
        json={
            "csv_text": "date,summary,amount\n2026-07-15,Pamela rent,1500.00\n",
            "basename": "auto.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string"},
                {"attribute_name": "amount", "data_type": "numeric"},
            ],
            "cel_rule_set_id": rule_set_id,
            "default_import_account_id": by_name["Cash"],
            "default_import_normal_balance": "debit",
        },
    )
    assert result.status_code == 200, result.text
    entries = import_api_client.get("/journal-entries", params={"limit": 10}).json()
    settlement_entries = [
        e for e in entries if e["id"] != accrual_entry_id and e["summary"] == "Pamela rent"
    ]
    assert len(settlement_entries) == 1
    settle_id = settlement_entries[0]["id"]
    linked = ledger_service.list_journal_entry_attachments(settle_id)
    assert len(linked) == 1
    assert linked[0].id == att.id
