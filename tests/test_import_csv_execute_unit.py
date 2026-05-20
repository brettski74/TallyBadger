"""Unit tests: CSV execute date parsing (via Pendulum) and row-level validation."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from tallybadger.api.routes.import_csv import _bag_to_journal_entry, _build_lines_from_array, _convert_cell
from tallybadger.ledger.models import AccountOut, JournalEntryOut, JournalLineOut, LedgerSettingsOut
from tallybadger.import_rules.cel_models import CelRule, CelRuleSet
from tallybadger.import_templates.models import ImportTemplateColumn
from tallybadger.main import app


def _blank_ledger_settings() -> LedgerSettingsOut:
    return LedgerSettingsOut(
        accounts_receivable_account_id=None,
        accounts_payable_account_id=None,
        unearned_revenue_account_id=None,
        unallocated_debits_account_id=None,
        unallocated_credits_account_id=None,
        default_cheque_credit_account_id=None,
        default_cheque_debit_account_id=None,
        max_attachment_upload_bytes=5242880,
        max_cheque_series_count=60,
        updated_at=datetime.now(tz=timezone.utc),
    )


@pytest.fixture
def import_execute_client() -> TestClient:
    ledger = MagicMock()
    ledger.list_accounts.return_value = []
    ledger.list_parties.return_value = []
    ledger.list_cheques.return_value = []
    ledger.get_ledger_settings.return_value = _blank_ledger_settings()

    from tallybadger.api.routes.import_csv import get_ledger_service

    app.dependency_overrides[get_ledger_service] = lambda: ledger
    yield TestClient(app)
    app.dependency_overrides.pop(get_ledger_service, None)


def _client_with_cel_rule(expression: str) -> TestClient:
    ledger = MagicMock()
    ledger.list_accounts.return_value = []
    ledger.list_parties.return_value = []
    ledger.list_cheques.return_value = []
    ledger.get_ledger_settings.return_value = _blank_ledger_settings()
    cel_svc = MagicMock()
    cel_svc.get_rule_set.return_value = MagicMock(
        rule_set=CelRuleSet(rules=[CelRule(sort_order=10, expression=expression)]),
    )
    from tallybadger.api.routes.import_csv import get_cel_rule_set_service, get_ledger_service

    app.dependency_overrides[get_ledger_service] = lambda: ledger
    app.dependency_overrides[get_cel_rule_set_service] = lambda: cel_svc
    return TestClient(app)


def _teardown_cel_client() -> None:
    from tallybadger.api.routes.import_csv import get_cel_rule_set_service, get_ledger_service

    app.dependency_overrides.pop(get_ledger_service, None)
    app.dependency_overrides.pop(get_cel_rule_set_service, None)


@pytest.fixture
def import_execute_client_cel_invalid() -> TestClient:
    """Rule set with invalid CEL — must surface 422 row_errors, not HTTP 500."""
    client = _client_with_cel_rule("!!!not_cel!!!")
    yield client
    _teardown_cel_client()


def test_execute_csv_non_iso_date_after_cel_returns_422_not_500() -> None:
    """CEL overwrote ``date`` with a non-ISO string (e.g. copied wrong attribute); row error, not 500."""
    client = _client_with_cel_rule('{"set":{"date": attributes["summary"]}}')
    try:
        payload = {
            "csv_text": "date,summary\n2026-01-01,not-an-iso-date\n",
            "basename": "rows.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string", "date_format": None},
            ],
            "cel_rule_set_id": 1,
        }
        r = client.post("/imports/csv/execute", json=payload)
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert detail["message"] == "CSV import failed validation"
        assert detail["row_errors"][0]["row_number"] == 2
        errs = detail["row_errors"][0]["errors"]
        assert any("date" in e.lower() and "iso" in e.lower() for e in errs)
    finally:
        _teardown_cel_client()


def test_execute_csv_row_error_includes_cel_debug_when_journal_build_fails() -> None:
    """422 row_errors include the same ``debug`` array a successful entry row would have (#57)."""
    client = _client_with_cel_rule(
        '{"set":{"date": attributes["summary"], "marker": debug(99)}}',
    )
    try:
        payload = {
            "csv_text": "date,summary\n2026-01-01,not-an-iso-date\n",
            "basename": "rows.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string", "date_format": None},
            ],
            "cel_rule_set_id": 1,
        }
        r = client.post("/imports/csv/execute", json=payload)
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        row0 = detail["row_errors"][0]
        assert row0["row_number"] == 2
        assert "debug" in row0
        assert row0["debug"] == [{"rule": "rule[0]", "value": 99, "row_number": 2}]
    finally:
        _teardown_cel_client()


