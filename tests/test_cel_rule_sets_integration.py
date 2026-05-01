"""Integration tests: persisted CEL rule set CRUD (#37)."""

from __future__ import annotations

from collections.abc import Iterator
import os
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.db_migrations import apply_sql_migrations
from tallybadger.import_rules.cel_rule_set_service import CelRuleSetService
from tallybadger.main import app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def integration_db_url() -> str:
    db_url = os.environ.get("TALLYBADGER_TEST_DATABASE_URL")
    if not db_url:
        pytest.skip("TALLYBADGER_TEST_DATABASE_URL not set; skipping integration tests")
    return db_url


@pytest.fixture(scope="session", autouse=True)
def migrated_database(integration_db_url: str) -> None:
    apply_sql_migrations(integration_db_url)


@pytest.fixture(autouse=True)
def clean_cel_rule_sets(integration_db_url: str) -> Iterator[None]:
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "TRUNCATE TABLE import_templates, cel_rule_sets RESTART IDENTITY CASCADE",
                )
    yield


@pytest.fixture
def cel_client(integration_db_url: str) -> Iterator[TestClient]:
    from tallybadger.api.routes.cel_rule_sets import get_cel_rule_set_service

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    app.dependency_overrides[get_cel_rule_set_service] = lambda: CelRuleSetService(
        connection_factory=connection_factory,
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_cel_rule_set_service, None)


def _sample_rule_set() -> dict:
    return {
        "rules": [
            {
                "id": "r1",
                "sort_order": 10,
                "enabled": True,
                "expression": '{"set": {"tag": "alpha"}}',
                "captures": [],
            },
        ],
    }


def test_cel_rule_set_crud_flow(cel_client: TestClient) -> None:
    create = cel_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "  bank-a  ", "rule_set": _sample_rule_set()},
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["name"] == "bank-a"
    assert body["rule_set"]["rules"][0]["id"] == "r1"
    rid = body["id"]

    listed = cel_client.get("/import-rules/cel/rule-sets")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["id"] == rid
    assert rows[0]["name"] == "bank-a"

    got = cel_client.get(f"/import-rules/cel/rule-sets/{rid}")
    assert got.status_code == 200
    assert got.json()["rule_set"]["rules"][0]["expression"] == '{"set": {"tag": "alpha"}}'

    patched = cel_client.patch(
        f"/import-rules/cel/rule-sets/{rid}",
        json={"name": "bank-b"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "bank-b"

    patched2 = cel_client.patch(
        f"/import-rules/cel/rule-sets/{rid}",
        json={
            "rule_set": {
                "rules": [
                    {
                        "sort_order": 0,
                        "expression": '{"set": {"tag": "beta"}}',
                        "captures": [],
                    },
                ],
            },
        },
    )
    assert patched2.status_code == 200
    assert patched2.json()["rule_set"]["rules"][0]["expression"] == '{"set": {"tag": "beta"}}'

    deleted = cel_client.delete(f"/import-rules/cel/rule-sets/{rid}")
    assert deleted.status_code == 204

    missing = cel_client.get(f"/import-rules/cel/rule-sets/{rid}")
    assert missing.status_code == 404


def test_create_duplicate_name_409(cel_client: TestClient) -> None:
    payload = {"name": "dup", "rule_set": _sample_rule_set()}
    assert cel_client.post("/import-rules/cel/rule-sets", json=payload).status_code == 201
    r2 = cel_client.post("/import-rules/cel/rule-sets", json=payload)
    assert r2.status_code == 409


def test_patch_name_conflict_409(cel_client: TestClient) -> None:
    cel_client.post("/import-rules/cel/rule-sets", json={"name": "a", "rule_set": _sample_rule_set()})
    b = cel_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "b", "rule_set": _sample_rule_set()},
    )
    bid = b.json()["id"]
    r = cel_client.patch(f"/import-rules/cel/rule-sets/{bid}", json={"name": "a"})
    assert r.status_code == 409


def test_get_delete_not_found(cel_client: TestClient) -> None:
    assert cel_client.get("/import-rules/cel/rule-sets/99999").status_code == 404
    assert cel_client.delete("/import-rules/cel/rule-sets/99999").status_code == 404


def test_patch_empty_body_422(cel_client: TestClient) -> None:
    c = cel_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "x", "rule_set": _sample_rule_set()},
    )
    rid = c.json()["id"]
    r = cel_client.patch(f"/import-rules/cel/rule-sets/{rid}", json={})
    assert r.status_code == 422


def test_capture_matcher_label_round_trip(cel_client: TestClient) -> None:
    payload = {
        "name": "with-labels",
        "rule_set": {
            "rules": [
                {
                    "name": "Parse EMT sender",
                    "sort_order": 0,
                    "expression": '{"set": {"x": 1}}',
                    "captures": [
                        {
                            "attribute": "description",
                            "pattern": r".*",
                            "flags": [],
                            "label": "Interac description line",
                        },
                    ],
                },
            ],
        },
    }
    create = cel_client.post("/import-rules/cel/rule-sets", json=payload)
    assert create.status_code == 201, create.text
    rid = create.json()["id"]
    got = cel_client.get(f"/import-rules/cel/rule-sets/{rid}")
    assert got.status_code == 200
    cap = got.json()["rule_set"]["rules"][0]["captures"][0]
    assert cap["label"] == "Interac description line"
    assert cap["attribute"] == "description"
