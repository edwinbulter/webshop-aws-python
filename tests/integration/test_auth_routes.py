EMAIL = "routes-test@example.com"
PASSWORD = "StrongPassw0rd!"


def _register_and_confirm(client, email=EMAIL, password=PASSWORD):
    client.post("/register", data={"email": email, "password": password, "password_confirm": password})
    client.post("/confirm", data={"email": email, "action": "confirm", "code": "123456"})


def test_get_requests_for_all_auth_pages_return_200(client, dynamodb_table):
    for path in ["/register", "/login", "/confirm", "/forgot-password", "/reset-password"]:
        response = client.get(path)
        assert response.status_code == 200, path


def test_register_success_redirects_to_confirm(client, dynamodb_table):
    response = client.post(
        "/register",
        data={"email": "newuser@example.com", "password": PASSWORD, "password_confirm": PASSWORD},
    )
    assert response.status_code == 302
    assert "/confirm" in response.headers["Location"]


def test_register_success_flash_mentions_local_dev(client, dynamodb_table):
    # The integration suite always runs against moto (see aws_endpoints in
    # tests/conftest.py), so COGNITO_IDP_ENDPOINT_URL is always set here --
    # cognito.is_local_mode() is true, locking in the local-dev wording.
    response = client.post(
        "/register",
        data={"email": "localflash@example.com", "password": PASSWORD, "password_confirm": PASSWORD},
        follow_redirects=True,
    )
    assert "geen echte e-mail verstuurd" in response.get_data(as_text=True)


def test_confirm_page_shows_local_mode_banner_and_prefilled_code(client, dynamodb_table):
    email = "localbanner@example.com"
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})

    html = client.get(f"/confirm?email={email}").get_data(as_text=True)
    assert 'data-testid="local-mode-banner"' in html
    assert 'id="code"' in html
    assert 'value="123456"' in html


def test_register_rejects_mismatched_passwords(client, dynamodb_table):
    response = client.post(
        "/register",
        data={"email": "mismatch@example.com", "password": PASSWORD, "password_confirm": "Different1!"},
    )
    assert response.status_code == 400
    assert "komen niet overeen" in response.get_data(as_text=True)


def test_register_rejects_duplicate_email(client, dynamodb_table):
    email = "duplicate@example.com"
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})

    response = client.post(
        "/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD}
    )
    assert response.status_code == 400
    assert "al geregistreerd" in response.get_data(as_text=True)


def test_confirm_success_redirects_to_login(client, dynamodb_table):
    email = "confirmable@example.com"
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})

    response = client.post("/confirm", data={"email": email, "action": "confirm", "code": "123456"})
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_confirm_resend_shows_local_mode_message_instead_of_crashing(client, dynamodb_table):
    # moto[server]==5.0.24 doesn't implement ResendConfirmationCode at all
    # (NotImplementedError, not a botocore ClientError) -- verified manually
    # against real AWS Cognito that app.auth.cognito.resend_confirmation_code
    # works correctly there. The route must catch this and degrade gracefully
    # (a friendly local-dev message) instead of a 500.
    email = "resend@example.com"
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})

    response = client.post("/confirm", data={"email": email, "action": "resend"})
    assert response.status_code == 200
    assert "niet ondersteund door de moto-mock" in response.get_data(as_text=True)


def test_login_success_sets_session_cookie_and_redirects(client, dynamodb_table):
    _register_and_confirm(client, "loginok@example.com")

    response = client.post("/login", data={"email": "loginok@example.com", "password": PASSWORD, "next": ""})
    assert response.status_code == 302

    with client.session_transaction() as flask_session:
        assert "session_id" in flask_session


def test_login_with_unconfirmed_account_redirects_to_confirm(client, dynamodb_table):
    email = "unconfirmed@example.com"
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})

    response = client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})
    assert response.status_code == 302
    assert "/confirm" in response.headers["Location"]


def test_login_with_wrong_password_shows_generic_error(client, dynamodb_table):
    _register_and_confirm(client, "wrongpass@example.com")

    response = client.post(
        "/login", data={"email": "wrongpass@example.com", "password": "NotThePassword1!", "next": ""}
    )
    assert response.status_code == 400
    assert "Onjuiste combinatie" in response.get_data(as_text=True)


def test_login_rejects_unsafe_next_url_and_falls_back_home(client, dynamodb_table):
    _register_and_confirm(client, "opensredirect@example.com")

    response = client.post(
        "/login",
        data={
            "email": "opensredirect@example.com",
            "password": PASSWORD,
            "next": "https://evil.example.com/phish",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_login_accepts_safe_next_url(client, dynamodb_table):
    _register_and_confirm(client, "safenext@example.com")

    response = client.post(
        "/login", data={"email": "safenext@example.com", "password": PASSWORD, "next": "/cart"}
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/cart"


def test_logout_clears_session(client, dynamodb_table):
    _register_and_confirm(client, "logoutme@example.com")
    client.post("/login", data={"email": "logoutme@example.com", "password": PASSWORD, "next": ""})

    response = client.post("/logout")
    assert response.status_code == 302

    with client.session_transaction() as flask_session:
        assert "session_id" not in flask_session


def test_nav_reflects_login_state(client, dynamodb_table):
    guest_html = client.get("/").get_data(as_text=True)
    assert "Inloggen" in guest_html
    assert "Uitloggen" not in guest_html

    _register_and_confirm(client, "navcheck@example.com")
    client.post("/login", data={"email": "navcheck@example.com", "password": PASSWORD, "next": ""})

    logged_in_html = client.get("/").get_data(as_text=True)
    assert "Uitloggen" in logged_in_html
    assert "Inloggen" not in logged_in_html


def test_forgot_password_shows_same_message_regardless_of_email_existing(client, dynamodb_table):
    _register_and_confirm(client, "forgotflow@example.com")

    for email in ["forgotflow@example.com", "doesnotexist@example.com"]:
        response = client.post("/forgot-password", data={"email": email})
        assert response.status_code == 302
        assert "/reset-password" in response.headers["Location"]


def test_reset_password_round_trip_allows_login_with_new_password(client, dynamodb_table):
    email = "resetflow@example.com"
    _register_and_confirm(client, email)
    client.post("/forgot-password", data={"email": email})

    new_password = "NewStrongPassw0rd!"
    response = client.post(
        "/reset-password",
        data={"email": email, "code": "123456", "password": new_password, "password_confirm": new_password},
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    login_response = client.post("/login", data={"email": email, "password": new_password, "next": ""})
    assert login_response.status_code == 302
    with client.session_transaction() as flask_session:
        assert "session_id" in flask_session
