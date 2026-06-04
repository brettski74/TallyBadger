from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import os

import pytest
from fastapi.testclient import TestClient
from psycopg import connect, errors as pg_errors
from psycopg.rows import dict_row

from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.main import app
from tallybadger.import_rules.cel_engine import evaluate_cel
from tallybadger.import_rules.cel_models import CelRule, CelRuleSet
from tallybadger.import_rules.errors import ImportRulesCelError
from tallybadger.ledger.models import (
    AccountCreate,
    AccountUpdate,
    AccrualPlanCreate,
    ChequeCreate,
    JournalEntryWrite,
    JournalLineIn,
    LedgerSettingsUpdate,
    PartyCreate,
    PartyUpdate,
    SettlementAllocationIn,
    SettlementWrite,
)
from tallybadger.ledger.service import (
    JOURNAL_LIST_SPLIT_LABEL,
    LedgerConflictError,
    LedgerNotFoundError,
    LedgerService,
    LedgerSettingsValidationError,
    LedgerValidationError,
)

pytestmark = pytest.mark.integration

_MINIMAL_PDF = b"%PDF-1.1\n1 0 obj<<>>endobj trailer<<>>\n%%EOF"


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
                    TRUNCATE TABLE journal_entry_filter_presets, import_templates,
                      journal_lines, journal_entry_attachments,
                      attachments, journal_entries, import_batches,
                      accrual_plans, party_match_patterns, parties, accounts, cel_rule_sets
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


def test_account_type_change_allowed_when_unreferenced(ledger_service: LedgerService) -> None:
    acct = ledger_service.create_account(AccountCreate(name="Lonely Expense", type="expense"))
    out = ledger_service.update_account(acct.id, AccountUpdate(type="liability"))
    assert out.type == "liability"
    assert out.name == "Lonely Expense"


def test_account_type_change_blocked_by_journal_line(ledger_service: LedgerService) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent", type="revenue"))
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 2),
            summary="rent",
            description="rent",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("50.00")),
                JournalLineIn(account_id=rent.id, amount=Decimal("-50.00")),
            ],
        )
    )
    with pytest.raises(LedgerConflictError, match="journal lines"):
        ledger_service.update_account(rent.id, AccountUpdate(type="expense"))


def test_account_type_change_blocked_by_ledger_settings(ledger_service: LedgerService) -> None:
    ar = ledger_service.create_account(AccountCreate(name="Tenant AR", type="asset"))
    ledger_service.update_ledger_settings(LedgerSettingsUpdate(accounts_receivable_account_id=ar.id))
    with pytest.raises(LedgerConflictError, match="ledger settings"):
        ledger_service.update_account(ar.id, AccountUpdate(type="liability"))


def test_account_type_change_blocked_by_cheque(ledger_service: LedgerService) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Bank", type="asset"))
    expense = ledger_service.create_account(AccountCreate(name="Gardening", type="expense"))
    ledger_service.create_cheque(
        ChequeCreate(
            credit_account_id=cash.id,
            debit_account_id=expense.id,
            summary="Lawn mower",
            cheque_number=101,
            issue_date=date(2026, 5, 3),
            amount=Decimal("80.00"),
        )
    )
    with pytest.raises(LedgerConflictError, match="cheque"):
        ledger_service.update_account(expense.id, AccountUpdate(type="liability"))


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


def test_list_entries_filters_by_new_dimensions(ledger_service: LedgerService) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    expense = ledger_service.create_account(AccountCreate(name="Repairs Expense", type="expense"))
    payable = ledger_service.create_account(AccountCreate(name="Trade Payable", type="liability"))
    party_a = ledger_service.create_party(PartyCreate(name="Alpha Tenant", role="customer"))
    party_b = ledger_service.create_party(PartyCreate(name="Bravo Vendor", role="vendor"))

    small = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 6, 1),
            summary="alpha rent",
            description="alpha rent",
            lines=[
                JournalLineIn(account_id=cash.id, party_id=party_a.id, amount=Decimal("50.00")),
                JournalLineIn(account_id=revenue.id, party_id=party_a.id, amount=Decimal("-50.00")),
            ],
        )
    )
    medium = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 6, 2),
            summary="bravo expense",
            description="bravo expense",
            lines=[
                JournalLineIn(account_id=expense.id, party_id=party_b.id, amount=Decimal("150.00")),
                JournalLineIn(account_id=payable.id, party_id=party_b.id, amount=Decimal("-150.00")),
            ],
        )
    )
    large = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 6, 3),
            summary="alpha big rent",
            description="alpha big rent",
            lines=[
                JournalLineIn(account_id=cash.id, party_id=party_a.id, amount=Decimal("500.00")),
                JournalLineIn(account_id=revenue.id, party_id=party_a.id, amount=Decimal("-500.00")),
            ],
        )
    )

    by_account = ledger_service.list_entries(account_ids=[expense.id], limit=10, offset=0)
    assert [e.id for e in by_account] == [medium.id]

    by_party = ledger_service.list_entries(party_ids=[party_a.id], limit=10, offset=0)
    assert sorted(e.id for e in by_party) == sorted([small.id, large.id])

    in_band = ledger_service.list_entries(amount_low=100, amount_high=200, limit=10, offset=0)
    assert [e.id for e in in_band] == [medium.id]

    no_cheque = ledger_service.list_entries(cheque_association="with_cheque", limit=10, offset=0)
    assert no_cheque == []

    has_no_cheque = ledger_service.list_entries(
        cheque_association="without_cheque", limit=10, offset=0
    )
    assert sorted(e.id for e in has_no_cheque) == sorted([small.id, medium.id, large.id])

    with pytest.raises(LedgerValidationError, match="amount_low"):
        ledger_service.list_entries(amount_low=300, amount_high=100, limit=10, offset=0)


