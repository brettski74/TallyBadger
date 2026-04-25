from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.ledger.service import (
    LedgerConflictError,
    LedgerValidationError,
)
from tallybadger.main import app


class StubLedgerService:
    def list_accounts(self):
        return []

    def create_account(self, _payload):
        raise LedgerConflictError("account name already exists")

    def create_entry(self, _payload):
        raise LedgerValidationError("journal entry is not balanced")

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
