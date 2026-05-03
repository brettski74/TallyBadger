from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import os

import pytest
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.import_rules.cel_engine import evaluate_cel
from tallybadger.import_rules.cel_models import CelRule, CelRuleSet
from tallybadger.import_rules.errors import ImportRulesCelError
from tallybadger.ledger.models import (
    AccountCreate,
    AccountUpdate,
    AccrualPlanCreate,
    AccrualPlanUpdate,
    JournalEntryWrite,
    JournalLineIn,
    LedgerSettingsUpdate,
    PartyCreate,
    SettlementAllocationIn,
    SettlementWrite,
)
from tallybadger.ledger.service import (
    JOURNAL_LIST_SPLIT_LABEL,
    LedgerService,
    LedgerValidationError,
)

pytestmark = pytest.mark.integration


def _ensure_ledger_settings_row(integration_db_url: str) -> None:
    """TRUNCATE ... CASCADE may remove ledger_settings; settlement tests need row id=1."""
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ledger_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
                )


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
                    """
                    TRUNCATE TABLE import_templates, journal_lines, journal_entries,
                      accrual_plans, party_match_patterns, parties, accounts, cel_rule_sets
                    RESTART IDENTITY CASCADE
                    """
                )
    yield


@pytest.fixture
def ledger_service(integration_db_url: str) -> LedgerService:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    return LedgerService(connection_factory=connection_factory)


def test_create_entry_rolls_back_when_account_fk_invalid(
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))

    with pytest.raises(LedgerValidationError, match="unknown account"):
        ledger_service.create_entry(
            JournalEntryWrite(
                entry_date=date(2026, 4, 25),
                summary="bad fk create",
                description="bad fk create",
                lines=[
                    JournalLineIn(account_id=cash.id, amount=Decimal("10.00")),
                    JournalLineIn(account_id=999999, amount=Decimal("-10.00")),
                ],
            )
        )

    with connect(os.environ["TALLYBADGER_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT COUNT(*) AS count FROM journal_entries")
            assert cur.fetchone()["count"] == 0
            cur.execute("SELECT COUNT(*) AS count FROM journal_lines")
            assert cur.fetchone()["count"] == 0


def test_update_entry_rolls_back_to_existing_lines_on_fk_error(
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    expense = ledger_service.create_account(
        AccountCreate(name="Repairs Expense", type="expense")
    )

    created = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 4, 25),
            summary="initial",
            description="initial",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("120.00")),
                JournalLineIn(account_id=rent.id, amount=Decimal("-120.00")),
            ],
        )
    )

    with pytest.raises(LedgerValidationError, match="unknown account"):
        ledger_service.update_entry(
            created.id,
            JournalEntryWrite(
                entry_date=date(2026, 4, 26),
                summary="bad fk update",
                description="bad fk update",
                lines=[
                    JournalLineIn(account_id=expense.id, amount=Decimal("50.00")),
                    JournalLineIn(account_id=999999, amount=Decimal("-50.00")),
                ],
            ),
        )

    reloaded = ledger_service.get_entry(created.id)
    assert reloaded.description == "initial"
    assert [line.account_id for line in reloaded.lines] == [cash.id, rent.id]
    assert [line.amount for line in reloaded.lines] == [
        Decimal("120.00"),
        Decimal("-120.00"),
    ]


