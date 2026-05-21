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

    def list_parties(self):
        return []

    def list_party_subtype_suggestions(self):
        return []

    def create_account(self, _payload):
        raise LedgerConflictError("account name already exists")

    def create_party(self, _payload):
        raise LedgerConflictError("party name already exists")

    def update_account(self, _account_id, _payload):
        raise LedgerValidationError("at least one account field must be updated")

    def update_party(self, _party_id, _payload):
        raise LedgerValidationError("at least one party field must be updated")

    def list_accrual_plans(self, **_kwargs):
        from tallybadger.ledger.models import AccrualPlanListResponse

        return AccrualPlanListResponse(plans=[])

    def get_accrual_plan_detail(self, plan_id: int):
        from datetime import datetime, timezone
        from decimal import Decimal

        from tallybadger.ledger.models import (
            AccrualPlanDetailResponse,
            AccrualPlanOut,
            AccrualPlanSummaryRollups,
        )

        if plan_id != 1:
            raise LedgerNotFoundError(f"accrual plan {plan_id} not found")
        now = datetime.now(tz=timezone.utc)
        return AccrualPlanDetailResponse(
            plan=AccrualPlanOut(
                id=1,
                name="Stub Plan",
                direction="revenue",
                party_id=1,
                target_account_id=2,
                bridge_account_id=3,
                frequency="monthly_day",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 12, 31),
                amount=Decimal("100.00"),
                summary_template="{plan}",
                description_template=None,
                day_of_week=None,
                day_of_month=1,
                month_of_year=None,
                business_day_adjust=False,
                created_at=now,
                updated_at=now,
            ),
            obligations=[],
            summary=AccrualPlanSummaryRollups(
                total_original_accrued=Decimal("100.00"),
                total_settled_to_date=Decimal("0"),
                past_due=Decimal("0"),
                not_yet_due=Decimal("100.00"),
                unearned=Decimal("0"),
            ),
        )

    def preview_accrual_plan(self, _payload):
        return []

    def create_accrual_plan(self, _payload):
        raise LedgerValidationError("plan frequency produced no entries in the date range")

    def update_accrual_plan(self, _plan_id, _payload):
        raise LedgerValidationError("plan has already posted entries; pass force_override=true to update")

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
            "summary": "Stub summary",
            "description": None,
            "created_at": datetime.now(tz=timezone.utc),
            "updated_at": datetime.now(tz=timezone.utc),
            "lines": [
                {
                    "id": 1,
                    "account_id": 1,
                    "party_id": None,
                    "amount": Decimal("1.00"),
                    "account_name": "Cash",
                    "party_name": None,
                }
            ],
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


def test_create_party_conflict_maps_to_409() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)

    response = client.post(
        "/parties",
        json={"name": "Acme Yard Maintenance", "role": "customer", "is_active": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "party name already exists"
    app.dependency_overrides.clear()


def test_create_journal_entry_validation_maps_to_422() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)

    response = client.post(
        "/journal-entries",
        json={
            "entry_date": "2026-04-24",
            "summary": "bad entry summary",
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
            "summary": "blocked summary",
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


def test_list_journal_entries_forwards_new_filter_dimensions() -> None:
    captured: dict[str, object] = {}

    class StubForwarding(StubLedgerService):
        def list_entries(self, **kwargs):
            captured.update(kwargs)
            return []

    app.dependency_overrides[get_ledger_service] = StubForwarding
    client = TestClient(app)

    response = client.get(
        "/journal-entries",
        params=[
            ("account_ids", "1"),
            ("account_ids", "2"),
            ("party_ids", "5"),
            ("accrual_plan_ids", "9"),
            ("amount_low", "10"),
            ("amount_high", "20"),
            ("cheque_association", "with_cheque"),
            ("import_basename", "Stmt.csv"),
        ],
    )

    assert response.status_code == 200
    assert captured["account_ids"] == [1, 2]
    assert captured["party_ids"] == [5]
    assert captured["accrual_plan_ids"] == [9]
    assert captured["amount_low"] == 10
    assert captured["amount_high"] == 20
    assert captured["cheque_association"] == "with_cheque"
    assert captured["import_basename"] == "Stmt.csv"
    app.dependency_overrides.clear()


def test_list_journal_entries_invalid_amount_band_maps_to_422() -> None:
    class StubAmountBand(StubLedgerService):
        def list_entries(self, **_kwargs):
            raise LedgerValidationError("amount_low must be less than or equal to amount_high")

    app.dependency_overrides[get_ledger_service] = StubAmountBand
    client = TestClient(app)

    response = client.get(
        "/journal-entries",
        params={"amount_low": 50, "amount_high": 10},
    )

    assert response.status_code == 422
    assert "amount_low" in response.json()["detail"]
    app.dependency_overrides.clear()


def test_list_journal_entries_rejects_invalid_cheque_association_value() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)

    response = client.get(
        "/journal-entries",
        params={"cheque_association": "bogus"},
    )

    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_list_account_lines_not_found_maps_to_404() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)

    response = client.get("/accounts/999/lines")

    assert response.status_code == 404
    assert response.json()["detail"] == "account 999 not found"
    app.dependency_overrides.clear()


def test_create_journal_entry_requires_summary_field() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)

    response = client.post(
        "/journal-entries",
        json={
            "entry_date": "2026-04-24",
            "description": "missing summary",
            "lines": [
                {"account_id": 1, "amount": "10.00"},
                {"account_id": 2, "amount": "-10.00"},
            ],
        },
    )

    assert response.status_code == 422
    app.dependency_overrides.clear()


