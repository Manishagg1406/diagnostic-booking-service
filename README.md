# EVE Diagnostics Booking Service

Backend service for booking diagnostic tests with a **simulated payment flow** and an **idempotent payment webhook**.
Built with **FastAPI + SQLAlchemy 2 + PostgreSQL** (SQLite works out of the box for quick local runs).

## Features
- Signup / login with JWT (bcrypt password hashing, request validation via Pydantic)
- Diagnostic tests, centres, and per-centre test prices (admin-managed, publicly readable, paginated)
- Bookings with a state machine: `PENDING → CONFIRMED | FAILED | CANCELLED`
- Mock payment endpoint (`POST /payments/`) that results in `SUCCESS` or `FAILED` and updates the booking
- Idempotent, HMAC-signed webhook (`POST /payments/webhook/`)
- Swagger UI at `/docs`, pagination, structured logging, 24 automated tests, Docker + docker-compose

## Run locally

### Option 1: Docker (PostgreSQL)
```bash
docker compose up --build
```
API: http://localhost:8000 — Swagger: http://localhost:8000/docs

### Option 2: plain Python (SQLite by default)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional; set DATABASE_URL to use Postgres
uvicorn app.main:app --reload
```
Tables are created on startup.

### Tests
```bash
pytest
```
Tests use an in-memory SQLite database, so no setup is needed.

### Configuration (env vars, see `.env.example`)
| Var | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL (default `sqlite:///./eve.db`) |
| `JWT_SECRET`, `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT signing |
| `WEBHOOK_SECRET` | HMAC secret shared with the payment provider |
| `ADMIN_EMAILS` | Comma-separated emails that become admins on signup |
| `PAYMENT_SUCCESS_RATE` | Chance the mock payment succeeds (default 0.8) |

## API overview

| Method & path | Auth | Description |
|---|---|---|
| `POST /auth/signup` | – | Create account |
| `POST /auth/login` | – | Returns JWT |
| `GET /auth/me` | user | Current user |
| `POST /tests`, `GET /tests` | admin / – | Manage / list diagnostic tests |
| `POST /centres`, `GET /centres` | admin / – | Create / list centres (`?location=&test_id=&limit=&offset=`) |
| `GET /centres/{id}` | – | Centre with its tests and prices |
| `POST /centres/{id}/tests` | admin | Offer a test at a price |
| `POST /bookings` | user | Create booking (status `PENDING`) |
| `GET /bookings`, `GET /bookings/{id}` | user | Own bookings only |
| `POST /bookings/{id}/cancel` | user | Cancel a PENDING or CONFIRMED booking |
| `POST /payments/` | user | Mock payment for a booking |
| `POST /payments/webhook/` | HMAC signature | Payment-provider callback |

### Example requests
```bash
# 1. Sign up the admin (email must be in ADMIN_EMAILS) and a normal user, then log in
curl -X POST localhost:8000/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"supersecret123"}'
curl -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"supersecret123"}'
# -> {"access_token":"<JWT>","token_type":"bearer"}
ADMIN="Authorization: Bearer <JWT>"

# 2. Admin creates a test, a centre, and prices the test at that centre
curl -X POST localhost:8000/tests   -H "$ADMIN" -H 'Content-Type: application/json' -d '{"name":"CBC"}'
curl -X POST localhost:8000/centres -H "$ADMIN" -H 'Content-Type: application/json' \
  -d '{"name":"EVE Central","location":"Gurugram"}'
curl -X POST localhost:8000/centres/1/tests -H "$ADMIN" -H 'Content-Type: application/json' \
  -d '{"test_id":1,"price":"499.50"}'

# 3. A user books the test (log in as a normal user first -> USER header)
curl -X POST localhost:8000/bookings -H "$USER" -H 'Content-Type: application/json' \
  -d '{"centre_id":1,"test_id":1,"appointment_at":"2030-01-15T10:00:00+05:30"}'

# 4. Mock payment (optional "simulate": "SUCCESS" | "FAILED" forces the outcome)
curl -X POST localhost:8000/payments/ -H "$USER" -H 'Content-Type: application/json' \
  -d '{"booking_id":1}'
