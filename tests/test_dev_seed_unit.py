"""Unit tests for SQL escaping in ``dev_seed`` export."""

from __future__ import annotations

from tallybadger.dev_seed import (
    _account_id_subselect_by_name,
    _sql_json_literal,
    _sql_text_literal,
    _subtype_sql_expr,
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
