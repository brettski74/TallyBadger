from fastapi.testclient import TestClient

from tallybadger.main import app

client = TestClient(app)


def test_cel_evaluate_endpoint_happy_path() -> None:
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
    r = client.post("/import-rules/cel/evaluate", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["attributes"]["party"] == "BOB"
    assert data["attributes"]["amount"] == 150.5
    assert data["require_review"] is True
    assert data["review_reason"] == "confirm party"


def test_cel_evaluate_endpoint_bad_control_type_422() -> None:
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
    r = client.post("/import-rules/cel/evaluate", json=body)
    assert r.status_code == 422