def test_execute_csv_non_date_type_after_cel_returns_422_not_500() -> None:
    """CEL set ``date`` to a number; :func:`_to_entry_date` rejects it — row error, not 500."""
    client = _client_with_cel_rule('{"set":{"date": 42}}')
    try:
        payload = {
            "csv_text": "date,summary\n2026-01-01,Rent\n",
            "basename": "rows.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string", "date_format": None},
            ],
            "cel_rule_set_id": 1,
        }
        r = client.post("/imports/csv/execute", json=payload)
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert detail["message"] == "CSV import failed validation"
        assert detail["row_errors"][0]["row_number"] == 2
        errs = detail["row_errors"][0]["errors"]
        assert any("date" in e.lower() for e in errs)
    finally:
        _teardown_cel_client()


def test_execute_csv_cel_date_literal_column_label_returns_422_not_500() -> None:
    """Using ``\"date\": \"Transaction Date\"`` (string literal) instead of ``attr[\"Transaction Date\"]``."""
    client = _client_with_cel_rule('{"set":{"date": "Transaction Date"}}')
    try:
        payload = {
            "csv_text": "date,summary\n2026-01-01,Rent\n",
            "basename": "rows.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string", "date_format": None},
            ],
            "cel_rule_set_id": 1,
        }
        r = client.post("/imports/csv/execute", json=payload)
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert detail["message"] == "CSV import failed validation"
        assert detail["row_errors"][0]["row_number"] == 2
        errs = detail["row_errors"][0]["errors"]
        assert any("date" in e.lower() and "iso" in e.lower() for e in errs)
    finally:
        _teardown_cel_client()


def test_execute_csv_cel_missing_comma_in_set_map_returns_422_not_500() -> None:
    """Missing comma between entries in a CEL map (parse error) must be ImportRulesCelError → 422, not 500."""
    client = _client_with_cel_rule('{"set":{"amount": 1 "date": 2}}')
    try:
        payload = {
            "csv_text": "date,summary\n2026-01-01,ok\n",
            "basename": "rows.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string", "date_format": None},
            ],
            "cel_rule_set_id": 1,
        }
        r = client.post("/imports/csv/execute", json=payload)
        assert r.status_code == 422, r.text
        detail = r.json()["detail"]
        assert detail["message"] == "CSV import failed validation"
        errs = detail["row_errors"][0]["errors"]
        assert any("CEL rule" in e for e in errs)
    finally:
        _teardown_cel_client()


def test_convert_cell_accepts_unpadded_us_date() -> None:
    col = ImportTemplateColumn(attribute_name="date", data_type="date", date_format="M/D/YYYY")
    assert _convert_cell("4/1/2026", col).isoformat() == "2026-04-01"


def test_convert_cell_accepts_padded_us_date() -> None:
    col = ImportTemplateColumn(attribute_name="date", data_type="date", date_format="M/D/YYYY")
    assert _convert_cell("04/01/2026", col).isoformat() == "2026-04-01"


def test_convert_cell_mm_dd_pendulum_accepts_single_digit_month_day() -> None:
    col = ImportTemplateColumn(attribute_name="date", data_type="date", date_format="MM/DD/YYYY")
    assert _convert_cell("4/7/2026", col).isoformat() == "2026-04-07"


def test_convert_cell_accepts_two_digit_month_day_when_mm_dd_format() -> None:
    col = ImportTemplateColumn(attribute_name="date", data_type="date", date_format="MM/DD/YYYY")
    assert _convert_cell("04/07/2026", col).isoformat() == "2026-04-07"


def test_convert_cell_iso_accepts_single_digit_month_day_with_yyyy_mm_dd() -> None:
    """Pendulum matches ``M`` and ``D`` flexibly inside ``YYYY-MM-DD``."""
    col = ImportTemplateColumn(attribute_name="date", data_type="date", date_format="YYYY-MM-DD")
    assert _convert_cell("2026-4-07", col).isoformat() == "2026-04-07"


def test_convert_cell_lenient_yyyy_m_d() -> None:
    col = ImportTemplateColumn(attribute_name="date", data_type="date", date_format="YYYY-M-D")
    assert _convert_cell("2026-4-7", col).isoformat() == "2026-04-07"


def test_bag_to_journal_entry_passes_cheque_id_from_bag() -> None:
    now = datetime.now(tz=timezone.utc)
    cash = AccountOut(id=1, name="Cash", type="asset", is_active=True, created_at=now, updated_at=now)
    rev = AccountOut(id=2, name="Revenue", type="revenue", is_active=True, created_at=now, updated_at=now)
    account_ids = {"Cash": 1, "Revenue": 2}
    party_ids: dict[str, int] = {}
    accounts_by_id = {1: cash, 2: rev}
    bag = {
        "date": date(2026, 1, 1),
        "summary": "Cheque-linked import",
        "cheque-id": 55,
        "line": [
            {"account": "Cash", "amount": "100.00"},
            {"account": "Revenue", "amount": "-100.00"},
        ],
    }
    je = _bag_to_journal_entry(
        bag,
        account_ids,
        party_ids,
        ledger_settings=_blank_ledger_settings(),
        accounts_by_id=accounts_by_id,
    )
    assert je.cheque_id == 55