def test_list_entries_amount_band_filters_by_debit_magnitude(
    ledger_service: LedgerService,
) -> None:
    """Balanced entries are filtered by list amount (debit-side magnitude when debits exist)."""

    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent", type="revenue"))
    expense = ledger_service.create_account(AccountCreate(name="Misc Expense", type="expense"))

    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 7, 1),
            summary="large",
            description="large",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("100.00")),
                JournalLineIn(account_id=rent.id, amount=Decimal("-100.00")),
            ],
        )
    )
    in_band = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 7, 2),
            summary="mid",
            description="mid",
            lines=[
                JournalLineIn(account_id=expense.id, amount=Decimal("25.00")),
                JournalLineIn(account_id=cash.id, amount=Decimal("-25.00")),
            ],
        )
    )

    matches = ledger_service.list_entries(amount_low=10, amount_high=50, limit=10, offset=0)
    assert [e.id for e in matches] == [in_band.id]


def test_db_rejects_journal_entry_header_without_lines(integration_db_url: str) -> None:
    # Deferrable balance triggers run at the outer transaction COMMIT; keep
    # pytest.raises around the whole connection context (not only conn.transaction()).
    with pytest.raises(pg_errors.RaiseException, match="journal entry requires at least two lines"):
        with connect(integration_db_url, row_factory=dict_row) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO journal_entries (entry_date, summary, description)
                        VALUES (%s, %s, %s)
                        """,
                        (date(2026, 8, 1), "orphan header", "orphan header"),
                    )


def test_db_rejects_journal_entry_with_one_line(integration_db_url: str) -> None:
    conn = connect(integration_db_url, row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO accounts (name, type) VALUES ('DB Cash', 'asset') RETURNING id"
            )
            cash_id = int(cur.fetchone()["id"])
        conn.commit()
        with pytest.raises(pg_errors.RaiseException, match="journal entry requires at least two lines"):
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO journal_entries (entry_date, summary, description)
                        VALUES (%s, %s, %s) RETURNING id
                        """,
                        (date(2026, 8, 2), "one line", "one line"),
                    )
                    entry_id = int(cur.fetchone()["id"])
                    cur.execute(
                        """
                        INSERT INTO journal_lines (entry_id, account_id, amount)
                        VALUES (%s, %s, %s)
                        """,
                        (entry_id, cash_id, Decimal("10.00")),
                    )
    finally:
        conn.close()


def test_db_rejects_unbalanced_journal_entry_at_commit(integration_db_url: str) -> None:
    conn = connect(integration_db_url, row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO accounts (name, type) VALUES ('DB Cash 2', 'asset') RETURNING id"
            )
            cash_id = int(cur.fetchone()["id"])
            cur.execute(
                "INSERT INTO accounts (name, type) VALUES ('DB Rent', 'revenue') RETURNING id"
            )
            rent_id = int(cur.fetchone()["id"])
        conn.commit()
        with pytest.raises(pg_errors.RaiseException, match="journal entry is not balanced"):
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO journal_entries (entry_date, summary, description)
                        VALUES (%s, %s, %s) RETURNING id
                        """,
                        (date(2026, 8, 3), "unbalanced", "unbalanced"),
                    )
                    entry_id = int(cur.fetchone()["id"])
                    cur.execute(
                        """
                        INSERT INTO journal_lines (entry_id, account_id, amount)
                        VALUES (%s, %s, %s), (%s, %s, %s)
                        """,
                        (
                            entry_id,
                            cash_id,
                            Decimal("100.00"),
                            entry_id,
                            rent_id,
                            Decimal("-50.00"),
                        ),
                    )
    finally:
        conn.close()


def test_db_accepts_balanced_journal_entry_via_raw_sql(integration_db_url: str) -> None:
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO accounts (name, type) VALUES ('DB Cash 3', 'asset') RETURNING id"
            )
            cash_id = int(cur.fetchone()["id"])
            cur.execute(
                "INSERT INTO accounts (name, type) VALUES ('DB Rent 2', 'revenue') RETURNING id"
            )
            rent_id = int(cur.fetchone()["id"])
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO journal_entries (entry_date, summary, description)
                    VALUES (%s, %s, %s) RETURNING id
                    """,
                    (date(2026, 8, 4), "balanced raw", "balanced raw"),
                )
                entry_id = int(cur.fetchone()["id"])
                cur.execute(
                    """
                    INSERT INTO journal_lines (entry_id, account_id, amount)
                    VALUES (%s, %s, %s), (%s, %s, %s)
                    """,
                    (
                        entry_id,
                        cash_id,
                        Decimal("40.00"),
                        entry_id,
                        rent_id,
                        Decimal("-40.00"),
                    ),
                )
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*)::int AS c FROM journal_lines WHERE entry_id = %s",
                (entry_id,),
            )
            assert int(cur.fetchone()["c"]) == 2


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


