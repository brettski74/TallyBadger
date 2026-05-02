"""Integration tests: import template CRUD (#38)."""

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
from tallybadger.import_templates.service import ImportTemplateService
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
def clean_import_templates(integration_db_url: str) -> Iterator[None]:
    with connect(integration_db_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "TRUNCATE TABLE import_templates, cel_rule_sets RESTART IDENTITY CASCADE",
                )
    yield


@pytest.fixture
def import_api_client(integration_db_url: str) -> Iterator[TestClient]:
    from tallybadger.api.routes.cel_rule_sets import get_cel_rule_set_service
    from tallybadger.api.routes.import_templates import get_import_template_service

    @contextmanager
    def connection_factory():
        with connect(integration_db_url, row_factory=dict_row) as conn:
            yield conn

    app.dependency_overrides[get_cel_rule_set_service] = lambda: CelRuleSetService(
        connection_factory=connection_factory,
    )
    app.dependency_overrides[get_import_template_service] = lambda: ImportTemplateService(
        connection_factory=connection_factory,
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_cel_rule_set_service, None)
    app.dependency_overrides.pop(get_import_template_service, None)


def _sample_rule_set() -> dict:
    return {
        "rules": [
            {
                "sort_order": 0,
                "expression": '{"set": {"x": 1}}',
                "captures": [],
            },
        ],
    }


def _sample_columns() -> list[dict]:
    return [
        {"attribute_name": "posted_on", "data_type": "date", "date_format": "YYYY-MM-DD"},
        {"attribute_name": None, "data_type": "string"},
        {"attribute_name": "amount", "data_type": "numeric"},
    ]


def test_import_template_crud_with_rule_set(import_api_client: TestClient) -> None:
    rs = import_api_client.post(
        "/import-rules/cel/rule-sets",
        json={"name": "bank-a", "rule_set": _sample_rule_set()},
    )
    assert rs.status_code == 201, rs.text
    rs_id = rs.json()["id"]

    create = import_api_client.post(
        "/import-templates",
        json={
            "name": "  tpl-one  ",
            "has_header_row": True,
            "columns": _sample_columns(),
            "cel_rule_set_id": rs_id,
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["name"] == "tpl-one"
    assert body["has_header_row"] is True
    assert body["cel_rule_set_id"] == rs_id
    assert len(body["columns"]) == 3
    assert body["columns"][0]["date_format"] == "YYYY-MM-DD"
    tid = body["id"]

    listed = import_api_client.get("/import-templates")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "tpl-one"

    got = import_api_client.get(f"/import-templates/{tid}")
    assert got.status_code == 200

    cleared = import_api_client.patch(
        f"/import-templates/{tid}",
        json={"cel_rule_set_id": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["cel_rule_set_id"] is None

    patched = import_api_client.patch(
        f"/import-templates/{tid}",
        json={"name": "tpl-two", "has_header_row": False},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "tpl-two"
    assert patched.json()["has_header_row"] is False

    deleted = import_api_client.delete(f"/import-templates/{tid}")
    assert deleted.status_code == 204
    assert import_api_client.get(f"/import-templates/{tid}").status_code == 404


def test_create_duplicate_name_409(import_api_client: TestClient) -> None:
    payload = {
        "name": "dup",
        "has_header_row": False,
        "columns": _sample_columns(),
    }
    assert import_api_client.post("/import-templates", json=payload).status_code == 201
    r2 = import_api_client.post("/import-templates", json=payload)
    assert r2.status_code == 409


def test_invalid_rule_set_fk_422(import_api_client: TestClient) -> None:
    r = import_api_client.post(
        "/import-templates",
        json={
            "name": "bad-fk",
            "columns": [],
            "cel_rule_set_id": 99999,
        },
    )
    assert r.status_code == 422


def test_date_column_missing_format_422(import_api_client: TestClient) -> None:
    r = import_api_client.post(
        "/import-templates",
        json={
            "name": "bad-col",
            "columns": [{"attribute_name": "d", "data_type": "date"}],
        },
    )
    assert r.status_code == 422


def test_patch_empty_422(import_api_client: TestClient) -> None:
    c = import_api_client.post(
        "/import-templates",
        json={"name": "x", "columns": []},
    )
    tid = c.json()["id"]
    r = import_api_client.patch(f"/import-templates/{tid}", json={})
    assert r.status_code == 422


def test_date_column_posix_format_rejected_422(import_api_client: TestClient) -> None:
    r = import_api_client.post(
        "/import-templates",
        json={
            "name": "bad-date-format",
            "columns": [{"attribute_name": "d", "data_type": "date", "date_format": "%Y-%m-%d"}],
        },
    )
    assert r.status_code == 422
