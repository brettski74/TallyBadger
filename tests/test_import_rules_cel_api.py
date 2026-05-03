from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.main import app


@pytest.fixture
def cel_evaluate_client() -> TestClient:
    ledger = MagicMock()
    ledger.list_parties.return_value = []
    app.dependency_overrides[get_ledger_service] = lambda: ledger
    yield TestClient(app)
    app.dependency_overrides.pop(get_ledger_service, None)


def test_cel_evaluate_endpoint_happy_path(cel_evaluate_client: TestClient) -> None:
    body = {
        "attributes": {"amount": 150.5, "description": "EMT - BOB, ref 1"},
        "rule_set": {
            "rules": [
                {
                    "sort_order": 10,
                    "captures": [
                        {
                            "attribute": "description",
                            "pattern": r"EMT\s*-\s*(?P<sender>[^,]+),",
                            "flags": [],
                        },
                    ],
                    "expression": (
                        'attributes["amount"] > 100 ? {"set":{"party": match[0]["groups"]["sender"]},'
                        '"review":"confirm party"} : null'
                    ),
                },
            ],
        },
    }
    r = cel_evaluate_client.post("/import-rules/cel/evaluate", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["attributes"]["party"] == "BOB"
    assert data["attributes"]["amount"] == 150.5
    assert data["require_review"] is True
    assert data["review_reason"] == "confirm party"


def test_cel_evaluate_endpoint_omits_debug_when_unused(cel_evaluate_client: TestClient) -> None:
    body = {
        "attributes": {},
        "rule_set": {"rules": [{"expression": '{"set":{"x": 1}}'}]},
    }
    r = cel_evaluate_client.post("/import-rules/cel/evaluate", json=body)
    assert r.status_code == 200
    assert "debug" not in r.json()


def test_cel_evaluate_endpoint_includes_debug_without_row_number(cel_evaluate_client: TestClient) -> None:
    body = {
        "attributes": {},
        "rule_set": {"rules": [{"expression": '{"set":{"x": debug(9)}}'}]},
    }
    r = cel_evaluate_client.post("/import-rules/cel/evaluate", json=body)
    assert r.status_code == 200
    data = r.json()
    assert "debug" in data
    assert len(data["debug"]) == 1
    assert data["debug"][0]["rule"] == "rule[0]"
    assert data["debug"][0]["value"] == 9
    assert "row_number" not in data["debug"][0]


def test_cel_evaluate_endpoint_bad_control_type_422(cel_evaluate_client: TestClient) -> None:
    body = {
        "attributes": {},
        "rule_set": {
            "rules": [
                {
                    "expression": '{"stop": true}',
                },
            ],
        },
    }
    r = cel_evaluate_client.post("/import-rules/cel/evaluate", json=body)
    assert r.status_code == 422