def test_accrual_plan_create_and_update_regenerates_entries(ledger_service: LedgerService) -> None:
    ar = ledger_service.create_account(AccountCreate(name="Accounts Receivable", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent Revenue", type="revenue"))
    party = ledger_service.create_party(
        PartyCreate(name="Acme Yard Maintenance", role="customer", is_active=True)
    )
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(accounts_receivable_account_id=ar.id),
    )
    plan = ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Rent Plan 2026",
            direction="revenue",
            party_id=party.id,
            target_account_id=rent.id,
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

    updated = ledger_service.update_accrual_plan(
        plan.id,
        AccrualPlanCreate(
            name="Revised rent plan",
            direction="revenue",
            party_id=party.id,
            target_account_id=rent.id,
            frequency="monthly_day",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            amount=Decimal("1500.00"),
            summary_template="{plan} {month}",
            day_of_month=1,
        ),
    )
    assert updated.name == "Revised rent plan"
    assert updated.end_date == date(2026, 3, 31)

    entries_after = ledger_service.list_entries(
        from_date=date(2026, 1, 1), to_date=date(2026, 3, 31)
    )
    plan_entries = [e for e in entries_after if e.summary.startswith("Revised rent plan")]
    assert len(plan_entries) == 3


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
    assert len(result.allocation_ids) == 1

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


def test_early_payment_settlement_reclasses_accrual_ap_to_prepaid(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ap = ledger_service.create_account(AccountCreate(name="Accounts Payable", type="liability"))
    repairs = ledger_service.create_account(AccountCreate(name="Repairs Expense", type="expense"))
    prepaid = ledger_service.create_account(AccountCreate(name="Prepaid Expenses", type="asset"))

    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            accounts_payable_account_id=ap.id,
            prepaid_expenses_account_id=prepaid.id,
        )
    )

    party = ledger_service.create_party(
        PartyCreate(name="Vendor Co", role="vendor", is_active=True)
    )

    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Repair bill Aug",
            direction="expense",
            party_id=party.id,
            target_account_id=repairs.id,
            frequency="monthly_day",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            amount=Decimal("800.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )

    ob = ledger_service.list_open_obligations(party.id)[0]
    accrual_entry_id = ob.source_entry_id
    assert accrual_entry_id is not None

    result = ledger_service.record_settlement(
        SettlementWrite(
            party_id=party.id,
            settlement_type="payment",
            event_date=date(2026, 7, 26),
            amount=Decimal("800.00"),
            cash_account_id=cash.id,
            allocations=[
                SettlementAllocationIn(obligation_id=ob.id, amount=Decimal("800.00")),
            ],
            note="early repair payment",
        )
    )

    assert ledger_service.get_entry(result.entry_id).summary == "Settlement Repair bill Aug"

    accrual_entry = ledger_service.get_entry(accrual_entry_id)
    account_ids = {line.account_id for line in accrual_entry.lines}
    assert ap.id not in account_ids
    assert prepaid.id in account_ids
    assert repairs.id in account_ids


def test_partial_early_payment_splits_accrual_bridge_between_prepaid_and_ap(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ap = ledger_service.create_account(AccountCreate(name="Accounts Payable", type="liability"))
    repairs = ledger_service.create_account(AccountCreate(name="Repairs Expense", type="expense"))
    prepaid = ledger_service.create_account(AccountCreate(name="Prepaid Expenses", type="asset"))

    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            accounts_payable_account_id=ap.id,
            prepaid_expenses_account_id=prepaid.id,
        )
    )

    party = ledger_service.create_party(
        PartyCreate(name="Vendor Co", role="vendor", is_active=True)
    )

    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Repair bill partial",
            direction="expense",
            party_id=party.id,
            target_account_id=repairs.id,
            frequency="monthly_day",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            amount=Decimal("800.00"),
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
            settlement_type="payment",
            event_date=date(2026, 7, 26),
            amount=Decimal("300.00"),
            cash_account_id=cash.id,
            allocations=[
                SettlementAllocationIn(obligation_id=ob.id, amount=Decimal("300.00")),
            ],
            note="partial early payment",
        )
    )

    accrual_entry = ledger_service.get_entry(accrual_entry_id)
    assert len(accrual_entry.lines) == 3
    by_account = {line.account_id: line.amount for line in accrual_entry.lines}
    assert by_account[prepaid.id] == Decimal("-300.00")
    assert by_account[ap.id] == Decimal("-500.00")
    assert by_account[repairs.id] == Decimal("800.00")
    assert sum(line.amount for line in accrual_entry.lines) == Decimal("0")

    still_open = ledger_service.list_open_obligations(party.id)
    assert len(still_open) == 1
    assert still_open[0].open_amount == Decimal("500.00")