def test_deactivated_account_cannot_be_posted_to(ledger_service: LedgerService) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent", type="revenue"))
    ledger_service.update_account(revenue.id, AccountUpdate(is_active=False))

    with pytest.raises(LedgerValidationError, match="deactivated"):
        ledger_service.create_entry(
            JournalEntryWrite(
                entry_date=date(2026, 5, 1),
                summary="blocked by deactivated account",
                description="blocked by deactivated account",
                lines=[
                    JournalLineIn(account_id=cash.id, amount=Decimal("100.00")),
                    JournalLineIn(account_id=revenue.id, amount=Decimal("-100.00")),
                ],
            )
        )

    with connect(os.environ["TALLYBADGER_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT COUNT(*) AS count FROM journal_entries")
            assert cur.fetchone()["count"] == 0


def test_list_entries_and_account_lines_with_filters(
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent", type="revenue"))

    older = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 4, 1),
            summary="older",
            description="older",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("90.00")),
                JournalLineIn(account_id=revenue.id, amount=Decimal("-90.00")),
            ],
        )
    )
    newer = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 4, 20),
            summary="newer",
            description="newer",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("110.00")),
                JournalLineIn(account_id=revenue.id, amount=Decimal("-110.00")),
            ],
        )
    )

    entries = ledger_service.list_entries(
        from_date=date(2026, 4, 10),
        to_date=date(2026, 4, 30),
        limit=10,
        offset=0,
    )
    assert [entry.id for entry in entries] == [newer.id]
    assert entries[0].debit_side_label == "Cash"
    assert entries[0].credit_side_label == "Rent"
    assert entries[0].amount == Decimal("110.00")

    lines = ledger_service.list_account_lines(
        cash.id,
        from_date=date(2026, 4, 1),
        to_date=date(2026, 4, 30),
        limit=10,
        offset=0,
    )
    assert [line.entry_id for line in lines] == [newer.id, older.id]


def test_list_entries_shows_split_label_when_multiple_lines_on_one_side(
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    escrow = ledger_service.create_account(AccountCreate(name="Escrow", type="asset"))
    liability = ledger_service.create_account(AccountCreate(name="Due To", type="liability"))

    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 1),
            summary="two debits",
            description="two debits",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("30.00")),
                JournalLineIn(account_id=escrow.id, amount=Decimal("70.00")),
                JournalLineIn(account_id=liability.id, amount=Decimal("-100.00")),
            ],
        )
    )

    entries = ledger_service.list_entries(from_date=date(2026, 5, 1), limit=10, offset=0)
    assert len(entries) == 1
    assert entries[0].debit_side_label == JOURNAL_LIST_SPLIT_LABEL
    assert entries[0].credit_side_label == "Due To"
    assert entries[0].amount == Decimal("100.00")

    repairs = ledger_service.create_account(AccountCreate(name="Repairs", type="expense"))
    fees = ledger_service.create_account(AccountCreate(name="Fees", type="expense"))
    bank = ledger_service.create_account(AccountCreate(name="Bank", type="asset"))

    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 2),
            summary="two credits",
            description="two credits",
            lines=[
                JournalLineIn(account_id=bank.id, amount=Decimal("200.00")),
                JournalLineIn(account_id=repairs.id, amount=Decimal("-120.00")),
                JournalLineIn(account_id=fees.id, amount=Decimal("-80.00")),
            ],
        )
    )

    entries2 = ledger_service.list_entries(from_date=date(2026, 5, 1), limit=10, offset=0)
    assert len(entries2) == 2
    newer = next(e for e in entries2 if e.description == "two credits")
    assert newer.debit_side_label == "Bank"
    assert newer.credit_side_label == JOURNAL_LIST_SPLIT_LABEL
    assert newer.amount == Decimal("200.00")


def test_get_entry_includes_account_name_on_each_line(ledger_service: LedgerService) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent", type="revenue"))
    entry = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 6, 1),
            summary="with names",
            description="with names",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("15.00")),
                JournalLineIn(account_id=revenue.id, amount=Decimal("-15.00")),
            ],
        )
    )
    loaded = ledger_service.get_entry(entry.id)
    assert [ln.account_name for ln in loaded.lines] == ["Cash", "Rent"]


