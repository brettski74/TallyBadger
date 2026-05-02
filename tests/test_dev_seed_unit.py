"""Unit tests for SQL escaping in ``dev_seed`` export."""

from __future__ import annotations

from tallybadger.dev_seed import _sql_json_literal, _sql_text_literal


def test_sql_text_literal_escapes_single_quotes() -> None:
    assert _sql_text_literal("O'Brien") == "'O''Brien'"


def test_sql_json_literal_escapes_single_quotes_in_json() -> None:
    lit = _sql_json_literal({"memo": "it's"})
    assert lit.startswith("'")
    assert lit.endswith("'::jsonb")
    assert "it''s" in lit
