from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.ledger.service import (
    LedgerConflictError,
    LedgerNotFoundError,
    LedgerValidationError,
)
from tallybadger.main import app


class StubLedgerService:
    def list_accounts(self):
        return []

    def create_account(self, _payload):
        raise LedgerConflictError("account name already exists")

    def update_account(self, _account_id, _payload):
        raise LedgerValidationError("at least one account field must be updated")

    def list_entries(self, **_kwargs):
        return []

    def create_entry(self, _payload):
        raise LedgerValidationError("journal entry is not balanced")

    def list_account_lines(self, _account_id, **_kwargs):
        raise LedgerNotFoundError("account 999 not found")

    def get_entry(self, _entry_id):
        return {
            "id": 1,
            "entry_date": date(2026, 4, 24),
            "description": None,
            "created_at": datetime.now(tz=timezone.utc),
            "updated_at": datetime.now(tz=timezone.utc),
            "lines": [{"id": 1, "account_id": 1, "amount": Decimal("1.00")}],
        }

    def update_entry(self, _entry_id, _payload):
        return self.get_entry(_entry_id)

    def delete_entry(self, _entry_id):
        return None


def test_create_account_conflict_maps_to_409() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)

    response = client.post(
        "/accounts",
        json={"name": "Cash", "type": "asset", "is_active": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "account name already exists"
    app.dependency_overrides.clear()


def test_create_journal_entry_validation_maps_to_422() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)

    response = client.post(
        "/journal-entries",
        json={
            "entry_date": "2026-04-24",
            "description": "bad entry",
            "lines": [
                {"account_id": 1, "amount": "10.00"},
                {"account_id": 2, "amount": "-9.00"},
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "journal entry is not balanced"
    app.dependency_overrides.clear()


def test_create_journal_entry_deactivated_account_maps_to_422() -> None:
    class StubDeactivatedPosting(StubLedgerService):
        def create_entry(self, _payload):
            raise LedgerValidationError("account 3 is deactivated; reactivate before posting")

    app.dependency_overrides[get_ledger_service] = StubDeactivatedPosting
    client = TestClient(app)

    response = client.post(
        "/journal-entries",
        json={
            "entry_date": "2026-04-24",
            "description": "blocked",
            "lines": [
                {"account_id": 3, "amount": "10.00"},
                {"account_id": 2, "amount": "-10.00"},
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "account 3 is deactivated; reactivate before posting"
    app.dependency_overrides.clear()


def test_update_account_validation_maps_to_422() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)

    response = client.patch("/accounts/1", json={})

    assert response.status_code == 422
    assert response.json()["detail"] == "at least one account field must be updated"
    app.dependency_overrides.clear()


def test_list_journal_entries_uses_query_params() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)

    response = client.get(
        "/journal-entries",
        params={
            "from_date": "2026-04-01",
            "to_date": "2026-04-30",
            "limit": 25,
            "offset": 5,
        },
    )

    assert response.status_code == 200
    assert response.json() == []
    app.dependency_overrides.clear()


def test_list_account_lines_not_found_maps_to_404() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)

    response = client.get("/accounts/999/lines")

    assert response.status_code == 404
    assert response.json()["detail"] == "account 999 not found"
    app.dependency_overrides.clear()
