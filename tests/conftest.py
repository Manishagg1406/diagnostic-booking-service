import os

# Must be set before the app is imported.
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret-12345"
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["DATABASE_URL"] = "sqlite://"

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app

PASSWORD = "supersecret123"


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)  # no `with`: we create tables ourselves, skip lifespan
    c.session_factory = Session
    yield c
    app.dependency_overrides.clear()
    engine.dispose()


def auth_headers(client, email="user@example.com"):
    client.post("/auth/signup", json={"email": email, "password": PASSWORD})
    token = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin(client):
    return auth_headers(client, "admin@example.com")


@pytest.fixture()
def user(client):
    return auth_headers(client, "user@example.com")


@pytest.fixture()
def other_user(client):
    return auth_headers(client, "other@example.com")


@pytest.fixture()
def catalog(client, admin):
    """One test, one centre offering it at 499.50."""
    test = client.post("/tests", json={"name": "CBC"}, headers=admin).json()
    centre = client.post("/centres", json={"name": "EVE Central", "location": "Gurugram"}, headers=admin).json()
    r = client.post(f"/centres/{centre['id']}/tests", json={"test_id": test["id"], "price": "499.50"}, headers=admin)
    assert r.status_code == 201
    return {"test_id": test["id"], "centre_id": centre["id"]}


def future(days=2):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest.fixture()
def booking(client, user, catalog):
    r = client.post(
        "/bookings",
        json={"centre_id": catalog["centre_id"], "test_id": catalog["test_id"], "appointment_at": future()},
        headers=user,
    )
    assert r.status_code == 201, r.text
    return r.json()


def send_webhook(client, payload, secret="test-webhook-secret", signature=None):
    body = json.dumps(payload).encode()
    sig = signature if signature is not None else hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post(
        "/payments/webhook/", content=body, headers={"Content-Type": "application/json", "X-Webhook-Signature": sig}
    )