def test_partial_early_payment_on_future_accrual_keeps_entry_balanced(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    """FIFO payment: due slice on Dec accrual, early slice reclassifies Jan accrual with signed prepaid."""
    _ensure_ledger_settings_row(integration_db_url)
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ap = ledger_service.create_account(AccountCreate(name="Accounts Payable", type="liability"))
    maintenance = ledger_service.create_account(
        AccountCreate(name="Maintenance and Repairs", type="expense")
    )
    prepaid = ledger_service.create_account(AccountCreate(name="Prepaid Expenses", type="asset"))

    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            accounts_payable_account_id=ap.id,
            prepaid_expenses_account_id=prepaid.id,
        )
    )

    party = ledger_service.create_party(
        PartyCreate(name="Mower Man Yard Maintenance", role="vendor", is_active=True)
    )

    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Mower monthly",
            direction="expense",
            party_id=party.id,
            target_account_id=maintenance.id,
            frequency="monthly_day",
            start_date=date(2025, 12, 1),
            end_date=date(2026, 1, 31),
            amount=Decimal("904.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )

    open_obs = sorted(
        ledger_service.list_open_obligations(party.id),
        key=lambda ob: ob.source_entry_date or date.min,
    )
    assert len(open_obs) == 2
    dec_ob, jan_ob = open_obs[0], open_obs[1]
    assert dec_ob.source_entry_date == date(2025, 12, 1)
    assert jan_ob.source_entry_date == date(2026, 1, 1)
    assert jan_ob.source_entry_id is not None

    ledger_service.record_settlement(
        SettlementWrite(
            party_id=party.id,
            settlement_type="payment",
            event_date=date(2025, 12, 6),
            amount=Decimal("1000.00"),
            cash_account_id=cash.id,
            allocations=[
                SettlementAllocationIn(obligation_id=dec_ob.id, amount=Decimal("904.00")),
                SettlementAllocationIn(obligation_id=jan_ob.id, amount=Decimal("96.00")),
            ],
            note="pay Dec due plus early slice on Jan",
        )
    )

    jan_accrual = ledger_service.get_entry(jan_ob.source_entry_id)
    by_account = {line.account_id: line.amount for line in jan_accrual.lines}
    assert by_account[maintenance.id] == Decimal("904.00")
    assert by_account[prepaid.id] == Decimal("-96.00")
    assert by_account[ap.id] == Decimal("-808.00")
    assert sum(line.amount for line in jan_accrual.lines) == Decimal("0")


def test_same_day_full_payment_collapses_into_accrual_entry(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ap = ledger_service.create_account(AccountCreate(name="Accounts Payable", type="liability"))
    repairs = ledger_service.create_account(AccountCreate(name="Repairs Expense", type="expense"))
    prepaid = ledger_service.create_account(AccountCreate(name="Prepaid Expenses", type="asset"))

    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            accounts_payable_account_id=ap.id,
            prepaid_expenses_account_id=prepaid.id,
        )
    )

    party = ledger_service.create_party(
        PartyCreate(name="Vendor Co", role="vendor", is_active=True)
    )

    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="August repair",
            direction="expense",
            party_id=party.id,
            target_account_id=repairs.id,
            frequency="monthly_day",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            amount=Decimal("800.00"),
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
            settlement_type="payment",
            event_date=date(2026, 8, 1),
            amount=Decimal("800.00"),
            cash_account_id=cash.id,
            allocations=[
                SettlementAllocationIn(obligation_id=ob.id, amount=Decimal("800.00")),
            ],
            note=None,
        )
    )

    assert _journal_entry_count(integration_db_url) == 1
    assert result.entry_id == accrual_entry_id

    entry = ledger_service.get_entry(accrual_entry_id)
    assert not any(line.account_id == ap.id for line in entry.lines)
    assert sum(line.amount for line in entry.lines if line.account_id == cash.id) == Decimal("-800.00")
    assert sum(line.amount for line in entry.lines if line.account_id == repairs.id) == Decimal("800.00")


def test_same_day_overpayment_adds_cash_and_prepaid_on_accrual_entry(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ap = ledger_service.create_account(AccountCreate(name="Accounts Payable", type="liability"))
    repairs = ledger_service.create_account(AccountCreate(name="Repairs Expense", type="expense"))
    prepaid = ledger_service.create_account(AccountCreate(name="Prepaid Expenses", type="asset"))

    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            accounts_payable_account_id=ap.id,
            prepaid_expenses_account_id=prepaid.id,
        )
    )

    party = ledger_service.create_party(
        PartyCreate(name="Vendor Co", role="vendor", is_active=True)
    )

    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="August repair overpay",
            direction="expense",
            party_id=party.id,
            target_account_id=repairs.id,
            frequency="monthly_day",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            amount=Decimal("800.00"),
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
            settlement_type="payment",
            event_date=date(2026, 8, 1),
            amount=Decimal("1000.00"),
            cash_account_id=cash.id,
            allocations=[
                SettlementAllocationIn(obligation_id=ob.id, amount=Decimal("800.00")),
            ],
            note=None,
        )
    )

    assert _journal_entry_count(integration_db_url) == 1
    entry = ledger_service.get_entry(accrual_entry_id)
    assert sum(line.amount for line in entry.lines if line.account_id == cash.id) == Decimal("-1000.00")
    assert sum(line.amount for line in entry.lines if line.account_id == prepaid.id) == Decimal("200.00")
    assert sum(line.amount for line in entry.lines if line.account_id == repairs.id) == Decimal("800.00")
    assert not any(line.account_id == ap.id for line in entry.lines)


def test_early_payment_without_prepaid_account_rejected(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    _ensure_ledger_settings_row(integration_db_url)
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    ap = ledger_service.create_account(AccountCreate(name="Accounts Payable", type="liability"))
    repairs = ledger_service.create_account(AccountCreate(name="Repairs Expense", type="expense"))

    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(accounts_payable_account_id=ap.id)
    )

    party = ledger_service.create_party(
        PartyCreate(name="Vendor Co", role="vendor", is_active=True)
    )

    ledger_service.create_accrual_plan(
        AccrualPlanCreate(
            name="Future repair",
            direction="expense",
            party_id=party.id,
            target_account_id=repairs.id,
            frequency="monthly_day",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            amount=Decimal("800.00"),
            summary_template="{plan}",
            day_of_month=1,
        )
    )

    ob = ledger_service.list_open_obligations(party.id)[0]

    with pytest.raises(LedgerValidationError, match="prepaid expenses"):
        ledger_service.record_settlement(
            SettlementWrite(
                party_id=party.id,
                settlement_type="payment",
                event_date=date(2026, 7, 26),
                amount=Decimal("800.00"),
                cash_account_id=cash.id,
                allocations=[
                    SettlementAllocationIn(obligation_id=ob.id, amount=Decimal("800.00")),
                ],
            )
        )


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


