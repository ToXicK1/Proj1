from tests.helpers import PASSWORD, latest_email, signup_verify_login, verify_token_from


def test_signup_returns_same_response_for_new_and_existing_email(client, engine):
    body = {"email": "a@example.com", "password": PASSWORD, "display_name": "A"}
    r1 = client.post("/api/v1/auth/signup", json=body)
    r2 = client.post("/api/v1/auth/signup", json=body)
    assert r1.status_code == r2.status_code == 202
    assert r1.json() == r2.json()
    # The existing account gets a notice instead of a second account.
    assert "Someone tried to register" in latest_email(engine, "signup_existing_account", "a@example.com")


def test_email_is_normalized(client, engine):
    client.post(
        "/api/v1/auth/signup",
        json={"email": "  Mixed@Example.COM ", "password": PASSWORD, "display_name": "M"},
    )
    token = verify_token_from(engine, "mixed@example.com")
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200


def test_login_blocked_until_email_verified(client):
    client.post("/api/v1/auth/signup", json={"email": "b@example.com", "password": PASSWORD, "display_name": "B"})
    r = client.post("/api/v1/auth/login", json={"email": "b@example.com", "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["code"] == "email_not_verified"


def test_verification_creates_personal_org_and_session(client, engine):
    csrf = signup_verify_login(client, engine, "c@example.com", name="Casey")
    orgs = client.get("/api/v1/orgs").json()["items"]
    assert len(orgs) == 1 and orgs[0]["role"] == "org_admin"
    assert orgs[0]["name"] == "Casey's workspace"
    me = client.get("/api/v1/auth/me").json()
    assert me["user"]["email"] == "c@example.com"
    assert me["csrf_token"] == csrf


def test_verification_token_is_single_use(client, engine):
    client.post("/api/v1/auth/signup", json={"email": "d@example.com", "password": PASSWORD, "display_name": "D"})
    token = verify_token_from(engine, "d@example.com")
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    r = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_or_expired_token"


def test_unknown_token_rejected(client):
    r = client.post("/api/v1/auth/verify-email", json={"token": "x" * 40})
    assert r.status_code == 400


def test_wrong_password_is_generic_and_lockout_engages(client, engine):
    csrf = signup_verify_login(client, engine, "e@example.com")
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    for _ in range(4):
        r = client.post("/api/v1/auth/login", json={"email": "e@example.com", "password": "wrong-password-xx"})
        assert r.status_code == 401
        assert r.json()["code"] == "invalid_credentials"
    # Fifth failure locks the account; even the right password is refused now.
    client.post("/api/v1/auth/login", json={"email": "e@example.com", "password": "wrong-password-xx"})
    r = client.post("/api/v1/auth/login", json={"email": "e@example.com", "password": PASSWORD})
    assert r.status_code == 423
    assert r.json()["code"] == "account_locked"


def test_unknown_email_and_wrong_password_look_identical(client, engine):
    csrf = signup_verify_login(client, engine, "f@example.com")
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    a = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-xx"})
    b = client.post("/api/v1/auth/login", json={"email": "f@example.com", "password": "wrong-password-xx"})
    assert a.status_code == b.status_code == 401
    assert a.json()["title"] == b.json()["title"]


def test_weak_password_rejected(client):
    r = client.post("/api/v1/auth/signup", json={"email": "g@example.com", "password": "short", "display_name": "G"})
    assert r.status_code == 422


def test_unknown_fields_rejected(client):
    r = client.post(
        "/api/v1/auth/signup",
        json={"email": "h@example.com", "password": PASSWORD, "display_name": "H", "role": "org_admin"},
    )
    assert r.status_code == 422


def test_logout_requires_csrf_and_revokes_session(client, engine):
    csrf = signup_verify_login(client, engine, "i@example.com")
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_session_cookie_is_httponly_and_lax(client, engine):
    client.post("/api/v1/auth/signup", json={"email": "j@example.com", "password": PASSWORD, "display_name": "J"})
    client.post("/api/v1/auth/verify-email", json={"token": verify_token_from(engine, "j@example.com")})
    r = client.post("/api/v1/auth/login", json={"email": "j@example.com", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "aidlc_session=" in cookie


def test_rate_limit_on_signup(app, client):
    app.state.auth_limiter._limit = 3
    statuses = []
    for i in range(5):
        r = client.post(
            "/api/v1/auth/signup",
            json={"email": f"r{i}@example.com", "password": PASSWORD, "display_name": "R"},
        )
        statuses.append(r.status_code)
    assert statuses[:3] == [202, 202, 202]
    assert statuses[3] == 429
