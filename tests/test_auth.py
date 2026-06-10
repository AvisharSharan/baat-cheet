from fastapi.testclient import TestClient

from app.auth import CurrentUser, create_access_token, user_from_token
from app.main import app


def test_jwt_round_trip(monkeypatch):
    monkeypatch.setenv("LOCAL_AUTH_USERNAME", "avi")
    monkeypatch.setenv("LOCAL_AUTH_PASSWORD", "secret")
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    token = create_access_token(CurrentUser(username="avi"))

    assert user_from_token(token).username == "avi"


def test_meetings_require_auth():
    client = TestClient(app)

    response = client.get("/api/meetings")

    assert response.status_code == 401


def test_login_returns_bearer_token(monkeypatch):
    monkeypatch.setenv("LOCAL_AUTH_USERNAME", "avi")
    monkeypatch.setenv("LOCAL_AUTH_PASSWORD", "secret")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    client = TestClient(app)

    response = client.post("/api/auth/login", json={"username": "avi", "password": "secret"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["username"] == "avi"
    assert user_from_token(payload["access_token"]).username == "avi"


def test_authenticated_meetings_list(monkeypatch):
    monkeypatch.setenv("LOCAL_AUTH_USERNAME", "avi")
    monkeypatch.setenv("LOCAL_AUTH_PASSWORD", "secret")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    client = TestClient(app)
    token = client.post("/api/auth/login", json={"username": "avi", "password": "secret"}).json()["access_token"]

    response = client.get("/api/meetings", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
