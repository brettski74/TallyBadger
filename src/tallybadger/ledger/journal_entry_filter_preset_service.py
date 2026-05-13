"""Service for named journal-entry list filter presets (#107)."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any

from psycopg import errors
from psycopg.rows import dict_row

from tallybadger.db import get_connection
from tallybadger.ledger.models import (
    JournalEntryFilterPresetDefinition,
    JournalEntryFilterPresetOut,
)


class JournalEntryFilterPresetConflictError(Exception):
    """Raised when a preset name already exists."""


class JournalEntryFilterPresetNotFoundError(Exception):
    """Raised when a preset id does not exist."""


def _row_to_out(row: dict[str, Any]) -> JournalEntryFilterPresetOut:
    definition = row["definition"]
    if not isinstance(definition, dict):
        definition = dict(definition)
    return JournalEntryFilterPresetOut(
        id=int(row["id"]),
        name=str(row["name"]),
        definition=JournalEntryFilterPresetDefinition.model_validate(definition),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class JournalEntryFilterPresetService:
    def __init__(
        self,
        connection_factory: Callable[[], AbstractContextManager] = get_connection,
    ) -> None:
        self._connection_factory = connection_factory

    def list_presets(self) -> list[JournalEntryFilterPresetOut]:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, name, definition, created_at, updated_at
                    FROM journal_entry_filter_presets
                    ORDER BY name ASC
                    """
                )
                rows = cur.fetchall()
        return [_row_to_out(r) for r in rows]

    def get_preset(self, preset_id: int) -> JournalEntryFilterPresetOut:
        with self._connection_factory() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT id, name, definition, created_at, updated_at
                    FROM journal_entry_filter_presets
                    WHERE id = %s
                    """,
                    (preset_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise JournalEntryFilterPresetNotFoundError(
                f"journal entry filter preset {preset_id} not found"
            )
        return _row_to_out(row)

    def create_preset(
        self,
        *,
        name: str,
        definition: JournalEntryFilterPresetDefinition,
    ) -> JournalEntryFilterPresetOut:
        clean = name.strip()
        if not clean:
            raise ValueError("name must not be empty")
        payload = definition.model_dump(mode="json", exclude_none=True)
        with self._connection_factory() as conn:
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            INSERT INTO journal_entry_filter_presets (name, definition)
                            VALUES (%s, %s::jsonb)
                            RETURNING id, name, definition, created_at, updated_at
                            """,
                            (clean, json.dumps(payload)),
                        )
                        row = cur.fetchone()
            except errors.UniqueViolation as exc:
                raise JournalEntryFilterPresetConflictError(
                    f"preset name '{clean}' is already in use"
                ) from exc
        assert row is not None
        return _row_to_out(row)

    def update_preset(
        self,
        preset_id: int,
        *,
        name: str | None = None,
        definition: JournalEntryFilterPresetDefinition | None = None,
    ) -> JournalEntryFilterPresetOut:
        if name is None and definition is None:
            raise ValueError("at least one of name or definition must be provided")

        clean_name = name.strip() if name is not None else None
        if clean_name is not None and not clean_name:
            raise ValueError("name must not be empty")

        definition_json: str | None
        if definition is not None:
            definition_json = json.dumps(
                definition.model_dump(mode="json", exclude_none=True),
            )
        else:
            definition_json = None

        with self._connection_factory() as conn:
            try:
                with conn.transaction():
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute(
                            """
                            UPDATE journal_entry_filter_presets
                            SET
                              name = COALESCE(%s, name),
                              definition = COALESCE(%s::jsonb, definition),
                              updated_at = NOW()
                            WHERE id = %s
                            RETURNING id, name, definition, created_at, updated_at
                            """,
                            (clean_name, definition_json, preset_id),
                        )
                        row = cur.fetchone()
            except errors.UniqueViolation as exc:
                raise JournalEntryFilterPresetConflictError(
                    f"preset name '{clean_name}' is already in use"
                ) from exc

        if row is None:
            raise JournalEntryFilterPresetNotFoundError(
                f"journal entry filter preset {preset_id} not found"
            )
        return _row_to_out(row)

    def delete_preset(self, preset_id: int) -> None:
        with self._connection_factory() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM journal_entry_filter_presets WHERE id = %s",
                        (preset_id,),
                    )
                    if cur.rowcount == 0:
                        raise JournalEntryFilterPresetNotFoundError(
                            f"journal entry filter preset {preset_id} not found"
                        )
