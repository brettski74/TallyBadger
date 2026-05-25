"""Integration tests for GET /parties register filters and sort (#187)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from psycopg import connect
from psycopg.rows import dict_row

from tallybadger.api.routes.ledger import get_ledger_service
from tallybadger.ledger.models import PartyCreate
from tallybadger.ledger.service import LedgerService
from tallybadger.main import app


@pytest.fixture
def ledger_service(integration_db_url: str) -> LedgerService:
    return LedgerService(connection_factory=lambda: connect(integration_db_url, row_factory=dict_row))


@pytest.fixture
def api_client(integration_db_url: str) -> Iterator[TestClient]:
    app.dependency_overrides[get_ledger_service] = lambda: LedgerService(
        connection_factory=lambda: connect(integration_db_url, row_factory=dict_row),
    )
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(get_ledger_service, None)


def _create_party(
    ledger_service: LedgerService,
    *,
    name: str,
    role: str = "both",
    is_active: bool = True,
    subtype: str | None = None,
) -> int:
    payload = PartyCreate(name=name, role=role, is_active=is_active)
    if subtype is not None:
        payload = PartyCreate(name=name, role=role, is_active=is_active, subtype=subtype)
    return ledger_service.create_party(payload).id


def test_list_parties_unfiltered_returns_all(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    tag = uuid.uuid4().hex[:8]
    alpha = f"Alpha Tenant {tag}"
    beta = f"Beta Vendor {tag}"
    _create_party(ledger_service, name=alpha, role="customer")
    _create_party(ledger_service, name=beta, role="vendor", is_active=False)

    rows = api_client.get("/parties").json()
    names = {row["name"] for row in rows}
    assert {alpha, beta}.issubset(names)


def test_list_parties_filters_and_sort(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    tag = uuid.uuid4().hex[:8]
    zulu = f"Zulu Utilities {tag}"
    alpha = f"Alpha Tenant {tag}"
    beta = f"Beta Tenant {tag}"
    no_sub = f"No Subtype Co {tag}"
    _create_party(ledger_service, name=zulu, role="vendor", subtype="Utilities")
    _create_party(ledger_service, name=alpha, role="customer", subtype="Tenant")
    _create_party(ledger_service, name=beta, role="customer", subtype="Tenant")
    _create_party(ledger_service, name=no_sub, role="other", subtype=None)

    active_customers = api_client.get(
        "/parties",
        params={"is_active": True, "roles": ["customer"], "name": tag},
    ).json()
    assert {row["name"] for row in active_customers} == {alpha, beta}

    by_name = api_client.get("/parties", params={"name": f"^beta.*{tag}$"}).json()
    assert len(by_name) == 1
    assert by_name[0]["name"] == beta

    by_subtype = api_client.get(
        "/parties",
        params=[("subtypes", "Tenant"), ("subtypes", "__null__"), ("name", tag)],
    ).json()
    assert {row["name"] for row in by_subtype} == {alpha, beta, no_sub}

    sorted_desc = api_client.get(
        "/parties",
        params={"sort": ["name:desc"], "name": tag},
    ).json()
    assert [row["name"] for row in sorted_desc] == [zulu, no_sub, beta, alpha]

    inactive = api_client.get("/parties", params={"is_active": False, "name": tag}).json()
    assert inactive == []


def test_list_party_subtype_suggestions(
    api_client: TestClient,
    ledger_service: LedgerService,
) -> None:
    tag = uuid.uuid4().hex[:8]
    _create_party(ledger_service, name=f"Subtype A {tag}", role="customer", subtype="Tenant")
    _create_party(ledger_service, name=f"Subtype B {tag}", role="vendor", subtype="Utilities")
    _create_party(ledger_service, name=f"Subtype C {tag}", role="other", subtype="Tenant")
    _create_party(ledger_service, name=f"No Subtype {tag}", role="other", subtype=None)

    suggestions = api_client.get("/parties/subtype-suggestions").json()
    assert suggestions == ["Tenant", "Utilities"]


def test_list_parties_validation_errors(api_client: TestClient) -> None:
    blank_name = api_client.get("/parties", params={"name": "   "})
    assert blank_name.status_code == 422

    bad_regex = api_client.get("/parties", params={"name": "[unclosed"})
    assert bad_regex.status_code == 422
    assert "regular expression" in bad_regex.json()["detail"].lower()

    bad_sort = api_client.get("/parties", params={"sort": ["not_a_field:asc"]})
    assert bad_sort.status_code == 422

    bad_direction = api_client.get("/parties", params={"sort": ["name:up"]})
    assert bad_direction.status_code == 422
