PASSWORD = "StrongPassw0rd!"


def _register_confirm_login(client, email):
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})
    client.post("/confirm", data={"email": email, "action": "confirm", "code": "123456"})
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})


def _csrf_token(client) -> str:
    html = client.get("/account").get_data(as_text=True)
    start = html.index('name="csrf_token" value="') + len('name="csrf_token" value="')
    return html[start : html.index('"', start)]


def test_account_requires_login(client, dynamodb_table):
    response = client.get("/account")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert "next=/account" in response.headers["Location"]


def test_account_shows_empty_profile_for_new_user(client, dynamodb_table):
    _register_confirm_login(client, "profile-new@example.com")

    response = client.get("/account")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "profile-new@example.com" in html


def test_account_update_persists_and_redisplays(client, dynamodb_table):
    _register_confirm_login(client, "profile-update@example.com")
    csrf_token = _csrf_token(client)

    response = client.post(
        "/account",
        data={
            "csrf_token": csrf_token,
            "given_name": "Jan",
            "family_name": "Jansen",
            "shipping_name": "Jan Jansen",
            "shipping_street": "Hoofdstraat 1",
            "shipping_postal_code": "1234AB",
            "shipping_city": "Amsterdam",
            "shipping_country": "Nederland",
            "billing_name": "Jan Jansen",
            "billing_street": "Hoofdstraat 1",
            "billing_postal_code": "1234AB",
            "billing_city": "Amsterdam",
            "billing_country": "Nederland",
        },
    )
    assert response.status_code == 302

    html = client.get("/account").get_data(as_text=True)
    assert 'value="Jan"' in html
    assert 'value="Jansen"' in html
    assert 'value="Hoofdstraat 1"' in html


def test_account_update_rejects_missing_csrf_token(client, dynamodb_table):
    _register_confirm_login(client, "profile-csrf@example.com")

    response = client.post("/account", data={"given_name": "Should", "family_name": "Fail"})
    assert response.status_code == 400


def test_account_update_rejects_wrong_csrf_token(client, dynamodb_table):
    _register_confirm_login(client, "profile-csrf2@example.com")

    response = client.post(
        "/account", data={"csrf_token": "not-the-real-token", "given_name": "Should", "family_name": "Fail"}
    )
    assert response.status_code == 400


def test_each_customer_only_ever_sees_their_own_profile(client, dynamodb_table):
    _register_confirm_login(client, "profile-a@example.com")
    csrf_token = _csrf_token(client)
    client.post(
        "/account",
        data={"csrf_token": csrf_token, "given_name": "Alice", "family_name": "A"},
    )
    client.post("/logout")

    _register_confirm_login(client, "profile-b@example.com")
    html = client.get("/account").get_data(as_text=True)
    assert "Alice" not in html
    assert "profile-b@example.com" in html
