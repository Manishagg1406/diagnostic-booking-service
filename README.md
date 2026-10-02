# Diagnostic Booking Service

**Author:** Manish Aggarwal · [GitHub](https://github.com/Manishagg1406)

A backend service for booking diagnostic tests with a **simulated payment flow** and an **idempotent payment webhook**.
Built with **FastAPI + SQLAlchemy 2 + PostgreSQL** (SQLite works out of the box for quick local runs).

## Features
- Signup / login with JWT (bcrypt password hashing, request validation via Pydantic)
- Diagnostic tests, centres, and per-centre test prices (admin-managed, publicly readable, paginated)
- Bookings with a state machine: `PENDING → CONFIRMED | FAILED | CANCELLED`
- Mock payment endpoint (`POST /payments/`) that results in `SUCCESS` or `FAILED` and updates the booking
- Idempotent, HMAC-signed webhook (`POST /payments/webhook/`)
- Swagger UI at `/docs`, pagination, logging, 24 automated tests, Dockerfile + docker-compose

## Run locally

### Option 1: plain Python (SQLite by default)
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux
uvicorn app.main:app --reload
```
API: http://localhost:8000 · Swagger UI: http://localhost:8000/docs

Tables are created automatically on startup. To use PostgreSQL, set `DATABASE_URL` in `.env`
(for example `postgresql+psycopg2://user:password@localhost:5432/dbname`).

### Option 2: Docker (PostgreSQL)
```bash
docker compose up --build
```
> Note: the Docker setup is included, but I have not run it locally (Docker is not installed on my machine). I developed and tested the app and the test suite with SQLite.

### Run the tests
```bash
pytest
```
Tests use an in-memory SQLite database, so no setup is needed (24 tests).

### Configuration (`.env`, see `.env.example`)
| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL (default `sqlite:///./eve.db`) |
| `JWT_SECRET`, `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT signing and token lifetime |
| `WEBHOOK_SECRET` | Shared secret used to sign webhook requests (HMAC) |
| `ADMIN_EMAILS` | Comma-separated emails that become admins when they sign up |
| `PAYMENT_SUCCESS_RATE` | Chance that the mock payment succeeds (default `0.8`) |

> To get an admin user: make sure `ADMIN_EMAILS` contains your email in `.env`, **then** sign up with that email. Admin status is set at signup.

## API overview

| Method & path | Auth | Description |
|---|---|---|
| `POST /auth/signup` | none | Create an account |
| `POST /auth/login` | none | Returns a JWT access token |
| `GET /auth/me` | user | Current user |
| `POST /tests`, `GET /tests` | admin / none | Create / list diagnostic tests |
| `POST /centres`, `GET /centres` | admin / none | Create / list centres (`?location=&test_id=&limit=&offset=`) |
| `GET /centres/{id}` | none | Centre with its tests and prices |
| `POST /centres/{id}/tests` | admin | Offer a test at a centre with a price |
| `POST /bookings` | user | Create a booking (status `PENDING`) |
| `GET /bookings`, `GET /bookings/{id}` | user | Own bookings only |
| `POST /bookings/{id}/cancel` | user | Cancel a `PENDING` or `CONFIRMED` booking |
| `POST /payments/` | user | Mock payment for a booking |
| `POST /payments/webhook/` | HMAC signature | Callback from the (simulated) payment provider |

The easiest way to try everything is the Swagger UI at `/docs`: log in, click **Authorize**, and paste the token (without quotes).

### Example requests
```bash
# Sign up and log in (email must be in ADMIN_EMAILS to become an admin)
curl -X POST http://localhost:8000/auth/signup -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"supersecret123"}'
curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"supersecret123"}'
# -> {"access_token":"<JWT>","token_type":"bearer"}

# Admin: create a test, a centre, and the test's price at that centre
curl -X POST http://localhost:8000/tests -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" -d '{"name":"CBC"}'
curl -X POST http://localhost:8000/centres -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" -d '{"name":"City Lab","location":"Delhi"}'
curl -X POST http://localhost:8000/centres/1/tests -H "Authorization: Bearer <ADMIN_JWT>" \
  -H "Content-Type: application/json" -d '{"test_id":1,"price":"499.50"}'

# User: book the test, then pay
curl -X POST http://localhost:8000/bookings -H "Authorization: Bearer <USER_JWT>" \
  -H "Content-Type: application/json" \
  -d '{"centre_id":1,"test_id":1,"appointment_at":"2030-01-15T10:00:00+05:30"}'
curl -X POST http://localhost:8000/payments/ -H "Authorization: Bearer <USER_JWT>" \
  -H "Content-Type: application/json" -d '{"booking_id":1}'
```
`POST /payments/` also accepts an optional `"simulate": "SUCCESS"` or `"FAILED"` to force the outcome (useful for demos and tests).

### Webhook
Payload: `{"event_id": "<unique id from the provider>", "booking_id": 1, "status": "SUCCESS" | "FAILED"}`

The provider signs the **raw request body** with HMAC-SHA256 (key = `WEBHOOK_SECRET`) and sends the hex digest in the `X-Webhook-Signature` header. A small Python script to try it:

```python
import hmac, hashlib, json, httpx