def test_journal_entry_attachment_round_trip(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    entry = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 5),
            summary="with attachment",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("1")),
                JournalLineIn(account_id=cash.id, amount=Decimal("-1")),
            ],
        ),
    )
    att = ledger_service.add_journal_entry_attachment(
        entry.id,
        file_bytes=_MINIMAL_PDF,
        upload_filename="invoices/March.pdf",
        summary="March bill",
        external_reference="INV-9",
    )
    assert att.mime_type == "application/pdf"
    assert att.original_filename == "March.pdf"
    assert att.summary == "March bill"
    listed = ledger_service.list_journal_entry_attachments(entry.id)
    assert len(listed) == 1
    blob, mime, name = ledger_service.get_journal_entry_attachment_download(entry.id, att.id)
    assert blob == _MINIMAL_PDF
    assert mime == "application/pdf"
    assert name == "March.pdf"
    ledger_service.unlink_journal_entry_attachment(entry.id, att.id)
    assert ledger_service.list_journal_entry_attachments(entry.id) == []
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM attachments")
            assert int(cur.fetchone()["c"]) == 0


def test_attachment_oversize_rejected_at_http(ledger_service: LedgerService) -> None:
    try:
        ledger_service.update_ledger_settings(LedgerSettingsUpdate(max_attachment_upload_bytes=10))
        cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
        entry = ledger_service.create_entry(
            JournalEntryWrite(
                entry_date=date(2026, 5, 5),
                summary="entry",
                description=None,
                lines=[
                    JournalLineIn(account_id=cash.id, amount=Decimal("1")),
                    JournalLineIn(account_id=cash.id, amount=Decimal("-1")),
                ],
            ),
        )
        client = TestClient(app)
        response = client.post(
            f"/journal-entries/{entry.id}/attachments",
            files={"file": ("big.bin", b"x" * 20, "application/octet-stream")},
            data={"summary": "too big"},
        )
        assert response.status_code == 413
        assert "10" in response.json()["detail"]
    finally:
        ledger_service.update_ledger_settings(
            LedgerSettingsUpdate(max_attachment_upload_bytes=5242880),
        )


def test_add_journal_entry_attachment_does_not_enforce_upload_limit(
    ledger_service: LedgerService,
) -> None:
    """Size policy is HTTP-only; domain service persists caller-supplied bytes (#263)."""
    try:
        ledger_service.update_ledger_settings(LedgerSettingsUpdate(max_attachment_upload_bytes=10))
        cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
        entry = ledger_service.create_entry(
            JournalEntryWrite(
                entry_date=date(2026, 5, 5),
                summary="entry",
                description=None,
                lines=[
                    JournalLineIn(account_id=cash.id, amount=Decimal("1")),
                    JournalLineIn(account_id=cash.id, amount=Decimal("-1")),
                ],
            ),
        )
        att = ledger_service.add_journal_entry_attachment(
            entry.id,
            file_bytes=b"x" * 20,
            upload_filename="big.bin",
            summary="doc",
            external_reference=None,
        )
        assert att.id > 0
    finally:
        ledger_service.update_ledger_settings(
            LedgerSettingsUpdate(max_attachment_upload_bytes=5242880),
        )


