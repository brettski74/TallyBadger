"""Route-level smoke tests for journal entry filter preset endpoints (#107)."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from tallybadger.api.routes.journal_entry_filter_presets import (
    get_journal_entry_filter_preset_service,
)
from tallybadger.ledger.journal_entry_filter_preset_service import (
    JournalEntryFilterPresetConflictError,
    JournalEntryFilterPresetNotFoundError,
)
from tallybadger.ledger.models import (
    JournalEntryFilterPresetDefinition,
    JournalEntryFilterPresetOut,
)
from tallybadger.main import app


def _preset_out(preset_id: int, name: str) -> JournalEntryFilterPresetOut:
    now = datetime.now(tz=timezone.utc)
    return JournalEntryFilterPresetOut(
        id=preset_id,
        name=name,
        definition=JournalEntryFilterPresetDefinition(account_ids=[1, 2]),
        created_at=now,
        updated_at=now,
    )


class _StubService:
    def list_presets(self):
        return [_preset_out(7, "Open A/R")]

    def get_preset(self, preset_id):
        return _preset_out(preset_id, "Open A/R")

    def create_preset(self, *, name, definition):  # noqa: ARG002
        return _preset_out(7, name)

    def update_preset(self, preset_id, *, name=None, definition=None):  # noqa: ARG002
        return _preset_out(preset_id, name or "Open A/R")

    def delete_preset(self, preset_id):
        return None


def test_list_filter_presets_returns_collection() -> None:
    app.dependency_overrides[get_journal_entry_filter_preset_service] = _StubService
    client = TestClient(app)
    response = client.get("/journal-entry-filter-presets")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Open A/R"
    assert rows[0]["definition"]["account_ids"] == [1, 2]
    app.dependency_overrides.clear()


def test_create_filter_preset_duplicate_name_maps_to_409() -> None:
    class StubConflict(_StubService):
        def create_preset(self, *, name, definition):  # noqa: ARG002
            raise JournalEntryFilterPresetConflictError(
                f"preset name '{name}' is already in use"
            )

    app.dependency_overrides[get_journal_entry_filter_preset_service] = StubConflict
    client = TestClient(app)
    response = client.post(
        "/journal-entry-filter-presets",
        json={"name": "Open A/R", "definition": {}},
    )
    assert response.status_code == 409
    app.dependency_overrides.clear()


def test_create_filter_preset_invalid_sort_field_maps_to_422() -> None:
    app.dependency_overrides[get_journal_entry_filter_preset_service] = _StubService
    client = TestClient(app)
    response = client.post(
        "/journal-entry-filter-presets",
        json={
            "name": "Bad sort",
            "definition": {
                "sort": [{"field": "id", "direction": "asc"}],
            },
        },
    )
    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_replace_filter_preset_not_found_maps_to_404() -> None:
    class StubMissing(_StubService):
        def update_preset(self, preset_id, *, name=None, definition=None):  # noqa: ARG002
            raise JournalEntryFilterPresetNotFoundError(
                f"journal entry filter preset {preset_id} not found"
            )

    app.dependency_overrides[get_journal_entry_filter_preset_service] = StubMissing
    client = TestClient(app)
    response = client.put(
        "/journal-entry-filter-presets/999",
        json={"name": "Other", "definition": {}},
    )
    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_delete_filter_preset_returns_204() -> None:
    app.dependency_overrides[get_journal_entry_filter_preset_service] = _StubService
    client = TestClient(app)
    response = client.delete("/journal-entry-filter-presets/7")
    assert response.status_code == 204
    app.dependency_overrides.clear()


def test_create_filter_preset_invalid_definition_amount_band_maps_to_422() -> None:
    # Pydantic validation catches inverted amount band before reaching the service.
    app.dependency_overrides[get_journal_entry_filter_preset_service] = _StubService
    client = TestClient(app)
    response = client.post(
        "/journal-entry-filter-presets",
        json={
            "name": "Bad",
            "definition": {"amount_low": 100, "amount_high": 10},
        },
    )
    assert response.status_code == 422
    app.dependency_overrides.clear()
