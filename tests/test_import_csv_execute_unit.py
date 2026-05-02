"""Unit tests: CSV execute date parsing (via Pendulum) and row-level validation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from tallybadger.api.routes.import_csv import _convert_cell
from tallybadger.import_rules.cel_models import CelRule, CelRuleSet
from tallybadger.import_templates.models import ImportTemplateColumn
from tallybadger.main import app


@pytest.fixture
def import_execute_client() -> TestClient:
    ledger = MagicMock()
    ledger.list_accounts.return_value = []
    ledger.list_parties.return_value = []

    from tallybadger.api.routes.import_csv import get_ledger_service

    app.dependency_overrides[get_ledger_service] = lambda: ledger
    yield TestClient(app)
    app.dependency_overrides.pop(get_ledger_service, None)


def _client_with_cel_rule(expression: str) -> TestClient:
    ledger = MagicMock()
    ledger.list_accounts.return_value = []
    ledger.list_parties.return_value = []
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


def test_execute_csv_non_date_type_after_cel_returns_422_not_500() -> None:
    """CEL set ``date`` to a number; :func:`_to_entry_date` rejects it — row error, not 500."""
    client = _client_with_cel_rule('{"set":{"date": 42}}')
    try:
        payload = {
            "csv_text": "date,summary\n2026-01-01,Rent\n",
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


def test_execute_csv_cel_error_returns_422_not_500(import_execute_client_cel_invalid: TestClient) -> None:
    payload = {
        "csv_text": "date,summary\n2026-01-01,ok\n",
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
