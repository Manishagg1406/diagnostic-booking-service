from sqlalchemy import func, select

from app.models import Payment, WebhookEvent
from tests.conftest import send_webhook


def count(client, model):
    with client.session_factory() as db:
        return db.scalar(select(func.count()).select_from(model))


# ---------- POST /payments/ ----------
def test_successful_payment_confirms_booking(client, booking, user):
    r = client.post("/payments/", json={"booking_id": booking["id"], "simulate": "SUCCESS"}, headers=user)
    assert r.status_code == 201
    assert r.json()["status"] == "SUCCESS" and r.json()["booking_status"] == "CONFIRMED"
    assert client.get(f"/bookings/{booking['id']}", headers=user).json()["status"] == "CONFIRMED"


def test_failed_payment_marks_booking_failed(client, booking, user):
    r = client.post("/payments/", json={"booking_id": booking["id"], "simulate": "FAILED"}, headers=user)
    assert r.status_code == 201
    assert r.json()["booking_status"] == "FAILED"
    # booking is terminal now: paying again is rejected
    assert client.post("/payments/", json={"booking_id": booking["id"]}, headers=user).status_code == 409


def test_cannot_pay_twice(client, booking, user):
    assert client.post("/payments/", json={"booking_id": booking["id"], "simulate": "SUCCESS"}, headers=user).status_code == 201
    assert client.post("/payments/", json={"booking_id": booking["id"], "simulate": "SUCCESS"}, headers=user).status_code == 409
    assert count(client, Payment) == 1


def test_payment_authorization_and_validation(client, booking, other_user):
    assert client.post("/payments/", json={"booking_id": booking["id"]}).status_code == 401
    assert client.post("/payments/", json={"booking_id": booking["id"]}, headers=other_user).status_code == 404
    assert client.post("/payments/", json={"booking_id": 9999}, headers=other_user).status_code == 404
    assert client.post("/payments/", json={}, headers=other_user).status_code == 422


# ---------- POST /payments/webhook/ ----------
def test_webhook_confirms_booking(client, booking, user):
    r = send_webhook(client, {"event_id": "evt_1", "booking_id": booking["id"], "status": "SUCCESS"})
    assert r.status_code == 200
    assert r.json() == {"result": "processed", "booking_id": booking["id"], "booking_status": "CONFIRMED"}
    assert client.get(f"/bookings/{booking['id']}", headers=user).json()["status"] == "CONFIRMED"


def test_webhook_is_idempotent(client, booking, user):
    payload = {"event_id": "evt_dup", "booking_id": booking["id"], "status": "SUCCESS"}
    results = [send_webhook(client, payload) for _ in range(3)]
    assert all(r.status_code == 200 for r in results)
    assert [r.json()["result"] for r in results] == ["processed", "duplicate", "duplicate"]
    assert all(r.json()["booking_status"] == "CONFIRMED" for r in results)
    assert count(client, Payment) == 1
    assert count(client, WebhookEvent) == 1
    assert len(client.get("/bookings", headers=user).json()) == 1  # no duplicate bookings


def test_duplicate_failed_webhook_is_also_idempotent(client, booking):
    payload = {"event_id": "evt_f", "booking_id": booking["id"], "status": "FAILED"}
    assert send_webhook(client, payload).json()["booking_status"] == "FAILED"
    assert send_webhook(client, payload).json()["result"] == "duplicate"
    assert count(client, Payment) == 1


def test_late_failed_webhook_does_not_corrupt_confirmed_booking(client, booking, user):
    send_webhook(client, {"event_id": "evt_ok", "booking_id": booking["id"], "status": "SUCCESS"})
    r = send_webhook(client, {"event_id": "evt_late", "booking_id": booking["id"], "status": "FAILED"})
    assert r.status_code == 200 and r.json()["result"] == "ignored"
    assert client.get(f"/bookings/{booking['id']}", headers=user).json()["status"] == "CONFIRMED"
    assert count(client, Payment) == 1


def test_webhook_success_after_cancel_is_ignored(client, booking, user):
    client.post(f"/bookings/{booking['id']}/cancel", headers=user)
    r = send_webhook(client, {"event_id": "evt_c", "booking_id": booking["id"], "status": "SUCCESS"})
    assert r.json()["result"] == "ignored" and r.json()["booking_status"] == "CANCELLED"
    assert count(client, Payment) == 0


def test_webhook_rejects_bad_signature_unknown_booking_and_bad_payload(client, booking):
    ok = {"event_id": "evt_x", "booking_id": booking["id"], "status": "SUCCESS"}
    assert send_webhook(client, ok, signature="deadbeef").status_code == 401
    assert send_webhook(client, ok, secret="wrong-secret").status_code == 401
    assert client.post("/payments/webhook/", json=ok).status_code == 401  # no signature header at all
    assert send_webhook(client, {**ok, "booking_id": 9999}).status_code == 404
    assert send_webhook(client, {**ok, "status": "MAYBE"}).status_code == 422
    assert send_webhook(client, {"booking_id": booking["id"], "status": "SUCCESS"}).status_code == 422  # no event_id
    assert count(client, Payment) == 0 and count(client, WebhookEvent) == 0