def test_attachment_shared_by_two_entries_then_orphan_purge(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    e1 = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 5),
            summary="a",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("1")),
                JournalLineIn(account_id=cash.id, amount=Decimal("-1")),
            ],
        ),
    )
    e2 = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 6),
            summary="b",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("1")),
                JournalLineIn(account_id=cash.id, amount=Decimal("-1")),
            ],
        ),
    )
    att = ledger_service.add_journal_entry_attachment(
        e1.id,
        file_bytes=_MINIMAL_PDF,
        upload_filename="shared.pdf",
        summary="shared doc",
        external_reference=None,
    )
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO journal_entry_attachments (journal_entry_id, attachment_id)
                    VALUES (%s, %s)
                    """,
                    (e2.id, att.id),
                )
    ledger_service.unlink_journal_entry_attachment(e1.id, att.id)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM attachments WHERE id = %s", (att.id,))
            assert int(cur.fetchone()["c"]) == 1
    ledger_service.unlink_journal_entry_attachment(e2.id, att.id)
    with connect(integration_db_url, row_factory=dict_row) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT COUNT(*) AS c FROM attachments")
            assert int(cur.fetchone()["c"]) == 0


def test_ledger_settings_max_attachment_byte_size_string(ledger_service: LedgerService) -> None:
    prev = ledger_service.get_ledger_settings().max_attachment_upload_bytes
    try:
        out = ledger_service.update_ledger_settings(
            LedgerSettingsUpdate(max_attachment_upload_bytes="1024k"),
        )
        assert out.max_attachment_upload_bytes == 1024 * 1024
    finally:
        ledger_service.update_ledger_settings(
            LedgerSettingsUpdate(max_attachment_upload_bytes=prev),
        )


def test_list_attachments_unknown_entry(ledger_service: LedgerService) -> None:
    with pytest.raises(LedgerNotFoundError, match="journal entry 999"):
        ledger_service.list_journal_entry_attachments(999)


def test_api_attachment_download_content_disposition(integration_db_url: str) -> None:
    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    svc = LedgerService(connection_factory=connection_factory)
    cash = svc.create_account(AccountCreate(name="Cash", type="asset"))
    entry = svc.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 5),
            summary="api att",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("1")),
                JournalLineIn(account_id=cash.id, amount=Decimal("-1")),
            ],
        ),
    )
    app.dependency_overrides[get_ledger_service] = lambda: LedgerService(
        connection_factory=connection_factory,
    )
    client = TestClient(app)
    try:
        r = client.post(
            f"/journal-entries/{entry.id}/attachments",
            files={"file": ("My File.pdf", _MINIMAL_PDF, "application/pdf")},
            data={"summary": "bill", "external_reference": "1"},
        )
        assert r.status_code == 201
        aid = r.json()["id"]
        dl = client.get(f"/journal-entries/{entry.id}/attachments/{aid}")
        assert dl.status_code == 200
        cd = dl.headers["content-disposition"].lower()
        assert "my file.pdf" in cd or "my%20file.pdf" in cd
    finally:
        app.dependency_overrides.pop(get_ledger_service, None)


def test_update_entry_allows_inactive_account_when_account_party_pair_unchanged(
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent", type="revenue"))
    party = ledger_service.create_party(PartyCreate(name="Tenant A", role="customer", is_active=True))
    created = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 10),
            summary="rent in",
            description="rent in",
            lines=[
                JournalLineIn(account_id=cash.id, party_id=party.id, amount=Decimal("100.00")),
                JournalLineIn(account_id=revenue.id, party_id=party.id, amount=Decimal("-100.00")),
            ],
        )
    )
    ledger_service.update_account(revenue.id, AccountUpdate(is_active=False))
    ledger_service.update_party(party.id, PartyUpdate(is_active=False))

    updated = ledger_service.update_entry(
        created.id,
        JournalEntryWrite(
            entry_date=date(2026, 5, 11),
            summary="rent in revised",
            description="edited header only",
            lines=[
                JournalLineIn(account_id=cash.id, party_id=party.id, amount=Decimal("120.00")),
                JournalLineIn(account_id=revenue.id, party_id=party.id, amount=Decimal("-120.00")),
            ],
        ),
    )
    assert updated.summary == "rent in revised"
    assert {ln.account_id for ln in updated.lines} == {cash.id, revenue.id}


def test_update_entry_rejects_line_with_new_inactive_account(
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent", type="revenue"))
    dormant = ledger_service.create_account(AccountCreate(name="Old Revenue", type="revenue"))
    ledger_service.update_account(dormant.id, AccountUpdate(is_active=False))
    created = ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 5, 12),
            summary="initial",
            description="initial",
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("50.00")),
                JournalLineIn(account_id=revenue.id, amount=Decimal("-50.00")),
            ],
        )
    )
    with pytest.raises(LedgerValidationError, match="deactivated"):
        ledger_service.update_entry(
            created.id,
            JournalEntryWrite(
                entry_date=date(2026, 5, 12),
                summary="swap to inactive",
                description="swap to inactive",
                lines=[
                    JournalLineIn(account_id=cash.id, amount=Decimal("50.00")),
                    JournalLineIn(account_id=dormant.id, amount=Decimal("-50.00")),
                ],
            ),
        )


def test_income_expense_report_omits_inactive_zero_accounts(
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    active_rev = ledger_service.create_account(AccountCreate(name="Active Rent", type="revenue"))
    dormant_rev = ledger_service.create_account(AccountCreate(name="Dormant Revenue", type="revenue"))
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 3, 1),
            summary="only active rent",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("10.00")),
                JournalLineIn(account_id=active_rev.id, amount=Decimal("-10.00")),
            ],
        )
    )
    ledger_service.update_account(dormant_rev.id, AccountUpdate(is_active=False))
    report = ledger_service.income_expense_report(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        exclude_zero_balance_accounts=False,
        preset=None,
    )
    rev_ids = {r.account_id for r in report.revenue_accounts}
    assert dormant_rev.id not in rev_ids
    assert active_rev.id in rev_ids


def test_balance_sheet_report_omits_inactive_zero_accounts(
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    dormant_asset = ledger_service.create_account(AccountCreate(name="Idle Equipment", type="asset"))
    equity_seed = ledger_service.create_account(AccountCreate(name="Equity Seed", type="equity"))
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 2, 1),
            summary="fund cash",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("200.00")),
                JournalLineIn(account_id=equity_seed.id, amount=Decimal("-200.00")),
            ],
        )
    )
    ledger_service.update_account(dormant_asset.id, AccountUpdate(is_active=False))
    report = ledger_service.balance_sheet_report(
        as_of_date=date(2026, 6, 1),
        exclude_requires_review=False,
        preset=None,
    )
    asset_ids = {a.account_id for a in report.assets.accounts if a.account_id is not None}
    assert dormant_asset.id not in asset_ids
    assert cash.id in asset_ids


def test_balance_sheet_keeps_inactive_account_with_nonzero_balance(
    ledger_service: LedgerService,
) -> None:
    cash = ledger_service.create_account(AccountCreate(name="Cash", type="asset"))
    used = ledger_service.create_account(AccountCreate(name="Used Asset", type="asset"))
    eq = ledger_service.create_account(AccountCreate(name="Equity", type="equity"))
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 2, 1),
            summary="buy asset",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("-50.00")),
                JournalLineIn(account_id=used.id, amount=Decimal("50.00")),
            ],
        )
    )
    ledger_service.create_entry(
        JournalEntryWrite(
            entry_date=date(2026, 2, 2),
            summary="balance",
            description=None,
            lines=[
                JournalLineIn(account_id=cash.id, amount=Decimal("50.00")),
                JournalLineIn(account_id=eq.id, amount=Decimal("-50.00")),
            ],
        )
    )
    ledger_service.update_account(used.id, AccountUpdate(is_active=False))
    report = ledger_service.balance_sheet_report(
        as_of_date=date(2026, 6, 1),
        exclude_requires_review=False,
        preset=None,
    )
    asset_ids = {a.account_id for a in report.assets.accounts if a.account_id is not None}
    assert used.id in asset_ids


def test_create_accrual_plan_rejects_inactive_party_or_accounts(
    ledger_service: LedgerService,
    integration_db_url: str,
) -> None:
    ar = ledger_service.create_account(AccountCreate(name="AR", type="asset"))
    rent = ledger_service.create_account(AccountCreate(name="Rent", type="revenue"))
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(accounts_receivable_account_id=ar.id),
    )
    party = ledger_service.create_party(PartyCreate(name="Inactive Tenant", role="customer", is_active=True))
    ledger_service.update_party(party.id, PartyUpdate(is_active=False))
    with pytest.raises(LedgerValidationError, match="inactive"):
        ledger_service.create_accrual_plan(
            AccrualPlanCreate(
                name="Bad party",
                direction="revenue",
                party_id=party.id,
                target_account_id=rent.id,
                frequency="monthly_day",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 31),
                amount=Decimal("100.00"),
                summary_template="{plan}",
                day_of_month=1,
            ),
        )

    party2 = ledger_service.create_party(PartyCreate(name="Active Tenant", role="customer", is_active=True))
    inactive_ar = ledger_service.create_account(AccountCreate(name="Inactive AR", type="asset"))
    ledger_service.update_account(inactive_ar.id, AccountUpdate(is_active=False))
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ledger_settings SET accounts_receivable_account_id = %s WHERE id = 1",
                    (inactive_ar.id,),
                )
    with pytest.raises(LedgerValidationError, match="deactivated"):
        ledger_service.create_accrual_plan(
            AccrualPlanCreate(
                name="Inactive AR bridge",
                direction="revenue",
                party_id=party2.id,
                target_account_id=rent.id,
                frequency="monthly_day",
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 31),
                amount=Decimal("100.00"),
                summary_template="{plan}",
                day_of_month=1,
            ),
        )


def test_update_ledger_settings_validate_on_change_for_system_defaults(
    ledger_service: LedgerService,
) -> None:
    ar = ledger_service.create_account(AccountCreate(name="Tenant AR", type="asset"))
    ar2 = ledger_service.create_account(AccountCreate(name="Tenant AR 2", type="asset"))
    ar3 = ledger_service.create_account(AccountCreate(name="Tenant AR 3", type="asset"))
    ledger_service.update_ledger_settings(LedgerSettingsUpdate(accounts_receivable_account_id=ar.id))

    with pytest.raises(LedgerConflictError, match='Settlement role "Accounts receivable"'):
        ledger_service.update_account(ar.id, AccountUpdate(is_active=False))

    out = ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(max_attachment_upload_bytes=2048),
    )
    assert out.accounts_receivable_account_id == ar.id
    assert out.max_attachment_upload_bytes == 2048

    ledger_service.update_ledger_settings(LedgerSettingsUpdate(accounts_receivable_account_id=ar2.id))
    ledger_service.update_account(ar.id, AccountUpdate(is_active=False))

    with pytest.raises(LedgerConflictError, match='Settlement role "Accounts receivable"'):
        ledger_service.update_account(ar2.id, AccountUpdate(is_active=False))

    ledger_service.update_ledger_settings(LedgerSettingsUpdate(accounts_receivable_account_id=ar3.id))
    ledger_service.update_account(ar2.id, AccountUpdate(is_active=False))
    with pytest.raises(LedgerValidationError, match="cannot use deactivated account"):
        ledger_service.update_ledger_settings(LedgerSettingsUpdate(accounts_receivable_account_id=ar2.id))


def test_ledger_settings_prepaid_expenses_account_asset_only(
    ledger_service: LedgerService,
) -> None:
    prepaid = ledger_service.create_account(AccountCreate(name="Vendor Prepaid", type="asset"))
    liability = ledger_service.create_account(AccountCreate(name="Accrued", type="liability"))

    out = ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(prepaid_expenses_account_id=prepaid.id),
    )
    assert out.prepaid_expenses_account_id == prepaid.id

    with pytest.raises(LedgerValidationError) as exc:
        ledger_service.update_ledger_settings(
            LedgerSettingsUpdate(prepaid_expenses_account_id=liability.id),
        )
    msg = str(exc.value)
    assert msg == (
        f'Settlement role "Prepaid expenses" requires an asset account. '
        f'"Accrued" ({liability.id}) is a liability account.'
    )


def test_ledger_settings_type_errors_name_setting_account_and_collect_all(
    ledger_service: LedgerService,
) -> None:
    asset = ledger_service.create_account(AccountCreate(name="Operating Cash", type="asset"))
    revenue = ledger_service.create_account(AccountCreate(name="Rent Income", type="revenue"))
    expense = ledger_service.create_account(AccountCreate(name="Office Supplies", type="expense"))

    with pytest.raises(LedgerSettingsValidationError) as exc:
        ledger_service.update_ledger_settings(
            LedgerSettingsUpdate(
                accounts_payable_account_id=asset.id,
                unearned_revenue_account_id=revenue.id,
                prepaid_expenses_account_id=expense.id,
            ),
        )
    msg = str(exc.value)
    assert len(exc.value.errors) == 3
    assert exc.value.errors[0] == (
        f'Settlement role "Accounts payable" requires a liability account. '
        f'"Operating Cash" ({asset.id}) is an asset account.'
    )
    assert exc.value.errors[1] == (
        f'Settlement role "Unearned revenue" requires a liability account. '
        f'"Rent Income" ({revenue.id}) is a revenue account.'
    )
    assert exc.value.errors[2] == (
        f'Settlement role "Prepaid expenses" requires an asset account. '
        f'"Office Supplies" ({expense.id}) is an expense account.'
    )
    assert "Accounts payable" in msg


def test_ledger_settings_inactive_error_names_setting_and_account(
    ledger_service: LedgerService,
) -> None:
    prepaid = ledger_service.create_account(AccountCreate(name="Vendor Prepaid", type="asset"))
    prepaid2 = ledger_service.create_account(AccountCreate(name="Vendor Prepaid 2", type="asset"))
    ledger_service.update_ledger_settings(LedgerSettingsUpdate(prepaid_expenses_account_id=prepaid.id))
    ledger_service.update_account(prepaid2.id, AccountUpdate(is_active=False))

    with pytest.raises(LedgerValidationError) as exc:
        ledger_service.update_ledger_settings(
            LedgerSettingsUpdate(prepaid_expenses_account_id=prepaid2.id),
        )
    msg = str(exc.value)
    assert msg == (
        f'Settlement role "Prepaid expenses" cannot use deactivated account '
        f'"Vendor Prepaid 2" ({prepaid2.id}).'
    )


def test_update_ledger_settings_validate_on_change_for_prepaid_expenses(
    ledger_service: LedgerService,
) -> None:
    prepaid = ledger_service.create_account(AccountCreate(name="Vendor Prepaid", type="asset"))
    prepaid2 = ledger_service.create_account(AccountCreate(name="Vendor Prepaid 2", type="asset"))
    ledger_service.update_ledger_settings(LedgerSettingsUpdate(prepaid_expenses_account_id=prepaid.id))

    with pytest.raises(LedgerConflictError, match='Settlement role "Prepaid expenses"'):
        ledger_service.update_account(prepaid.id, AccountUpdate(is_active=False))

    out = ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(max_attachment_upload_bytes=4096),
    )
    assert out.prepaid_expenses_account_id == prepaid.id

    ledger_service.update_ledger_settings(LedgerSettingsUpdate(prepaid_expenses_account_id=prepaid2.id))
    with pytest.raises(LedgerConflictError, match='Settlement role "Prepaid expenses"'):
        ledger_service.update_account(prepaid2.id, AccountUpdate(is_active=False))

    ledger_service.update_ledger_settings(LedgerSettingsUpdate(prepaid_expenses_account_id=prepaid.id))
    ledger_service.update_account(prepaid2.id, AccountUpdate(is_active=False))
    with pytest.raises(LedgerValidationError, match="cannot use deactivated account"):
        ledger_service.update_ledger_settings(
            LedgerSettingsUpdate(prepaid_expenses_account_id=prepaid2.id),
        )


def test_deactivate_account_blocked_for_configured_settlement_roles(
    ledger_service: LedgerService,
) -> None:
    prepaid = ledger_service.create_account(AccountCreate(name="Vendor Prepaid", type="asset"))
    suspense = ledger_service.create_account(AccountCreate(name="Import suspense", type="suspense"))
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            prepaid_expenses_account_id=prepaid.id,
            unallocated_debits_account_id=suspense.id,
        ),
    )

    with pytest.raises(LedgerConflictError) as exc:
        ledger_service.update_account(prepaid.id, AccountUpdate(is_active=False))
    assert str(exc.value) == (
        f'Cannot deactivate account "Vendor Prepaid" ({prepaid.id}): '
        f'it is configured as Settlement role "Prepaid expenses".'
    )

    with pytest.raises(LedgerConflictError) as exc:
        ledger_service.update_account(suspense.id, AccountUpdate(is_active=False))
    assert "Unallocated debits (default debit side)" in str(exc.value)

    other_prepaid = ledger_service.create_account(AccountCreate(name="Other prepaid", type="asset"))
    other_suspense = ledger_service.create_account(AccountCreate(name="Other suspense", type="suspense"))
    ledger_service.update_ledger_settings(
        LedgerSettingsUpdate(
            prepaid_expenses_account_id=other_prepaid.id,
            unallocated_debits_account_id=other_suspense.id,
        ),
    )
    updated_prepaid = ledger_service.update_account(prepaid.id, AccountUpdate(is_active=False))
    updated_suspense = ledger_service.update_account(suspense.id, AccountUpdate(is_active=False))
    assert updated_prepaid.is_active is False
    assert updated_suspense.is_active is False


def test_account_type_change_blocked_by_prepaid_expenses_setting(
    ledger_service: LedgerService,
) -> None:
    prepaid = ledger_service.create_account(AccountCreate(name="Vendor Prepaid", type="asset"))
    ledger_service.update_ledger_settings(LedgerSettingsUpdate(prepaid_expenses_account_id=prepaid.id))
    with pytest.raises(LedgerConflictError, match="ledger settings"):
        ledger_service.update_account(prepaid.id, AccountUpdate(type="liability"))


def test_update_party_does_not_revalidate_inactive_default_accounts_unless_changed(
    ledger_service: LedgerService,
) -> None:
    rev = ledger_service.create_account(AccountCreate(name="Party Rev", type="revenue"))
    party = ledger_service.create_party(
        PartyCreate(
            name="Mixed Co",
            role="customer",
            is_active=True,
            default_revenue_account_id=rev.id,
        )
    )
    ledger_service.update_account(rev.id, AccountUpdate(is_active=False))
    out = ledger_service.update_party(party.id, PartyUpdate(name="Mixed Co Renamed"))
    assert out.name == "Mixed Co Renamed"
    assert out.default_revenue_account_id == rev.id

    rev2 = ledger_service.create_account(AccountCreate(name="Rev Two", type="revenue"))
    ledger_service.update_account(rev2.id, AccountUpdate(is_active=False))
    with pytest.raises(LedgerValidationError, match="active"):
        ledger_service.update_party(party.id, PartyUpdate(default_revenue_account_id=rev2.id))
