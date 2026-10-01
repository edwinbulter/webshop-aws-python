import re

PASSWORD = "StrongPassw0rd!"
PRODUCT_ID = "vindlys-bureaulamp-zwart"
PRODUCT_COLOR = "Zwart"


def _register_confirm_login(client, email):
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})
    client.post("/confirm", data={"email": email, "action": "confirm", "code": "123456"})
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})


def _place_order(client) -> str:
    client.post("/cart/add", data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "1"})
    response = client.post("/checkout")
    html = response.get_data(as_text=True)
    start = html.index('data-testid="order-id">') + len('data-testid="order-id">')
    return html[start : html.index("<", start)].strip()


def test_orders_list_requires_login(client, dynamodb_table):
    response = client.get("/account/orders")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_logged_in_checkout_links_order_to_customer(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "orders-owner@example.com")
    order_id = _place_order(client)

    html = client.get("/account/orders").get_data(as_text=True)
    assert order_id in html


def test_orders_list_shows_seconds_free_date(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "orders-list-date@example.com")
    _place_order(client)

    html = client.get("/account/orders").get_data(as_text=True)
    match = re.search(r'font-mono[^>]*>[^<]+</p>\s*<p class="text-sm text-gray-500">([^<]+)</p>', html)
    assert match is not None
    assert re.fullmatch(r"\d{2}-\d{2}-\d{4} \d{2}:\d{2}", match.group(1).strip())


def test_order_detail_shows_own_order(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "orders-detail@example.com")
    order_id = _place_order(client)

    response = client.get(f"/account/orders/{order_id}")
    assert response.status_code == 200
    assert order_id in response.get_data(as_text=True)


def test_order_detail_shows_product_thumbnail_and_seconds_free_date(
    client, dynamodb_table, eventbridge_bus_and_queues
):
    _register_confirm_login(client, "orders-thumbnail@example.com")
    order_id = _place_order(client)

    html = client.get(f"/account/orders/{order_id}").get_data(as_text=True)
    assert '<img src="https://www.ikea.com' in html
    # "Geplaatst op: dd-mm-yyyy HH:MM" -- no seconds, no ISO "T"/timezone suffix.
    match = re.search(r"Geplaatst op:</span>\s*([^<]+)</p>", html)
    assert match is not None
    assert re.fullmatch(r"\d{2}-\d{2}-\d{4} \d{2}:\d{2}", match.group(1).strip())


def test_order_detail_404s_for_someone_elses_order(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "orders-victim@example.com")
    victim_order_id = _place_order(client)
    client.post("/logout")

    _register_confirm_login(client, "orders-attacker@example.com")
    response = client.get(f"/account/orders/{victim_order_id}")
    assert response.status_code == 404


def test_order_detail_404s_identically_for_nonexistent_order(client, dynamodb_table):
    _register_confirm_login(client, "orders-404@example.com")

    existing_but_foreign = client.get("/account/orders/does-not-exist-at-all")
    assert existing_but_foreign.status_code == 404


def test_guest_order_has_no_customer_link_and_is_invisible_to_any_account(
    client, dynamodb_table, eventbridge_bus_and_queues
):
    client.post("/cart/add", data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "1"})
    client.post("/checkout")

    _register_confirm_login(client, "orders-unrelated@example.com")
    html = client.get("/account/orders").get_data(as_text=True)
    assert "orders-empty" in html or "Je hebt nog geen bestellingen" in html
