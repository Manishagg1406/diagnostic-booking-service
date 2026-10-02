from tests.conftest import PASSWORD


def test_signup_and_login(client):
    r = client.post("/auth/signup", json={"email": "A@Example.com", "password": PASSWORD})
    assert r.status_code == 201
    assert r.json()["email"] == "a@example.com"  # normalised
    assert "password" not in r.text

    r = client.post("/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == "a@example.com"


def test_duplicate_signup_conflict(client):
    body = {"email": "a@example.com", "password": PASSWORD}
    assert client.post("/auth/signup", json=body).status_code == 201
    assert client.post("/auth/signup", json=body).status_code == 409


def test_signup_validation(client):
    assert client.post("/auth/signup", json={"email": "not-an-email", "password": PASSWORD}).status_code == 422
    assert client.post("/auth/signup", json={"email": "a@example.com", "password": "short"}).status_code == 422
    assert client.post("/auth/signup", json={"email": "a@example.com"}).status_code == 422


def test_login_wrong_password_and_unknown_user_look_the_same(client):
    client.post("/auth/signup", json={"email": "a@example.com", "password": PASSWORD})
    wrong = client.post("/auth/login", json={"email": "a@example.com", "password": "wrongpassword"})
    unknown = client.post("/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_protected_routes_reject_missing_or_bad_token(client):
    assert client.get("/bookings").status_code == 401
    assert client.get("/bookings", headers={"Authorization": "Bearer garbage"}).status_code == 401
