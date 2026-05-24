"""Dev-only Postgres seed: export/import accounts, parties (and match patterns), CEL rule sets,
import templates (including default import account and normal balance).

This file is **not** run by ``tallybadger.db_migrations``. Production deploys should only
apply numbered ``sql/NNN_*.sql`` migrations; local manual testing uses ``sql/dev_seed.sql``.

- ``python -m tallybadger.dev_seed export`` — dump current DB to ``sql/dev_seed.sql`` (see ``make export-dev-seed``).
- ``python -m tallybadger.dev_seed apply`` — run that SQL against the configured DB (see ``make dev-seed``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tallybadger.core.config import get_settings
from tallybadger.db import connect_database

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_SEED_PATH = REPO_ROOT / "sql" / "dev_seed.sql"


def _sql_text_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_json_literal(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return "'" + raw.replace("'", "''") + "'::jsonb"


def _account_id_subselect_by_name(account_name: str | None) -> str:
    """SQL expression resolving an account id by name, or NULL."""
    if account_name is None:
        return "NULL::bigint"
    name = str(account_name).strip()
    if not name:
        return "NULL::bigint"
    return (
        "(SELECT id FROM accounts WHERE LOWER(name) = LOWER("
        f"{_sql_text_literal(name)}) LIMIT 1)"
    )


def _subtype_sql_expr(subtype: object) -> str:
    if subtype is None:
        return "NULL::text"
    s = str(subtype).strip()
    if not s:
        return "NULL::text"
    return _sql_text_literal(s)


def _import_normal_balance_sql_expr(value: object) -> str:
    """SQL expression for import_templates.default_import_normal_balance (debit/credit or NULL)."""
    if value is None:
        return "NULL::text"
    s = str(value).strip().lower()
    if s in ("debit", "credit"):
        return _sql_text_literal(s)
    return "NULL::text"


def export_dev_seed_sql(*, database_url: str | None = None, destination: Path | None = None) -> Path:
    """Write idempotent INSERT statements for dev-relevant tables."""
    url = database_url or get_settings().database_url
    dest = destination or DEV_SEED_PATH
    lines: list[str] = [
        "-- DEV ONLY: not applied by production migrations.",
        "-- Idempotent INSERTs (safe to re-run on the same database).",
        "-- Regenerate from your local DB: make export-dev-seed",
        "",
    ]

    with connect_database(url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT name, type
                FROM accounts
                WHERE is_active = TRUE
                ORDER BY id
                """,
            )
            accounts = list(cur.fetchall())
            cur.execute(
                """
                SELECT p.name, p.role, p.is_active, p.subtype,
                       ra.name AS default_revenue_account_name,
                       ea.name AS default_expense_account_name
                FROM parties p
                LEFT JOIN accounts ra ON ra.id = p.default_revenue_account_id
                LEFT JOIN accounts ea ON ea.id = p.default_expense_account_id
                WHERE p.is_active = TRUE
                ORDER BY p.id
                """,
            )
            parties = list(cur.fetchall())
            cur.execute(
                """
                SELECT p.name AS party_name, pm.pattern, pm.sort_order
                FROM party_match_patterns pm
                INNER JOIN parties p ON p.id = pm.party_id
                WHERE p.is_active = TRUE
                ORDER BY p.id, pm.sort_order, pm.id
                """,
            )
            party_patterns = list(cur.fetchall())
            cur.execute(
                """
                SELECT name, definition
                FROM cel_rule_sets
                ORDER BY id
                """,
            )
            rule_sets = list(cur.fetchall())
            cur.execute(
                """
                SELECT it.name, it.has_header_row, it.columns_definition, crs.name AS rule_set_name,
                       da.name AS default_import_account_name,
                       it.default_import_normal_balance
                FROM import_templates it
                LEFT JOIN cel_rule_sets crs ON crs.id = it.cel_rule_set_id
                LEFT JOIN accounts da ON da.id = it.default_import_account_id
                ORDER BY it.id
                """,
            )
            templates = list(cur.fetchall())

    for row in accounts:
        name, typ = row["name"], row["type"]
        lines.append(
            "INSERT INTO accounts (name, type, is_active)\n"
            f"SELECT {_sql_text_literal(name)}, {_sql_text_literal(typ)}, TRUE\n"
            "WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE LOWER(a.name) = LOWER("
            f"{_sql_text_literal(name)}));\n",
        )
    if accounts:
        lines.append("")

    for row in parties:
        name, role = row["name"], row["role"]
        subtype_sql = _subtype_sql_expr(row.get("subtype"))
        rev_sql = _account_id_subselect_by_name(row.get("default_revenue_account_name"))
        exp_sql = _account_id_subselect_by_name(row.get("default_expense_account_name"))
        lines.append(
            "INSERT INTO parties (name, role, is_active, subtype, "
            "default_revenue_account_id, default_expense_account_id)\n"
            f"SELECT {_sql_text_literal(name)}, {_sql_text_literal(role)}, TRUE, "
            f"{subtype_sql}, {rev_sql}, {exp_sql}\n"
            "WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER("
            f"{_sql_text_literal(name)}));\n",
        )
    if parties:
        lines.append("")

    for prow in party_patterns:
        party_name = str(prow["party_name"])
        pattern = str(prow["pattern"])
        sort_order = int(prow["sort_order"])
        pat_lit = _sql_text_literal(pattern)
        party_lit = _sql_text_literal(party_name)
        lines.append(
            "INSERT INTO party_match_patterns (party_id, pattern, sort_order)\n"
            f"SELECT p.id, {pat_lit}, {sort_order}\n"
            "FROM parties p\n"
            f"WHERE LOWER(p.name) = LOWER({party_lit})\n"
            "AND NOT EXISTS (\n"
            "  SELECT 1 FROM party_match_patterns pm\n"
            "  WHERE pm.party_id = p.id AND pm.sort_order = "
            f"{sort_order} AND pm.pattern = {pat_lit}\n"
            ");\n",
        )
    if party_patterns:
        lines.append("")

    for row in rule_sets:
        name = row["name"]
        definition = row["definition"]
        lines.append(
            "INSERT INTO cel_rule_sets (name, definition)\n"
            f"SELECT {_sql_text_literal(name)}, {_sql_json_literal(definition)}\n"
            "WHERE NOT EXISTS (SELECT 1 FROM cel_rule_sets crs WHERE LOWER(crs.name) = LOWER("
            f"{_sql_text_literal(name)}));\n",
        )
    if rule_sets:
        lines.append("")

    for row in templates:
        name = row["name"]
        has_header = bool(row["has_header_row"])
        cols = row["columns_definition"]
        rs_name = row["rule_set_name"]
        fk_sql = (
            f"(SELECT id FROM cel_rule_sets WHERE LOWER(name) = LOWER({_sql_text_literal(rs_name)}) LIMIT 1)"
            if rs_name
            else "NULL::bigint"
        )
        def_acct_sql = _account_id_subselect_by_name(row.get("default_import_account_name"))
        def_norm_sql = _import_normal_balance_sql_expr(row.get("default_import_normal_balance"))
        lines.append(
            "INSERT INTO import_templates (name, has_header_row, columns_definition, cel_rule_set_id, "
            "default_import_account_id, default_import_normal_balance)\n"
            f"SELECT {_sql_text_literal(name)}, {str(has_header).upper()}, "
            f"{_sql_json_literal(cols)}, {fk_sql}, {def_acct_sql}, {def_norm_sql}\n"
            "WHERE NOT EXISTS (SELECT 1 FROM import_templates t WHERE LOWER(t.name) = LOWER("
            f"{_sql_text_literal(name)}));\n",
        )
    if templates:
        lines.append("")

    lines.append(
        "-- End dev seed (no schema_migrations row — this file is not a numbered migration).\n",
    )
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def apply_dev_seed_sql(*, database_url: str | None = None, seed_path: Path | None = None) -> None:
    """Execute ``sql/dev_seed.sql`` if it contains SQL beyond comments."""
    url = database_url or get_settings().database_url
    path = seed_path or DEV_SEED_PATH
    if not path.is_file():
        print(f"dev seed file missing: {path}", file=sys.stderr)
        raise SystemExit(1)
    sql = path.read_text(encoding="utf-8")
    stripped = sql.strip()
    if not stripped:
        print(f"{path} is empty, nothing to apply")
        return
    # Skip if file is only comments / blank lines
    if not any(
        line for line in stripped.splitlines() if line.strip() and not line.lstrip().startswith("--")
    ):
        print(f"{path} has no executable SQL, nothing to apply")
        return

    with connect_database(url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(sql)


def main() -> None:
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "export"
    if cmd in ("export", "e"):
        path = export_dev_seed_sql()
        print(f"wrote {path}")
    elif cmd in ("apply", "a"):
        apply_dev_seed_sql()
        print(f"applied {DEV_SEED_PATH}")
    else:
        print("usage: python -m tallybadger.dev_seed export|apply", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
