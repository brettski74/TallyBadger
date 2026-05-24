"""Unit tests for SQL escaping in ``dev_seed`` export."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from tallybadger.dev_seed import (
    _account_id_subselect_by_name,
    _import_normal_balance_sql_expr,
    _sql_json_literal,
    _sql_text_literal,
    _subtype_sql_expr,
    export_dev_seed_sql,
)


def test_sql_text_literal_escapes_single_quotes() -> None:
    assert _sql_text_literal("O'Brien") == "'O''Brien'"


def test_sql_json_literal_escapes_single_quotes_in_json() -> None:
    lit = _sql_json_literal({"memo": "it's"})
    assert lit.startswith("'")
    assert lit.endswith("'::jsonb")
    assert "it''s" in lit


def test_account_id_subselect_by_name() -> None:
    assert _account_id_subselect_by_name(None) == "NULL::bigint"
    assert _account_id_subselect_by_name("") == "NULL::bigint"
    assert "LOWER(name)" in _account_id_subselect_by_name("Cash")
    assert "Cash" in _account_id_subselect_by_name("Cash")


def test_subtype_sql_expr() -> None:
    assert _subtype_sql_expr(None) == "NULL::text"
    assert _subtype_sql_expr("") == "NULL::text"
    assert _subtype_sql_expr("  ") == "NULL::text"
    assert _subtype_sql_expr("Tenant") == "'Tenant'"


def test_import_normal_balance_sql_expr() -> None:
    assert _import_normal_balance_sql_expr(None) == "NULL::text"
    assert _import_normal_balance_sql_expr("") == "NULL::text"
    assert _import_normal_balance_sql_expr("DEBIT") == "'debit'"
    assert _import_normal_balance_sql_expr("credit") == "'credit'"
    assert _import_normal_balance_sql_expr("invalid") == "NULL::text"


def test_export_dev_seed_sql_import_template_includes_default_import_columns(tmp_path: Path) -> None:
    """Regression for #63: export must emit default_import_account_id and default_import_normal_balance."""
    fetch_batches = [
        [{"name": "Petty cash", "type": "asset"}],
        [],
        [],
        [],
        [
            {
                "name": "Bank CSV",
                "has_header_row": True,
                "columns_definition": {"date": "col_a"},
                "rule_set_name": None,
                "default_import_account_name": "Petty cash",
                "default_import_normal_balance": "debit",
            },
        ],
    ]

    class _FakeCursor:
        def __init__(self) -> None:
            self._i = 0

        def execute(self, _query: object, _params: object | None = None) -> None:
            return None

        def fetchall(self) -> list[dict[str, object]]:
            batch = fetch_batches[self._i]
            self._i += 1
            return batch

    fake_cur = _FakeCursor()
    cur_ctx = MagicMock()
    cur_ctx.__enter__.return_value = fake_cur
    cur_ctx.__exit__.return_value = None
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = cur_ctx

    conn_ctx = MagicMock()
    conn_ctx.__enter__.return_value = fake_conn
    conn_ctx.__exit__.return_value = None

    out = tmp_path / "seed.sql"
    with patch("tallybadger.dev_seed.connect_database", return_value=conn_ctx):
        export_dev_seed_sql(database_url="postgresql://unused", destination=out)

    text = out.read_text(encoding="utf-8")
    assert (
        "INSERT INTO import_templates (name, has_header_row, columns_definition, cel_rule_set_id, "
        "default_import_account_id, default_import_normal_balance)"
    ) in text
    assert ", 'debit'\n" in text or ", 'debit'\r\n" in text
    assert "LOWER('Petty cash')" in text