def test_list_accrual_plans_returns_wrapper() -> None:
    client = TestClient(app)
    app.dependency_overrides[get_ledger_service] = lambda: StubLedgerService()
    try:
        response = client.get("/accrual-plans")
        assert response.status_code == 200
        assert response.json() == {"plans": [], "filter_options": None}
    finally:
        app.dependency_overrides.clear()


def test_get_accrual_plan_detail_returns_wrapper() -> None:
    client = TestClient(app)
    app.dependency_overrides[get_ledger_service] = lambda: StubLedgerService()
    try:
        response = client.get("/accrual-plans/1")
        assert response.status_code == 200
        body = response.json()
        assert body["plan"]["id"] == 1
        assert body["obligations"] == []
        assert body["summary"]["total_original_accrued"] == "100.00"
    finally:
        app.dependency_overrides.clear()


def test_get_accrual_plan_detail_not_found_maps_to_404() -> None:
    client = TestClient(app)
    app.dependency_overrides[get_ledger_service] = lambda: StubLedgerService()
    try:
        response = client.get("/accrual-plans/99")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_preview_accrual_plan_endpoint() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)
    response = client.post(
        "/accrual-plans/preview",
        json={
            "name": "Plan 2026",
            "direction": "revenue",
            "party_id": 1,
            "target_account_id": 2,
            "bridge_account_id": 1,
            "frequency": "monthly_day",
            "start_date": "2026-01-01",
            "end_date": "2026-03-31",
            "amount": "100.00",
            "summary_template": "{plan} {month}",
            "day_of_month": 1,
        },
    )
    assert response.status_code == 200
    assert response.json() == []
    app.dependency_overrides.clear()


def test_update_accrual_plan_guard_maps_to_422() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)
    response = client.patch("/accrual-plans/1", json={"name": "Updated"})
    assert response.status_code == 422
    assert "force_override=true" in response.json()["detail"]
    app.dependency_overrides.clear()


def test_preview_accrual_plan_weekly_rejects_business_day_adjust() -> None:
    app.dependency_overrides[get_ledger_service] = StubLedgerService
    client = TestClient(app)
    response = client.post(
        "/accrual-plans/preview",
        json={
            "name": "Weekly Plan",
            "direction": "revenue",
            "party_id": 1,
            "target_account_id": 2,
            "bridge_account_id": 1,
            "frequency": "weekly",
            "start_date": "2026-01-01",
            "end_date": "2026-03-31",
            "amount": "100.00",
            "summary_template": "{plan} {month}",
            "day_of_week": 0,
            "business_day_adjust": True,
        },
    )
    assert response.status_code == 422
    app.dependency_overrides.clear()
