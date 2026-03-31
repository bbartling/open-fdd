from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from open_fdd.platform.api.main import app

client = TestClient(app)


def _set_phase1_env(monkeypatch):
    ph = PasswordHasher()
    monkeypatch.setenv("OFDD_APP_USER", "openfdd")
    monkeypatch.setenv("OFDD_APP_USER_HASH", ph.hash("pass1234"))
    monkeypatch.setenv("OFDD_JWT_SECRET", "unit-test-secret-32-bytes-minimum")
    monkeypatch.setenv("OFDD_ACCESS_TOKEN_MINUTES", "60")
    monkeypatch.setenv("OFDD_REFRESH_TOKEN_DAYS", "7")


def test_login_and_access_token_flow(monkeypatch):
    _set_phase1_env(monkeypatch)
    r0 = client.get("/capabilities")
    assert r0.status_code == 401

    login = client.post(
        "/auth/login", json={"username": "openfdd", "password": "pass1234"}
    )
    assert login.status_code == 200
    body = login.json()
    assert "access_token" in body and "refresh_token" in body

    r1 = client.get(
        "/capabilities",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert r1.status_code == 200


def test_refresh_issues_new_access_token(monkeypatch):
    _set_phase1_env(monkeypatch)
    login = client.post(
        "/auth/login", json={"username": "openfdd", "password": "pass1234"}
    )
    refresh_token = login.json()["refresh_token"]
    refresh = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh.status_code == 200
    assert refresh.json().get("access_token")