SECRET = b"<your WEBHOOK_SECRET from .env>"
body = json.dumps({"event_id": "evt_1", "booking_id": 1, "status": "SUCCESS"}).encode()
sig = hmac.new(SECRET, body, hashlib.sha256).hexdigest()

for _ in range(2):  # send the same event twice
    r = httpx.post("http://localhost:8000/payments/webhook/", content=body,
                   headers={"X-Webhook-Signature": sig, "Content-Type": "application/json"})
    print(r.status_code, r.json())
```
Expected output (the booking must be `PENDING` before the first call):
```
200 {'result': 'processed', 'booking_id': 1, 'booking_status': 'CONFIRMED'}
200 {'result': 'duplicate', 'booking_id': 1, 'booking_status': 'CONFIRMED'}
```

Possible results (all HTTP 200, so the provider stops retrying):
- `processed`: the event changed the booking's state
- `duplicate`: this `event_id` was already handled, nothing changed
- `ignored`: the event is valid but the booking's current state doesn't allow the change (for example a late `FAILED` event for an already `CONFIRMED` booking)

## Database design
```
users(id, email UNIQUE, password_hash, is_admin, created_at)
diagnostic_tests(id, name UNIQUE)
centres(id, name, location)
centre_tests(id, centre_id FK, test_id FK, price, UNIQUE(centre_id, test_id), CHECK price > 0)
bookings(id, user_id FK, centre_id FK, test_id FK, appointment_at, amount, status, created_at, updated_at)
payments(id, booking_id FK, amount, status, source [API|WEBHOOK], reference UNIQUE, created_at)
webhook_events(id, event_id UNIQUE, booking_id FK, reported_status, outcome [APPLIED|IGNORED], created_at)
```
- **`centre_tests`** links centres and tests (many-to-many) and stores the price, because the same test can cost different amounts at different centres.
- **`bookings.amount`** is a snapshot of the price at booking time, so later price changes don't alter old bookings. Money uses `NUMERIC(10,2)`, never floats.
- **Idempotency is enforced by the database**, not only by code: `webhook_events.event_id` and `payments.reference` are `UNIQUE`.

## Design notes
- **Layers:** routers (HTTP only) → services (business rules and transactions) → models. Domain errors are mapped to HTTP responses in one place (`app/main.py`).
- **State machine** (`app/services/state.py`): the only place where booking status changes. Allowed: `PENDING → CONFIRMED / FAILED / CANCELLED` and `CONFIRMED → CANCELLED`. `FAILED` and `CANCELLED` are final.
- **Webhook idempotency:** (1) lock the booking row (`SELECT … FOR UPDATE`), (2) check whether the `event_id` was already processed and return early if so, (3) otherwise apply the change and save the event and payment in one transaction, (4) if two identical requests race, the UNIQUE constraint rejects the second one and it is answered as `duplicate`.
- **Security:** bcrypt password hashes; the same error for a wrong password and an unknown email; other users' bookings return 404 (not 403) so IDs can't be guessed; the price is always computed on the server; the webhook is authenticated with an HMAC signature (constant-time comparison).

## Edge cases handled
- Missing, invalid or expired JWT → 401
- Non-admin trying to change the catalogue → 403
- Invalid booking ID, or someone else's booking → 404
- Invalid request bodies → 422
- Appointment time in the past → 422
- Centre does not offer the requested test → 404
- Duplicate signup / test / centre offering → 409
- Paying for a booking that is not `PENDING` → 409
- Cancelling an already cancelled or failed booking → 409
- Repeated webhook events, and late or out-of-order webhook events
- Wrong or missing webhook signature → 401; unknown booking in webhook → 404

## Assumptions
- Appointment times are stored in UTC; a time without timezone is treated as UTC.
- If a payment fails, the booking becomes `FAILED` and the user creates a new booking to retry.
- A confirmed booking can be cancelled; refunds are out of scope.
- Admins are identified by the `ADMIN_EMAILS` setting (a simple stand-in for real role management).

## What I'd improve with more time
- **Database migrations (Alembic):** right now tables are created on startup; migrations would let me change the schema safely.
- **Appointment slots:** limit how many bookings a centre can take per time slot and prevent double-booking.
- **Payment retries and refunds:** allow another payment attempt after a failure, and refund when a confirmed booking is cancelled.
- **Better auth:** refresh tokens, password reset, and proper roles instead of the `ADMIN_EMAILS` shortcut.
- **Test on real PostgreSQL:** I tested with SQLite; I would add tests against PostgreSQL, especially for concurrent webhooks.

## Note on AI assistance
I used an AI assistant (Claude) to help scaffold and review this project. I ran the tests and the full booking, payment and webhook flow locally.