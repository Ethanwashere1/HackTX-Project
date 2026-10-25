from fastapi.testclient import TestClient

from app.errors import install_error_handlers


def assert_error(resp, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "service": "backend"}


def test_unknown_route_is_404_in_contract_format(client):
    assert_error(client.get("/api/does-not-exist"), 404, "not_found")


def test_wrong_method_is_405_in_contract_format(client):
    assert_error(client.delete("/health"), 405, "method_not_allowed")


def test_validation_error_is_422_in_contract_format(client):
    assert_error(client.post("/api/auth/dev-login", json={"email": "nope"}), 422, "validation_error")


def test_missing_session_is_401(client):
    assert_error(client.get("/api/me"), 401, "unauthenticated")


def test_unhandled_exception_is_500_in_contract_format():
    from fastapi import FastAPI

    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret detail")

    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/boom")
    assert_error(resp, 500, "internal_error")
    assert "secret detail" not in resp.text


def test_cors_allows_frontend_origin_with_credentials(client):
    resp = client.options(
        "/api/me",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert resp.headers["access-control-allow-credentials"] == "true"