def test_accrual_plan_create_and_guarded_update(ledger_service: LedgerService) -> None:
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    party = ledger_service.create_party(
        PartyCreate(name="Acme Yard Maintenance", role="customer", is_active=True)
    )
    plan = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Rent Plan 2026",
            direction="revenue",
            party_id=party.id,
            target_account_id=rent.id,
            bridge_account_id=ar.id,
            frequency="monthly_day",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 28),
            amount=Decimal("1200.00"),
            summary_template="{plan} {month}",
            day_of_month=1,
        )
    )
    assert plan.name == "Rent Plan 2026"

    entries = ledger_service.list_entries(from_date=date(2026, 1, 1), to_date=date(2026, 2, 28))
    assert len(entries) == 2
    assert all(entry.summary.startswith("Rent Plan 2026") for entry in entries)

    with pytest.raises(LedgerValidationError, match="force_override=true"):
        ledger_service.update_accrual_plan(
            plan.id,
            AccrualPlanUpdate(name="Revised rent plan"),
        )


def test_early_receipt_settlement_reclasses_accrual_ar_to_unearned(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    ur = ledger_service.create_account(AccountCreate(name="Unearned Revenue", type="liability"))

    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            accounts_receivable_account_id=ar.id,
            unearned_revenue_account_id=ur.id,
        )
    )

    party = ledger_service.create_party(
        PartyCreate(name="Acme Yard Maintenance", role="customer", is_active=True)
    )

    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Rent 2026-07",
            direction="revenue",
            party_id=party.id,
            target_account_id=rent.id,
            bridge_account_id=ar.id,
            frequency="monthly_day",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            amount=Decimal("1500.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )

    open_obs = ledger_service.list_open_obligations(party.id)
    assert len(open_obs) == 1
    ob = open_obs[0]
    assert ob.source_line_id is not None
    accrual_entry_id = ob.source_entry_id
    assert accrual_entry_id is not None

    result = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party.id,
            settlement_type="receipt",
            event_date=date(2026, 6, 26),
            amount=Decimal("1500.00"),
            cash_account_id=cash.id,
            allocations=[
                SettlementAllocationIn(obligation_id=ob.id, amount=Decimal("1500.00")),
            ],
            note="early rent",
        )
    )

    settle_entry = ledger_service.get_entry(result.entry_id)
    assert settle_entry.summary == "Settlement Rent 2026-07"

    accrual_entry = ledger_service.get_entry(accrual_entry_id)
    account_ids = {line.account_id for line in accrual_entry.lines}
    assert ar.id not in account_ids
    assert ur.id in account_ids
    assert rent.id in account_ids


def test_partial_early_receipt_splits_accrual_bridge_between_ur_and_ar(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    ur = ledger_service.create_account(AccountCreate(name="Unearned Revenue", type="liability"))

    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            accounts_receivable_account_id=ar.id,
            unearned_revenue_account_id=ur.id,
        )
    )

    party = ledger_service.create_party(
        PartyCreate(name="Acme Yard Maintenance", role="customer", is_active=True)
    )

    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Rent increase month",
            direction="revenue",
            party_id=party.id,
            target_account_id=rent.id,
            bridge_account_id=ar.id,
            frequency="monthly_day",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            amount=Decimal("1500.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )

    open_obs = ledger_service.list_open_obligations(party.id)
    ob = open_obs[0]
    accrual_entry_id = ob.source_entry_id
    assert accrual_entry_id is not None

    result = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party.id,
            settlement_type="receipt",
            event_date=date(2026, 6, 26),
            amount=Decimal("500.00"),
            cash_account_id=cash.id,
            allocations=[
                SettlementAllocationIn(obligation_id=ob.id, amount=Decimal("500.00")),
            ],
            note="old rent amount before increase notice",
        )
    )

    assert ledger_service.get_entry(result.entry_id).summary == "Settlement Rent increase month"

    accrual_entry = ledger_service.get_entry(accrual_entry_id)
    assert len(accrual_entry.lines) == 3
    by_account = {line.account_id: line.amount for line in accrual_entry.lines}
    assert by_account[ur.id] == Decimal("500.00")
    assert by_account[ar.id] == Decimal("1000.00")
    assert by_account[rent.id] == Decimal("-1500.00")

    still_open = ledger_service.list_open_obligations(party.id)
    assert len(still_open) == 1
    assert still_open[0].open_amount == Decimal("1000.00")


def _journal_entry_count(integration_db_url: str) -> int:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM journal_entries")
            return int(cur.fetchone()["c"])


