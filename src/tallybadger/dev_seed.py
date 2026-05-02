"""Dev-only Postgres seed: export/import accounts, parties, CEL rule sets, import templates.

This file is **not** run by ``tallybadger.db_migrations``. Production deploys should only
apply numbered ``sql/NNN_*.sql`` migrations; local manual testing uses ``sql/dev_seed.sql``.

- ``python -m tallybadger.dev_seed export`` — dump current DB to ``sql/dev_seed.sql`` (see ``make export-dev-seed``).
- ``python -m tallybadger.dev_seed apply`` — run that SQL against the configured DB (see ``make dev-seed``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.core.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_SEED_PATH = REPO_ROOT / "sql" / "dev_seed.sql"


def _sql_text_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_json_literal(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return "'" + raw.replace("'", "''") + "'::jsonb"


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

    with connect(url) as conn:
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
                SELECT name, role
                FROM parties
                WHERE is_active = TRUE
                ORDER BY id
                """,
            )
            parties = list(cur.fetchall())
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
                SELECT it.name, it.has_header_row, it.columns_definition, crs.name AS rule_set_name
                FROM import_templates it
                LEFT JOIN cel_rule_sets crs ON crs.id = it.cel_rule_set_id
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
        lines.append(
            "INSERT INTO parties (name, role, is_active)\n"
            f"SELECT {_sql_text_literal(name)}, {_sql_text_literal(role)}, TRUE\n"
            "WHERE NOT EXISTS (SELECT 1 FROM parties p WHERE LOWER(p.name) = LOWER("
            f"{_sql_text_literal(name)}));\n",
        )
    if parties:
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
        lines.append(
            "INSERT INTO import_templates (name, has_header_row, columns_definition, cel_rule_set_id)\n"
            f"SELECT {_sql_text_literal(name)}, {str(has_header).upper()}, "
            f"{_sql_json_literal(cols)}, {fk_sql}\n"
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

    with connect(url) as conn:
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
