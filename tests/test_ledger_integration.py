from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import os

import pytest
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.ledger.models import AccountCreate, JournalEntryWrite, JournalLineIn
from tallybadger.ledger.service import LedgerService, LedgerValidationError

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
                    TRUNCATE TABLE journal_lines, journal_entries, accounts
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