def test_same_day_full_receipt_collapses_into_accrual_entry(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    ur = ledger_service.create_account(AccountCreate(name="Unearned Revenue", type="liability"))

    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            accounts_receivable_account_id=ar.id,
            unearned_revenue_account_id=ur.id,
        )
    )

    party = ledger_service.create_party(
        PartyCreate(name="Acme Yard Maintenance", role="customer", is_active=True)
    )

    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="July rent",
            direction="revenue",
            party_id=party.id,
            target_account_id=rent.id,
            bridge_account_id=ar.id,
            frequency="monthly_day",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            amount=Decimal("1500.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )

    assert _journal_entry_count(integration_db_url) == 1
    ob = ledger_service.list_open_obligations(party.id)[0]
    accrual_entry_id = ob.source_entry_id
    assert accrual_entry_id is not None

    result = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party.id,
            settlement_type="receipt",
            event_date=date(2026, 7, 1),
            amount=Decimal("1500.00"),
            cash_account_id=cash.id,
            allocations=[
                SettlementAllocationIn(obligation_id=ob.id, amount=Decimal("1500.00")),
            ],
            note=None,
        )
    )

    assert _journal_entry_count(integration_db_url) == 1
    assert result.entry_id == accrual_entry_id

    entry = ledger_service.get_entry(accrual_entry_id)
    assert not any(line.account_id == ar.id for line in entry.lines)
    assert sum(line.amount for line in entry.lines if line.account_id == cash.id) == Decimal("1500.00")
    assert sum(line.amount for line in entry.lines if line.account_id == rent.id) == Decimal("-1500.00")


