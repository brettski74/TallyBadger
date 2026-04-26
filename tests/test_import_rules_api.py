"""API tests for POST /import-rules/evaluate."""

from fastapi.testclient import TestClient

from tallybadger.main import app

client = TestClient(app)


def test_evaluate_endpoint_happy_path() -> None:
    body = {
        "attributes": {"description": "EMT - BOB, ref 1"},
        "rule_set": {
            "rules": [
                {
                    "id": "emt",
                    "sort_order": 10,
                    "matchers": [
                        {
                            "type": "regex",
                            "attribute": "description",
                            "pattern": r"EMT\s*-\s*(?P<sender>[^,]+),",
                            "flags": [],
                        },
                    ],
                    "actions": [
                        {
                            "type": "set_attribute",
                            "name": "party_name_hint",
                            "from_regex_group": {"matcher_index": 0, "group": "sender"},
                        },
                    ],
                },
            ],
        },
    }
    r = client.post("/import-rules/evaluate", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["attributes"]["party_name_hint"].strip() == "BOB"
    assert data["dropped"] is False
    assert any(e["event"] == "rule_matched" for e in data["trace"])


def test_evaluate_invalid_regex_group_422() -> None:
    body = {
        "attributes": {"d": "x"},
        "rule_set": {
            "rules": [
                {
                    "matchers": [{"type": "regex", "attribute": "d", "pattern": "x"}],
                    "actions": [
                        {
                            "type": "set_attribute",
                            "name": "y",
                            "from_regex_group": {"matcher_index": 0, "group": 99},
                        },
                    ],
                },
            ],
        },
    }
    r = client.post("/import-rules/evaluate", json=body)
    assert r.status_code == 422