def test_execute_csv_debug_only_on_entries_that_used_debug() -> None:
    """CEL #59: per-entry ``debug`` on CSV execute; omit key when that row had no ``debug()`` call."""
    now = datetime.now(tz=timezone.utc)
    cash = AccountOut(id=1, name="Cash", type="asset", is_active=True, created_at=now, updated_at=now)
    rent = AccountOut(id=2, name="Rent Income", type="revenue", is_active=True, created_at=now, updated_at=now)
    ledger = MagicMock()
    ledger.list_accounts.return_value = [cash, rent]
    ledger.list_parties.return_value = []
    ledger.list_cheques.return_value = []
    ledger.get_ledger_settings.return_value = LedgerSettingsOut(
        accounts_receivable_account_id=None,
        accounts_payable_account_id=None,
        unearned_revenue_account_id=None,
        unallocated_debits_account_id=None,
        unallocated_credits_account_id=None,
        default_cheque_credit_account_id=None,
        default_cheque_debit_account_id=None,
        max_attachment_upload_bytes=5242880,
        max_cheque_series_count=60,
        updated_at=now,
    )
    expr = (
        '(attributes["summary"] == "A") ? '
        '{"set":{"dr-account":"Cash", "cr-account":"Rent Income", "amount": debug(100)}} : '
        '{"set":{"dr-account":"Cash", "cr-account":"Rent Income", "amount": 100}}'
    )
    cel_svc = MagicMock()
    cel_svc.get_rule_set.return_value = MagicMock(
        rule_set=CelRuleSet(rules=[CelRule(sort_order=10, expression=expr)]),
    )
    e1 = JournalEntryOut(
        id=101,
        entry_date=date(2026, 1, 1),
        summary="A",
        description=None,
        requires_review=False,
        cheque_id=None,
        created_at=now,
        updated_at=now,
        lines=[
            JournalLineOut(
                id=1,
                account_id=1,
                account_name="Cash",
                party_id=None,
                party_name=None,
                amount=Decimal("100"),
            ),
            JournalLineOut(
                id=2,
                account_id=2,
                account_name="Rent Income",
                party_id=None,
                party_name=None,
                amount=Decimal("-100"),
            ),
        ],
    )
    e2 = JournalEntryOut(
        id=102,
        entry_date=date(2026, 1, 2),
        summary="B",
        description=None,
        requires_review=False,
        cheque_id=None,
        created_at=now,
        updated_at=now,
        lines=[
            JournalLineOut(
                id=3,
                account_id=1,
                account_name="Cash",
                party_id=None,
                party_name=None,
                amount=Decimal("100"),
            ),
            JournalLineOut(
                id=4,
                account_id=2,
                account_name="Rent Income",
                party_id=None,
                party_name=None,
                amount=Decimal("-100"),
            ),
        ],
    )
    ledger.create_import_batch_with_entries.return_value = (1, [e1, e2])
    from tallybadger.api.routes.import_csv import get_cel_rule_set_service, get_ledger_service
    from tallybadger.main import app

    app.dependency_overrides[get_ledger_service] = lambda: ledger
    app.dependency_overrides[get_cel_rule_set_service] = lambda: cel_svc
    try:
        client = TestClient(app)
        payload = {
            "csv_text": "date,summary\n2026-01-01,A\n2026-01-02,B\n",
            "basename": "two-rows.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string", "date_format": None},
            ],
            "cel_rule_set_id": 1,
        }
        r = client.post("/imports/csv/execute", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["posted_entries"] == 2
        ent0, ent1 = data["entries"]
        assert "debug" in ent0
        assert ent0["debug"][0]["value"] == 100
        assert ent0["debug"][0]["row_number"] == 2
        assert "debug" not in ent1
    finally:
        app.dependency_overrides.pop(get_ledger_service, None)
        app.dependency_overrides.pop(get_cel_rule_set_service, None)


def test_execute_csv_seeds_default_account_for_cel_from_template() -> None:
    """``default_import_account_id`` resolves to ``default-account`` before rules (#92)."""
    now = datetime.now(tz=timezone.utc)
    chequing = AccountOut(
        id=7,
        name="Business Chequing",
        type="asset",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    expense = AccountOut(
        id=8,
        name="Repairs",
        type="expense",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    ledger = MagicMock()
    ledger.list_accounts.return_value = [chequing, expense]
    ledger.list_parties.return_value = []
    ledger.list_cheques.return_value = []
    ledger.get_ledger_settings.return_value = _blank_ledger_settings()
    expr = '{"set":{"dr-account":"Repairs", "cr-account":"Business Chequing", "amount": 50, "probe": debug(attributes["default-account"])}}'
    cel_svc = MagicMock()
    cel_svc.get_rule_set.return_value = MagicMock(
        rule_set=CelRuleSet(rules=[CelRule(sort_order=10, expression=expr)]),
    )
    je = JournalEntryOut(
        id=201,
        entry_date=date(2026, 3, 1),
        summary="m",
        description=None,
        requires_review=False,
        cheque_id=None,
        created_at=now,
        updated_at=now,
        lines=[
            JournalLineOut(
                id=1,
                account_id=8,
                account_name="Repairs",
                party_id=None,
                party_name=None,
                amount=Decimal("50"),
            ),
            JournalLineOut(
                id=2,
                account_id=7,
                account_name="Business Chequing",
                party_id=None,
                party_name=None,
                amount=Decimal("-50"),
            ),
        ],
    )
    ledger.create_import_batch_with_entries.return_value = (2, [je])
    from tallybadger.api.routes.import_csv import get_cel_rule_set_service, get_ledger_service
    from tallybadger.main import app

    app.dependency_overrides[get_ledger_service] = lambda: ledger
    app.dependency_overrides[get_cel_rule_set_service] = lambda: cel_svc
    try:
        client = TestClient(app)
        payload = {
            "csv_text": "date,summary\n2026-03-01,m\n",
            "basename": "march.csv",
            "has_header_row": True,
            "columns": [
                {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
                {"attribute_name": "summary", "data_type": "string", "date_format": None},
            ],
            "cel_rule_set_id": 1,
            "default_import_account_id": 7,
        }
        r = client.post("/imports/csv/execute", json=payload)
        assert r.status_code == 200, r.text
        ent0 = r.json()["entries"][0]
        assert ent0["debug"][0]["value"] == "Business Chequing"
        assert ent0["debug"][0]["row_number"] == 2
    finally:
        app.dependency_overrides.pop(get_ledger_service, None)
        app.dependency_overrides.pop(get_cel_rule_set_service, None)


def test_execute_csv_cel_error_returns_422_not_500(import_execute_client_cel_invalid: TestClient) -> None:
    payload = {
        "csv_text": "date,summary\n2026-01-01,ok\n",
        "basename": "ok.csv",
        "has_header_row": True,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
            {"attribute_name": "summary", "data_type": "string", "date_format": None},
        ],
        "cel_rule_set_id": 1,
    }
    r = import_execute_client_cel_invalid.post("/imports/csv/execute", json=payload)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["message"] == "CSV import failed validation"
    assert detail["row_errors"][0]["row_number"] == 2
    assert any("CEL rule" in err for err in detail["row_errors"][0]["errors"])


def test_execute_csv_reports_all_row_errors(import_execute_client: TestClient) -> None:
    """Every row with validation failures should appear in row_errors (not only the first)."""
    csv_text = "date,x\nnotadate,a\nalsono,b\n"
    payload = {
        "csv_text": csv_text,
        "basename": "bad-dates.csv",
        "has_header_row": True,
        "columns": [
            {"attribute_name": "date", "data_type": "date", "date_format": "YYYY-MM-DD"},
            {"attribute_name": "summary", "data_type": "string", "date_format": None},
        ],
    }
    r = import_execute_client.post("/imports/csv/execute", json=payload)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["message"] == "CSV import failed validation"
    rows = {item["row_number"]: item["errors"] for item in detail["row_errors"]}
    assert rows[2]
    assert rows[3]
    assert len(detail["row_errors"]) == 2


def test_build_lines_from_array_parses_obligation_id() -> None:
    account_ids = {"Cash": 1, "Accounts Receivable": 2}
    party_ids = {"Tenant": 10}
    lines = _build_lines_from_array(
        {
            "line": [
                {"account": "Cash", "amount": "500.00", "party": "Tenant"},
                {
                    "account": "Accounts Receivable",
                    "amount": "-500.00",
                    "party": "Tenant",
                    "obligation-id": "42",
                },
            ],
        },
        account_ids,
        party_ids,
    )
    assert len(lines) == 2
    assert lines[0].obligation_id is None
    assert lines[1].obligation_id == 42
    assert lines[1].amount == Decimal("-500.00")


def test_build_lines_from_array_rejects_invalid_obligation_id() -> None:
    with pytest.raises(ValueError, match="obligation-id"):
        _build_lines_from_array(
            {
                "line": [
                    {"account": "Cash", "amount": "100.00"},
                    {"account": "Accounts Receivable", "amount": "-100.00", "obligation-id": "nope"},
                ],
            },
            {"Cash": 1, "Accounts Receivable": 2},
            {},
        )
