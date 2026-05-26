"""API tests for GET /date-range/resolve (#133)."""

from fastapi.testclient import TestClient

from tallybadger.main import app


def test_resolve_single_expression() -> None:
    client = TestClient(app)
    response = client.get(
        "/date-range/resolve",
        params={"expr": "2026-01-15", "anchor": "2026-05-06T12:00:00Z"},
    )
    assert response.status_code == 200
    assert response.json() == {"date": "2026-01-15", "from_date": None, "to_date": None}


def test_resolve_range() -> None:
    client = TestClient(app)
    response = client.get(
        "/date-range/resolve",
        params={
            "from": "now/y",
            "to": "now",
            "anchor": "2026-05-06T12:00:00Z",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["date"] is None
    assert body["from_date"] == "2026-01-01"
    assert body["to_date"] == "2026-05-06"


def test_resolve_invalid_expression_returns_422() -> None:
    client = TestClient(app)
    response = client.get("/date-range/resolve", params={"expr": "not-a-date"})
    assert response.status_code == 422


def test_resolve_requires_expr_or_range() -> None:
    client = TestClient(app)
    assert client.get("/date-range/resolve").status_code == 422
    assert (
        client.get(
            "/date-range/resolve",
            params={"from": "now", "expr": "now"},
        ).status_code
        == 422
    )
