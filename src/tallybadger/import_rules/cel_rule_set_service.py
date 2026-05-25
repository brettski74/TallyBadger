from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any

from psycopg import errors
from psycopg.rows import dict_row

from tallybadger.db import get_connection
from tallybadger.import_rules.cel_models import CelRuleSet
from tallybadger.import_rules.cel_rule_set_validation import validate_cel_rule_set


class CelRuleSetConflictError(Exception):
    """Raised when a rule set name already exists."""


class CelRuleSetNotFoundError(Exception):
    """Raised when a rule set id does not exist."""


class CelRuleSetStored:
    """In-process record returned by the service (not a Pydantic API model)."""

    __slots__ = ("id", "name", "rule_set", "created_at", "updated_at")

    def __init__(
        self,
        *,
        id: int,
        name: str,
        rule_set: CelRuleSet,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        self.id = id
        self.name = name
        self.rule_set = rule_set
        self.created_at = created_at
        self.updated_at = updated_at


class CelRuleSetListItem:
    __slots__ = ("id", "name", "updated_at")

    def __init__(self, *, id: int, name: str, updated_at: datetime) -> None:
        self.id = id
        self.name = name
        self.updated_at = updated_at


def _row_to_stored(row: dict[str, Any]) -> CelRuleSetStored:
    definition = row["definition"]
    if not isinstance(definition, dict):
        definition = dict(definition)
    return CelRuleSetStored(
        id=int(row["id"]),
        name=str(row["name"]),
        rule_set=CelRuleSet.model_validate(definition),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class CelRuleSetService:
    def __init__(
        self,
        connection_factory: Callable[[], AbstractContextManager] = get_connection,
    ) -> None:
        self._connection_factory = connection_factory

    def list_rule_sets(self) -> list[CelRuleSetListItem]:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, name, updated_at
                    FROM cel_rule_sets
                    ORDER BY name ASC
                    """
                )
                rows = cur.fetchall()
        return [
            CelRuleSetListItem(id=int(r["id"]), name=str(r["name"]), updated_at=r["updated_at"])
            for r in rows
        ]

    def get_rule_set(self, rule_set_id: int) -> CelRuleSetStored:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, name, definition, created_at, updated_at
                    FROM cel_rule_sets
                    WHERE id = %s
                    """,
                    (rule_set_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise CelRuleSetNotFoundError(f"rule set {rule_set_id} not found")
        return _row_to_stored(row)

    def create_rule_set(self, name: str, rule_set: CelRuleSet) -> CelRuleSetStored:
        clean = name.strip()
        if not clean:
            raise ValueError("name must not be empty")
        validate_cel_rule_set(rule_set)
        payload = rule_set.model_dump(mode="json")
        with self._connection_factory() as conn:
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            INSERT INTO cel_rule_sets (name, definition)
                            VALUES (%s, %s::jsonb)
                            RETURNING id, name, definition, created_at, updated_at
                            """,
                            (clean, json.dumps(payload)),
                        )
                        row = cur.fetchone()
            except errors.UniqueViolation as exc:
                raise CelRuleSetConflictError(f"name '{clean}' is already in use") from exc
        assert row is not None
        return _row_to_stored(row)

    def update_rule_set(
        self,
        rule_set_id: int,
        *,
        name: str | None = None,
        rule_set: CelRuleSet | None = None,
    ) -> CelRuleSetStored:
        if name is None and rule_set is None:
            raise ValueError("at least one of name or rule_set must be provided")

        clean_name = name.strip() if name is not None else None
        if clean_name is not None and not clean_name:
            raise ValueError("name must not be empty")

        definition_json: str | None
        if rule_set is not None:
            validate_cel_rule_set(rule_set)
            definition_json = json.dumps(rule_set.model_dump(mode="json"))
        else:
            definition_json = None

        with self._connection_factory() as conn:
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            UPDATE cel_rule_sets
                            SET
                              name = COALESCE(%s, name),
                              definition = COALESCE(%s::jsonb, definition),
                              updated_at = NOW()
                            WHERE id = %s
                            RETURNING id, name, definition, created_at, updated_at
                            """,
                            (clean_name, definition_json, rule_set_id),
                        )
                        row = cur.fetchone()
            except errors.UniqueViolation as exc:
                raise CelRuleSetConflictError(
                    f"name '{clean_name}' is already in use",
                ) from exc

        if row is None:
            raise CelRuleSetNotFoundError(f"rule set {rule_set_id} not found")
        return _row_to_stored(row)

    def delete_rule_set(self, rule_set_id: int) -> None:
        with self._connection_factory() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM cel_rule_sets WHERE id = %s", (rule_set_id,))
                    if cur.rowcount == 0:
                        raise CelRuleSetNotFoundError(f"rule set {rule_set_id} not found")
