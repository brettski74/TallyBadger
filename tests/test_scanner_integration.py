"""Integration tests for flatbed scan API (#258, #259)."""

import io
import json
import tarfile
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.api.routes.ledger import get_scan_backend_dep
from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.backup.snapshot import export_complete_snapshot
from tallybadger.main import app
from tallybadger.ledger.models import (
    AccountCreate,
    AccrualPlanScanCreate,
    JournalEntryWrite,
    JournalLineIn,
    LedgerSettingsUpdate,
    PartyCreate,
)
from tallybadger.ledger.service import LedgerService
from tallybadger.scanner.stub import StubScanBackend, minimal_jpeg_bytes

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session", autouse=True)
def migrated_database(integration_db_url: str) -> None:
    from tallybadger.db_migrations import apply_sql_migrations

    apply_sql_migrations(integration_db_url)


@pytest.fixture(autouse=True)
def clean_database(integration_db_url: str) -> Iterator[None]:
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    TRUNCATE TABLE journal_entry_filter_presets, import_templates,
                      journal_lines, journal_entry_attachments,
                      attachments, journal_entries, import_batches,
                      accrual_obligations, accrual_plans, party_match_patterns, parties, accounts, cel_rule_sets
                    RESTART IDENTITY CASCADE
                    """
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


def test_attachment_link_count_maintained(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    entry = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 5),
            summary="link count",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("1")),
                JournalLineIn(account_id=cash.id, amount=Decimal("-1")),
            ],
        ),
    )
    att = ledger_service.add_journal_entry_attachment(
        entry.id,
        file_bytes=b"hello",
        upload_filename="a.txt",
        summary="doc",
        external_reference=None,
    )
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT link_count FROM attachments WHERE id = %s", (att.id,))
            assert int(cur.fetchone()["link_count"]) == 1
    ledger_service.unlink_journal_entry_attachment(entry.id, att.id)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM attachments WHERE id = %s", (att.id,))
            assert int(cur.fetchone()["c"]) == 0


def test_scan_attach_uses_stub_and_skips_upload_limit(ledger_service: LedgerService) -> None:
    try:
        ledger_service.update_ledger_settings(
            LedgerSettingsUpdate(
                max_attachment_upload_bytes=10,
                scanner_device_uri="hpaio:/example",
            ),
        )
        cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
        expense = ledger_service.create_account(AccountCreate(name="Expense", type="expense"))
        party = ledger_service.create_party(PartyCreate(name="Acme Plumbing", role="vendor", is_active=True))
        entry = ledger_service.create_entry(
            JournalEntryWrite(
                entry_date=date(2026, 5, 30),
                summary="bill entry",
                description=None,
                lines=[
                    JournalLineIn(account_id=expense.id, party_id=party.id, amount=Decimal("50")),
                    JournalLineIn(account_id=cash.id, party_id=party.id, amount=Decimal("-50")),
                ],
            ),
        )
        att = ledger_service.scan_and_attach_journal_entry(
            entry.id,
            summary="Invoice May",
            external_reference=None,
            scan_backend=StubScanBackend(),
        )
        assert att.mime_type == "image/jpeg"
        assert att.original_filename == "20260530.acme-plumbing.invoice-may.jpg"
        blob, _, _ = ledger_service.get_journal_entry_attachment_download(entry.id, att.id)
        assert blob == minimal_jpeg_bytes()
    finally:
        ledger_service.update_ledger_settings(
            LedgerSettingsUpdate(max_attachment_upload_bytes=5242880),
        )


def test_scan_attach_without_party_on_lines(ledger_service: LedgerService) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    expense = ledger_service.create_account(AccountCreate(name="Expense", type="expense"))
    entry = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 30),
            summary="internal transfer",
            description=None,
            lines=[
                JournalLineIn(account_id=expense.id, amount=Decimal("50")),
                JournalLineIn(account_id=cash.id, amount=Decimal("-50")),
            ],
        ),
    )
    att = ledger_service.scan_and_attach_journal_entry(
        entry.id,
        summary="Supporting doc",
        external_reference=None,
        scan_backend=StubScanBackend(),
    )
    assert att.original_filename == "20260530.supporting-doc.jpg"


def test_scan_attach_picks_party_on_largest_pl_line(ledger_service: LedgerService) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    expense_a = ledger_service.create_account(AccountCreate(name="Expense A", type="expense"))
    expense_b = ledger_service.create_account(AccountCreate(name="Expense B", type="expense"))
    alpha = ledger_service.create_party(PartyCreate(name="Alpha Vendor", role="vendor", is_active=True))
    beta = ledger_service.create_party(PartyCreate(name="Beta Vendor", role="vendor", is_active=True))
    entry = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 6, 2),
            summary="split bill",
            description=None,
            lines=[
                JournalLineIn(account_id=expense_a.id, party_id=alpha.id, amount=Decimal("10")),
                JournalLineIn(account_id=expense_b.id, party_id=beta.id, amount=Decimal("90")),
                JournalLineIn(account_id=cash.id, party_id=alpha.id, amount=Decimal("-100")),
            ],
        ),
    )
    att = ledger_service.scan_and_attach_journal_entry(
        entry.id,
        summary="Big line bill",
        external_reference=None,
        scan_backend=StubScanBackend(),
    )
    assert att.original_filename == "20260602.beta-vendor.big-line-bill.jpg"


def test_api_scan_attach_route(integration_db_url: str) -> None:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    svc = LedgerService(connection_factory=connection_factory)
    cash = svc.create_account(AccountCreate(name="Cash", type="asset"))
    expense = svc.create_account(AccountCreate(name="Expense", type="expense"))
    party = svc.create_party(PartyCreate(name="Vendor Co", role="vendor", is_active=True))
    entry = svc.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 6, 1),
            summary="scan api",
            description=None,
            lines=[
                JournalLineIn(account_id=expense.id, party_id=party.id, amount=Decimal("10")),
                JournalLineIn(account_id=cash.id, party_id=party.id, amount=Decimal("-10")),
            ],
        ),
    )
    app.dependency_overrides[get_ledger_service] = lambda: LedgerService(connection_factory=connection_factory)
    app.dependency_overrides[get_scan_backend_dep] = lambda: StubScanBackend()
    client = TestClient(app)
    try:
        r = client.post(
            f"/journal-entries/{entry.id}/attachments/scan",
            json={"summary": "June bill"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["mime_type"] == "image/jpeg"
        assert body["original_filename"] == "20260601.vendor-co.june-bill.jpg"
        flatbed = client.post("/scanner/flatbed")
        assert flatbed.status_code == 200
        assert flatbed.headers["content-type"].startswith("image/jpeg")
    finally:
        app.dependency_overrides.pop(get_ledger_service, None)
        app.dependency_overrides.pop(get_scan_backend_dep, None)


def _seed_expense_scan_chart(ledger_service: LedgerService) -> dict[str, int]:
    ap = ledger_service.create_account(AccountCreate(name="Accounts Payable", type="liability"))
    utilities = ledger_service.create_account(AccountCreate(name="Utilities", type="expense"))
    party = ledger_service.create_party(
        PartyCreate(name="Acme Plumbing", role="vendor", is_active=True),
    )
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(accounts_payable_account_id=ap.id),
    )
    return {"ap_id": ap.id, "utilities_id": utilities.id, "party_id": party.id}


def test_scan_create_accrual_plan_posts_je_and_obligation(ledger_service: LedgerService) -> None:
    ids = _seed_expense_scan_chart(ledger_service)
    result = ledger_service.scan_and_create_accrual_plan(
        AccrualPlanScanCreate(
            party_id=ids["party_id"],
            target_account_id=ids["utilities_id"],
            amount=Decimal("125.50"),
            bill_date=date(2026, 5, 30),
            due_date=date(2026, 6, 15),
            direction="expense",
            summary="Invoice May",
        ),
        scan_backend=StubScanBackend(),
    )
    assert result.plan.name == "20260530 Acme Plumbing Invoice May"
    assert result.plan.direction == "expense"
    assert result.plan.start_date == date(2026, 5, 30)
    assert result.plan.end_date == date(2026, 5, 30)
    assert result.obligation.due_date == date(2026, 6, 15)
    assert result.obligation.original_amount == Decimal("125.50")
    assert result.obligation.obligation_type == "payable"
    assert result.attachment.mime_type == "image/jpeg"
    assert result.attachment.original_filename == "20260530.acme-plumbing.invoice-may.jpg"
    detail = ledger_service.get_accrual_plan_detail(result.plan.id)
    assert len(detail.obligations) == 1
    assert detail.obligations[0].due_date == date(2026, 6, 15)
    entries = [
        ob
        for ob in ledger_service.list_open_obligations(ids["party_id"])
        if ob.accrual_plan_id == result.plan.id
    ]
    assert len(entries) == 1
    assert entries[0].source_entry_id == result.source_entry_id


def test_scan_create_accrual_plan_unique_name_suffix(ledger_service: LedgerService) -> None:
    ids = _seed_expense_scan_chart(ledger_service)
    first = ledger_service.scan_and_create_accrual_plan(
        AccrualPlanScanCreate(
            party_id=ids["party_id"],
            target_account_id=ids["utilities_id"],
            amount=Decimal("10"),
            bill_date=date(2026, 5, 30),
            summary="Invoice May",
        ),
        scan_backend=StubScanBackend(),
    )
    second = ledger_service.scan_and_create_accrual_plan(
        AccrualPlanScanCreate(
            party_id=ids["party_id"],
            target_account_id=ids["utilities_id"],
            amount=Decimal("20"),
            bill_date=date(2026, 5, 30),
            summary="Invoice May",
        ),
        scan_backend=StubScanBackend(),
    )
    assert first.plan.name == "20260530 Acme Plumbing Invoice May"
    assert second.plan.name == "20260530 Acme Plumbing Invoice May (2)"


def test_snapshot_exports_accrual_obligation_due_date(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    ids = _seed_expense_scan_chart(ledger_service)
    result = ledger_service.scan_and_create_accrual_plan(
        AccrualPlanScanCreate(
            party_id=ids["party_id"],
            target_account_id=ids["utilities_id"],
            amount=Decimal("42.00"),
            bill_date=date(2026, 7, 1),
            due_date=date(2026, 7, 20),
            summary="July bill",
        ),
        scan_backend=StubScanBackend(),
    )
    with connect(integration_db_url, row_factory=dict_row) as conn:
        archive = export_complete_snapshot(conn)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        envelope = json.loads(tf.extractfile("accrual_obligations.json").read().decode())
    obligations = envelope["rows"]
    row = next(r for r in obligations if int(r["id"]) == result.obligation.id)
    assert row["due_date"] == "2026-07-20"


def test_api_scan_accrual_plan_route(integration_db_url: str) -> None:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    svc = LedgerService(connection_factory=connection_factory)
    ids = _seed_expense_scan_chart(svc)
    app.dependency_overrides[get_ledger_service] = lambda: LedgerService(connection_factory=connection_factory)
    app.dependency_overrides[get_scan_backend_dep] = lambda: StubScanBackend()
    client = TestClient(app)
    try:
        r = client.post(
            "/accrual-plans/scan",
            json={
                "party_id": ids["party_id"],
                "target_account_id": ids["utilities_id"],
                "amount": "99.00",
                "bill_date": "2026-06-01",
                "summary": "June bill",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["plan"]["name"] == "20260601 Acme Plumbing June bill"
        assert body["obligation"]["due_date"] is None
        assert body["attachment"]["original_filename"] == "20260601.acme-plumbing.june-bill.jpg"
        assert body["source_entry_id"] > 0
    finally:
        app.dependency_overrides.pop(get_ledger_service, None)
        app.dependency_overrides.pop(get_scan_backend_dep, None)


def test_ledger_settings_scanner_fields_round_trip(ledger_service: LedgerService) -> None:
    prev = ledger_service.get_ledger_settings()
    try:
        out = ledger_service.update_ledger_settings(
            LedgerSettingsUpdate(
                scanner_device_uri="hpaio:/net/test?ip=1.2.3.4",
                max_scanned_pages=40,
                scan_dpi=200,
            ),
        )
        assert out.scanner_device_uri == "hpaio:/net/test?ip=1.2.3.4"
        assert out.max_scanned_pages == 40
        assert out.scan_dpi == 200
        assert out.scan_color_mode == "greyscale"
    finally:
        ledger_service.update_ledger_settings(
            LedgerSettingsUpdate(
                scanner_device_uri=prev.scanner_device_uri,
                max_scanned_pages=prev.max_scanned_pages,
                scan_dpi=prev.scan_dpi,
            ),
        )
