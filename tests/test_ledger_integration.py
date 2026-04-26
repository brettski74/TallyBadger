from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import os

import pytest
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.ledger.models import (
    AccountCreate,
    AccountUpdate,
    AccrualPlanCreate,
    AccrualPlanUpdate,
    JournalEntryWrite,
    JournalLineIn,
    PartyCreate,
)
from tallybadger.ledger.service import (
    JOURNAL_LIST_SPLIT_LABEL,
    LedgerService,
    LedgerValidationError,
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
                    """
                    TRUNCATE TABLE journal_lines, journal_entries, accrual_plans, parties, accounts
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
