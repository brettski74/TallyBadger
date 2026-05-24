"""Route-level smoke tests for cheque register filter preset endpoints (#196)."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from tallybadger.api.routes.cheque_register_filter_presets import (
    get_cheque_register_filter_preset_service,
)
from tallybadger.ledger.cheque_register_filter_preset_service import (
    ChequeRegisterFilterPresetConflictError,
    ChequeRegisterFilterPresetNotFoundError,
)
from tallybadger.ledger.models import (
    ChequeRegisterFilterPresetDefinition,
    ChequeRegisterFilterPresetOut,
    ChequeRegisterFilterPresetSortKey,
)
from tallybadger.main import app


def _preset_out(preset_id: int, name: str) -> ChequeRegisterFilterPresetOut:
    now = datetime.now(tz=timezone.utc)
    return ChequeRegisterFilterPresetOut(
        id=preset_id,
        name=name,
        definition=ChequeRegisterFilterPresetDefinition(
            status="open",
            sort=[ChequeRegisterFilterPresetSortKey(field="amount", direction="desc")],
        ),
        created_at=now,
        updated_at=now,
    )


class _StubService:
    def list_presets(self):
        return [_preset_out(3, "Open by amount")]

    def get_preset(self, preset_id):
        return _preset_out(preset_id, "Open by amount")

    def create_preset(self, *, name, definition):  # noqa: ARG002
        return _preset_out(3, name)

    def update_preset(self, preset_id, *, name=None, definition=None):  # noqa: ARG002
        return _preset_out(preset_id, name or "Open by amount")

    def delete_preset(self, preset_id):
        return None


def test_list_cheque_register_filter_presets_returns_collection() -> None:
    app.dependency_overrides[get_cheque_register_filter_preset_service] = _StubService
    client = TestClient(app)
    response = client.get("/cheque-register-filter-presets")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "Open by amount"
    assert rows[0]["definition"]["sort"][0]["field"] == "amount"
    app.dependency_overrides.clear()


def test_create_cheque_register_filter_preset_duplicate_name_maps_to_409() -> None:
    class StubConflict(_StubService):
        def create_preset(self, *, name, definition):  # noqa: ARG002
            raise ChequeRegisterFilterPresetConflictError(
                f"preset name '{name}' is already in use"
            )

    app.dependency_overrides[get_cheque_register_filter_preset_service] = StubConflict
    client = TestClient(app)
    response = client.post(
        "/cheque-register-filter-presets",
        json={"name": "Open by amount", "definition": {"status": "open"}},
    )
    assert response.status_code == 409
    app.dependency_overrides.clear()


def test_create_cheque_register_filter_preset_invalid_sort_field_maps_to_422() -> None:
    app.dependency_overrides[get_cheque_register_filter_preset_service] = _StubService
    client = TestClient(app)
    response = client.post(
        "/cheque-register-filter-presets",
        json={
            "name": "Bad sort",
            "definition": {
                "sort": [{"field": "id", "direction": "asc"}],
            },
        },
    )
    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_replace_cheque_register_filter_preset_not_found_maps_to_404() -> None:
    class StubMissing(_StubService):
        def update_preset(self, preset_id, *, name=None, definition=None):  # noqa: ARG002
            raise ChequeRegisterFilterPresetNotFoundError(
                f"cheque register filter preset {preset_id} not found"
            )

    app.dependency_overrides[get_cheque_register_filter_preset_service] = StubMissing
    client = TestClient(app)
    response = client.put(
        "/cheque-register-filter-presets/99",
        json={"name": "Missing", "definition": {}},
    )
    assert response.status_code == 404
    app.dependency_overrides.clear()
