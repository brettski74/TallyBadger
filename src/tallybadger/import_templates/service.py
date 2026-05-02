from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any

from psycopg import errors
from psycopg.rows import dict_row

from tallybadger.db import get_connection
from tallybadger.import_templates.models import ImportTemplateColumn


class ImportTemplateConflictError(Exception):
    """Raised when a template name already exists."""


class ImportTemplateNotFoundError(Exception):
    """Raised when a template id does not exist."""


class ImportTemplateInvalidRuleSetError(Exception):
    """Raised when cel_rule_set_id does not reference an existing rule set."""


class ImportTemplateStored:
    __slots__ = (
        "id",
        "name",
        "has_header_row",
        "columns",
        "cel_rule_set_id",
        "default_import_account_id",
        "default_import_normal_balance",
        "created_at",
        "updated_at",
    )

    def __init__(
        self,
        *,
        id: int,
        name: str,
        has_header_row: bool,
        columns: list[ImportTemplateColumn],
        cel_rule_set_id: int | None,
        default_import_account_id: int | None,
        default_import_normal_balance: str | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        self.id = id
        self.name = name
        self.has_header_row = has_header_row
        self.columns = columns
        self.cel_rule_set_id = cel_rule_set_id
        self.default_import_account_id = default_import_account_id
        self.default_import_normal_balance = default_import_normal_balance
        self.created_at = created_at
        self.updated_at = updated_at


class ImportTemplateListItem:
    __slots__ = ("id", "name", "updated_at")

    def __init__(self, *, id: int, name: str, updated_at: datetime) -> None:
        self.id = id
        self.name = name
        self.updated_at = updated_at


def _parse_columns(raw: Any) -> list[ImportTemplateColumn]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = list(raw)
    return [ImportTemplateColumn.model_validate(item) for item in raw]


def _row_to_stored(row: dict[str, Any]) -> ImportTemplateStored:
    normal = row.get("default_import_normal_balance")
    return ImportTemplateStored(
        id=int(row["id"]),
        name=str(row["name"]),
        has_header_row=bool(row["has_header_row"]),
        columns=_parse_columns(row["columns_definition"]),
        cel_rule_set_id=int(row["cel_rule_set_id"]) if row["cel_rule_set_id"] is not None else None,
        default_import_account_id=int(row["default_import_account_id"])
        if row.get("default_import_account_id") is not None
        else None,
        default_import_normal_balance=str(normal) if normal is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ImportTemplateService:
    def __init__(
        self,
        connection_factory: Callable[[], AbstractContextManager] = get_connection,
    ) -> None:
        self._connection_factory = connection_factory

    def list_templates(self) -> list[ImportTemplateListItem]:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, name, updated_at
                    FROM import_templates
                    ORDER BY name ASC
                    """
                )
                rows = cur.fetchall()
        return [
            ImportTemplateListItem(id=int(r["id"]), name=str(r["name"]), updated_at=r["updated_at"])
            for r in rows
        ]

    def get_template(self, template_id: int) -> ImportTemplateStored:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, name, has_header_row, columns_definition, cel_rule_set_id,
                           default_import_account_id, default_import_normal_balance,
                           created_at, updated_at
                    FROM import_templates
                    WHERE id = %s
                    """,
                    (template_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise ImportTemplateNotFoundError(f"import template {template_id} not found")
        return _row_to_stored(row)

    def create_template(
        self,
        name: str,
        has_header_row: bool,
        columns: list[ImportTemplateColumn],
        cel_rule_set_id: int | None = None,
        *,
        default_import_account_id: int | None = None,
        default_import_normal_balance: str | None = None,
    ) -> ImportTemplateStored:
        clean = name.strip()
        if not clean:
            raise ValueError("name must not be empty")
        payload = [c.model_dump(mode="json") for c in columns]
        with self._connection_factory() as conn:
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            INSERT INTO import_templates
                              (name, has_header_row, columns_definition, cel_rule_set_id,
                               default_import_account_id, default_import_normal_balance)
                            VALUES (%s, %s, %s::jsonb, %s, %s, %s)
                            RETURNING id, name, has_header_row, columns_definition,
                                      cel_rule_set_id, default_import_account_id,
                                      default_import_normal_balance, created_at, updated_at
                            """,
                            (
                                clean,
                                has_header_row,
                                json.dumps(payload),
                                cel_rule_set_id,
                                default_import_account_id,
                                default_import_normal_balance,
                            ),
                        )
                        row = cur.fetchone()
            except errors.UniqueViolation as exc:
                raise ImportTemplateConflictError(f"name '{clean}' is already in use") from exc
            except errors.ForeignKeyViolation as exc:
                raise ImportTemplateInvalidRuleSetError(
                    "cel_rule_set_id does not reference an existing rule set",
                ) from exc
        assert row is not None
        return _row_to_stored(row)

    def update_template(self, template_id: int, patch: dict[str, Any]) -> ImportTemplateStored:
        if not patch:
            raise ValueError("at least one field must be provided")

        set_parts: list[str] = []
        args: list[Any] = []

        if "name" in patch:
            clean = str(patch["name"]).strip()
            if not clean:
                raise ValueError("name must not be empty")
            set_parts.append("name = %s")
            args.append(clean)

        if "has_header_row" in patch:
            set_parts.append("has_header_row = %s")
            args.append(bool(patch["has_header_row"]))

        if "columns" in patch:
            raw_cols = patch["columns"]
            cols = [ImportTemplateColumn.model_validate(c) for c in raw_cols]
            set_parts.append("columns_definition = %s::jsonb")
            args.append(json.dumps([c.model_dump(mode="json") for c in cols]))

        if "cel_rule_set_id" in patch:
            set_parts.append("cel_rule_set_id = %s")
            args.append(patch["cel_rule_set_id"])

        if "default_import_account_id" in patch:
            set_parts.append("default_import_account_id = %s")
            args.append(patch["default_import_account_id"])

        if "default_import_normal_balance" in patch:
            set_parts.append("default_import_normal_balance = %s")
            args.append(patch["default_import_normal_balance"])

        if not set_parts:
            raise ValueError("at least one field must be provided")

        set_parts.append("updated_at = NOW()")
        args.append(template_id)

        sql = f"""
            UPDATE import_templates
            SET {", ".join(set_parts)}
            WHERE id = %s
            RETURNING id, name, has_header_row, columns_definition, cel_rule_set_id,
                      default_import_account_id, default_import_normal_balance,
                      created_at, updated_at
        """

        with self._connection_factory() as conn:
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(sql, args)
                        row = cur.fetchone()
            except errors.UniqueViolation as exc:
                raise ImportTemplateConflictError("name is already in use") from exc
            except errors.ForeignKeyViolation as exc:
                raise ImportTemplateInvalidRuleSetError(
                    "cel_rule_set_id does not reference an existing rule set",
                ) from exc

        if row is None:
            raise ImportTemplateNotFoundError(f"import template {template_id} not found")
        return _row_to_stored(row)

    def delete_template(self, template_id: int) -> None:
        with self._connection_factory() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM import_templates WHERE id = %s", (template_id,))
                    if cur.rowcount == 0:
                        raise ImportTemplateNotFoundError(f"import template {template_id} not found")
