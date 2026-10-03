import json

from app.repositories import single_table

PASSWORD = "StrongPassw0rd!"
PRODUCT_ID = "vindlys-bureaulamp-zwart"
PRODUCT_COLOR = "Zwart"


def _register_confirm_login(client, email):
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})
    client.post("/confirm", data={"email": email, "action": "confirm", "code": "123456"})
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})


def _csrf_token(client) -> str:
    html = client.get("/account").get_data(as_text=True)
    start = html.index('name="csrf_token" value="') + len('name="csrf_token" value="')
    return html[start : html.index('"', start)]


def _place_order(client) -> str:
    client.post("/cart/add", data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "1"})
    response = client.post("/checkout")
    html = response.get_data(as_text=True)
    start = html.index('data-testid="order-id">') + len('data-testid="order-id">')
    return html[start : html.index("<", start)].strip()


# ---- data export (AVG Art. 20) ----


def test_export_requires_login(client, dynamodb_table):
    response = client.get("/account/export")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_export_handles_no_profile_or_orders_yet(client, dynamodb_table):
    _register_confirm_login(client, "export-empty@example.com")

    response = client.get("/account/export")
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert "attachment" in response.headers["Content-Disposition"]
    assert "mijn-gegevens.json" in response.headers["Content-Disposition"]

    payload = json.loads(response.get_data(as_text=True))
    assert payload["profiel"] is None
    assert payload["bestellingen"] == []


def test_export_includes_profile_and_order_data(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "export-full@example.com")
    csrf_token = _csrf_token(client)
    client.post(
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
    order_id = _place_order(client)

    payload = json.loads(client.get("/account/export").get_data(as_text=True))

    assert payload["profiel"]["email"] == "export-full@example.com"
    assert payload["profiel"]["voornaam"] == "Jan"
    assert payload["profiel"]["afleveradres"]["street"] == "Hoofdstraat 1"
    # Internal storage details must never leak into the export.
    assert "PK" not in payload["profiel"]
    assert "SK" not in payload["profiel"]

    assert len(payload["bestellingen"]) == 1
    order_payload = payload["bestellingen"][0]
    assert order_payload["id"] == order_id
    assert len(order_payload["regels"]) == 1
    assert order_payload["regels"][0]["kleur"] == PRODUCT_COLOR


# ---- account deletion (AVG Art. 17) ----


def test_delete_confirm_page_requires_login(client, dynamodb_table):
    response = client.get("/account/delete")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_delete_rejects_missing_csrf_token(client, dynamodb_table):
    _register_confirm_login(client, "delete-csrf@example.com")

    response = client.post("/account/delete", data={"password": PASSWORD})
    assert response.status_code == 400


def test_delete_rejects_wrong_password_and_keeps_the_account(client, dynamodb_table):
    email = "delete-wrongpw@example.com"
    _register_confirm_login(client, email)
    csrf_token = _csrf_token(client)

    response = client.post(
        "/account/delete", data={"csrf_token": csrf_token, "password": "NotTheRealPassword1!"}
    )
    assert response.status_code == 302
    assert "/account/delete" in response.headers["Location"]

    # The account must still exist and be usable.
    login_response = client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})
    assert login_response.status_code == 302
    assert "/login" not in login_response.headers["Location"]


def test_delete_removes_account_and_profile_but_keeps_orders(
    client, dynamodb_table, eventbridge_bus_and_queues
):
    email = "delete-full@example.com"
    _register_confirm_login(client, email)
    csrf_token = _csrf_token(client)
    client.post(
        "/account",
        data={"csrf_token": csrf_token, "given_name": "Te", "family_name": "Verwijderen"},
    )
    order_id = _place_order(client)
    sub = single_table.get_order(order_id).user_sub
    assert single_table.get_user_profile(sub) is not None

    response = client.post("/account/delete", data={"csrf_token": csrf_token, "password": PASSWORD})
    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    # Profile (identifying data) is gone.
    assert single_table.get_user_profile(sub) is None
    # The order itself (pseudonymous transaction record) is deliberately kept.
    assert single_table.get_order(order_id) is not None

    # The Cognito account itself no longer exists -- logging in fails.
    login_response = client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})
    assert login_response.status_code == 400

    # The session was destroyed too -- /account now requires logging in again.
    assert client.get("/account").status_code == 302