```

### Webhook
Payload: `{"event_id": "<unique id from provider>", "booking_id": 1, "status": "SUCCESS" | "FAILED"}`.
The provider signs the **raw request body** with HMAC-SHA256 (key = `WEBHOOK_SECRET`) and sends the hex digest in `X-Webhook-Signature`.
```bash
BODY='{"event_id":"evt_123","booking_id":1,"status":"SUCCESS"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "dev-webhook-secret" | awk '{print $NF}')
curl -X POST localhost:8000/payments/webhook/ -H 'Content-Type: application/json' \
  -H "X-Webhook-Signature: $SIG" -d "$BODY"
# -> {"result":"processed","booking_id":1,"booking_status":"CONFIRMED"}
# send it again -> {"result":"duplicate", ...} and nothing changes
```
Responses: `processed` (state changed), `duplicate` (event already seen), `ignored` (event is valid but the booking's current state doesn't allow the change, e.g. late `FAILED` for a `CONFIRMED` booking). All three return HTTP 200 so the provider stops retrying.

## Database design
```
users(id, email UNIQUE, password_hash, is_admin, created_at)
diagnostic_tests(id, name UNIQUE)
centres(id, name, location)
centre_tests(id, centre_id FK, test_id FK, price, UNIQUE(centre_id, test_id), CHECK price > 0)
bookings(id, user_id FK, centre_id FK, test_id FK, appointment_at, amount, status, created_at, updated_at)
payments(id, booking_id FK, amount, status, source[API|WEBHOOK], reference UNIQUE, created_at)
webhook_events(id, event_id UNIQUE, booking_id FK, reported_status, outcome[APPLIED|IGNORED], created_at)
```
- **`centre_tests`** is the many-to-many between centres and tests and holds the price, because the same test can cost different amounts at different centres.
- **`bookings.amount`** is a snapshot of the price at booking time, so later price edits don't change old bookings. Money uses `NUMERIC(10,2)`, never floats.
- **Idempotency** is enforced by the database, not just by code: `webhook_events.event_id` and `payments.reference` are `UNIQUE`.

## Design notes
- **Layering:** routers (HTTP only) → services (business rules, transactions) → models. Domain errors (`AppError`) are mapped to HTTP responses in one place.
- **State machine** (`app/services/state.py`): the only place booking status changes. Allowed: `PENDING → CONFIRMED/FAILED/CANCELLED`, `CONFIRMED → CANCELLED`. `FAILED` and `CANCELLED` are terminal.
- **Webhook idempotency:** (1) lock the booking row (`SELECT … FOR UPDATE`), (2) look up `event_id` and return early if seen, (3) otherwise apply the change and insert `webhook_events` + `payments` in one transaction, (4) if two identical requests race, the UNIQUE constraint rejects the loser and we answer `duplicate`.
- **Security:** bcrypt hashes; identical error for wrong password vs. unknown email; other users' bookings return 404 (not 403) so IDs can't be probed; price is always computed server-side; webhook is authenticated by HMAC with constant-time comparison.

## Edge cases handled
Invalid/missing/expired JWT (401) · non-admin catalogue changes (403) · invalid or someone else's booking ID (404) · invalid payloads (422) · past appointment (422) · centre doesn't offer the test (404) · duplicate signup/test/offering (409) · paying a non-PENDING booking (409) · cancelling an already cancelled/failed booking (409) · duplicate webhook events · late/out-of-order webhooks · bad webhook signature (401) · unknown booking in webhook (404).

## Assumptions
- `appointment_at` is stored in UTC; a timestamp without timezone is treated as UTC.
- A failed payment makes the booking `FAILED` (terminal); the user creates a new booking to retry.
- Cancelling a `CONFIRMED` booking is allowed; refunds are out of scope.
- Admins are identified by `ADMIN_EMAILS` (simple stand-in for real role management).
- The mock `POST /payments/` and the webhook are two independent routes to the same state machine; whichever arrives first wins and the other is rejected/ignored.
- No double-booking / slot capacity is modelled.

## What I'd improve with more time
- Alembic migrations instead of `create_all`
- Refresh tokens, password reset, email verification, proper roles/permissions
- Appointment slots with capacity and double-booking prevention
- Retry-friendly payments (multiple attempts per booking) and refunds
- Webhook timestamp in the signature to prevent replay; background processing (Celery) with retries
- Rate limiting, Redis caching for the centre catalogue, request-ID based structured JSON logs
- Concurrency tests against real PostgreSQL in CI
