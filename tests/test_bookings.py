from datetime import datetime, timedelta, timezone

from tests.conftest import future


def test_create_booking_uses_server_side_price(client, user, catalog):
    r = client.post(
        "/bookings",
        # a client-sent "amount" must be ignored
        json={"centre_id": catalog["centre_id"], "test_id": catalog["test_id"], "appointment_at": future(), "amount": 1},
        headers=user,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["amount"] == 499.5
    assert body["status"] == "PENDING"


def test_booking_validation(client, user, catalog):
    base = {"centre_id": catalog["centre_id"], "test_id": catalog["test_id"], "appointment_at": future()}
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert client.post("/bookings", json={**base, "appointment_at": past}, headers=user).status_code == 422
    assert client.post("/bookings", json={**base, "appointment_at": "tomorrow-ish"}, headers=user).status_code == 422
    assert client.post("/bookings", json={**base, "test_id": 9999}, headers=user).status_code == 404
    assert client.post("/bookings", json={**base, "centre_id": 9999}, headers=user).status_code == 404
    assert client.post("/bookings", json=base).status_code == 401


def test_users_cannot_see_or_cancel_each_others_bookings(client, booking, other_user, user):
    assert client.get(f"/bookings/{booking['id']}", headers=other_user).status_code == 404
    assert client.post(f"/bookings/{booking['id']}/cancel", headers=other_user).status_code == 404
    assert client.get("/bookings", headers=other_user).json() == []
    assert len(client.get("/bookings", headers=user).json()) == 1


def test_invalid_booking_id(client, user):
    assert client.get("/bookings/9999", headers=user).status_code == 404
    assert client.get("/bookings/abc", headers=user).status_code == 422


def test_cancel_flow(client, booking, user):
    r = client.post(f"/bookings/{booking['id']}/cancel", headers=user)
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert client.post(f"/bookings/{booking['id']}/cancel", headers=user).status_code == 409  # already cancelled
    pay = client.post("/payments/", json={"booking_id": booking["id"]}, headers=user)
    assert pay.status_code == 409  # can't pay a cancelled booking