def test_same_day_partial_receipt_adds_cash_on_accrual_entry(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    ur = ledger_service.create_account(AccountCreate(name="Unearned Revenue", type="liability"))

    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            accounts_receivable_account_id=ar.id,
            unearned_revenue_account_id=ur.id,
        )
    )

    party = ledger_service.create_party(
        PartyCreate(name="Acme Yard Maintenance", role="customer", is_active=True)
    )

    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="July rent partial",
            direction="revenue",
            party_id=party.id,
            target_account_id=rent.id,
            bridge_account_id=ar.id,
            frequency="monthly_day",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            amount=Decimal("1500.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )

    ob = ledger_service.list_open_obligations(party.id)[0]
    accrual_entry_id = ob.source_entry_id
    assert accrual_entry_id is not None

    ledger_service.record_settlement(
        SettlementWrite(
            party_id=party.id,
            settlement_type="receipt",
            event_date=date(2026, 7, 1),
            amount=Decimal("500.00"),
            cash_account_id=cash.id,
            allocations=[
                SettlementAllocationIn(obligation_id=ob.id, amount=Decimal("500.00")),
            ],
            note=None,
        )
    )

    assert _journal_entry_count(integration_db_url) == 1
    entry = ledger_service.get_entry(accrual_entry_id)
    by_account = {line.account_id: line.amount for line in entry.lines}
    assert by_account[ar.id] == Decimal("1000.00")
    assert by_account[cash.id] == Decimal("500.00")
    assert by_account[rent.id] == Decimal("-1500.00")


def test_same_day_overpayment_adds_cash_and_unearned_on_accrual_entry(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    ur = ledger_service.create_account(AccountCreate(name="Unearned Revenue", type="liability"))

    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            accounts_receivable_account_id=ar.id,
            unearned_revenue_account_id=ur.id,
        )
    )

    party = ledger_service.create_party(
        PartyCreate(name="Acme Yard Maintenance", role="customer", is_active=True)
    )

    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="July rent over",
            direction="revenue",
            party_id=party.id,
            target_account_id=rent.id,
            bridge_account_id=ar.id,
            frequency="monthly_day",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            amount=Decimal("1500.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )

    ob = ledger_service.list_open_obligations(party.id)[0]
    accrual_entry_id = ob.source_entry_id
    assert accrual_entry_id is not None

    ledger_service.record_settlement(
        SettlementWrite(
            party_id=party.id,
            settlement_type="receipt",
            event_date=date(2026, 7, 1),
            amount=Decimal("2000.00"),
            cash_account_id=cash.id,
            allocations=[
                SettlementAllocationIn(obligation_id=ob.id, amount=Decimal("1500.00")),
            ],
            note=None,
        )
    )

    assert _journal_entry_count(integration_db_url) == 1
    entry = ledger_service.get_entry(accrual_entry_id)
    assert sum(line.amount for line in entry.lines if line.account_id == cash.id) == Decimal("2000.00")
    assert sum(line.amount for line in entry.lines if line.account_id == ur.id) == Decimal("-500.00")
    assert sum(line.amount for line in entry.lines if line.account_id == rent.id) == Decimal("-1500.00")
    assert not any(line.account_id == ar.id for line in entry.lines)


def test_party_default_revenue_and_cel_party_and_revenue_account(ledger_service: LedgerService) -> None:
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    ledger_service.create_party(
        PartyCreate(
            name="Bob Tenant",
            role="customer",
            is_active=True,
            match_patterns=[r"BANK.*BOB"],
            default_revenue_account_id=rent.id,
        ),
    )
    parties = ledger_service.list_parties()
    bob = next(p for p in parties if p.name == "Bob Tenant")
    assert bob.match_patterns == [r"BANK.*BOB"]
    assert bob.default_revenue_account_name == "Rent Revenue"

    rs = CelRuleSet(
        rules=[
            CelRule(
                sort_order=10,
                expression=(
                    '{"set": {"party": party(attributes["desc"]), '
                    '"acct": revenue_account("Bob Tenant")}}'
                ),
            ),
        ],
    )
    out = evaluate_cel(rs, {"desc": "BANK PAY BOB"}, parties=parties)
    assert out.attributes["party"] == "Bob Tenant"
    assert out.attributes["acct"] == "Rent Revenue"


def test_cel_party_returns_null_when_no_pattern_match(ledger_service: LedgerService) -> None:
    ledger_service.create_party(
        PartyCreate(name="Only", role="customer", is_active=True, match_patterns=[r"^X$"]),
    )
    rs = CelRuleSet(rules=[CelRule(expression='{"set": {"p": party(attributes["desc"])}}')])
    out = evaluate_cel(rs, {"desc": "no way"}, parties=ledger_service.list_parties())
    assert out.attributes.get("p") is None


def test_party_default_equity_allowed_for_revenue_slot_and_cel(
    ledger_service: LedgerService,
) -> None:
    """Owner capital (equity) is allowed as the party's default for revenue_account() CEL."""
    owner_eq = ledger_service.create_account(AccountCreate(name="Owner Capital – Building A", type="equity"))
    ledger_service.create_party(
        PartyCreate(
            name="Building A LLC",
            role="customer",
            is_active=True,
            match_patterns=[],
            default_revenue_account_id=owner_eq.id,
        ),
    )
    parties = ledger_service.list_parties()
    p = next(x for x in parties if x.name == "Building A LLC")
    assert p.default_revenue_account_name == "Owner Capital – Building A"

    rs = CelRuleSet(
        rules=[CelRule(expression='{"set":{"cap": revenue_account("Building A LLC")}}')],
    )
    out = evaluate_cel(rs, {}, parties=parties)
    assert out.attributes["cap"] == "Owner Capital – Building A"


def test_cel_party_ambiguous_match_raises(ledger_service: LedgerService) -> None:
    ledger_service.create_party(
        PartyCreate(name="Alpha", role="customer", is_active=True, match_patterns=[r"REF"]),
    )
    ledger_service.create_party(
        PartyCreate(name="Beta", role="customer", is_active=True, match_patterns=[r"REF"]),
    )
    rs = CelRuleSet(rules=[CelRule(expression='{"set": {"p": party(attributes["desc"])}}')])
    with pytest.raises(ImportRulesCelError, match="multiple parties"):
        evaluate_cel(rs, {"desc": "REF 123"}, parties=ledger_service.list_parties())
