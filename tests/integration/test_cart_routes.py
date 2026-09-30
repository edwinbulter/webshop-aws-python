PRODUCT_ID = "vindlys-bureaulamp-zwart"
PRODUCT_COLOR = "Zwart"
PRODUCT_PRICE_CENTS = 1999


def test_add_to_cart_updates_badge_and_cart_page(client, dynamodb_table):
    response = client.post(
        "/cart/add",
        data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "2"},
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Toegevoegd" in html
    assert 'id="cart-count"' in html
    assert ">2<" in html

    cart_response = client.get("/cart")
    cart_html = cart_response.get_data(as_text=True)
    assert "VINDLYS" in cart_html
    expected_total = f"€ {2 * PRODUCT_PRICE_CENTS / 100:.2f}"
    assert expected_total in cart_html


def test_add_to_cart_rejects_unknown_color(client, dynamodb_table):
    response = client.post(
        "/cart/add",
        data={"product_id": PRODUCT_ID, "color": "Kleur die niet bestaat", "quantity": "1"},
    )
    assert response.status_code == 400
    assert "niet gevonden" in response.get_data(as_text=True)


def test_add_to_cart_clamps_quantity_to_max(client, dynamodb_table):
    response = client.post(
        "/cart/add",
        data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "999"},
    )
    assert response.status_code == 200

    cart_html = client.get("/cart").get_data(as_text=True)
    assert "Aantal: 10" in cart_html


def test_clear_cart_empties_it_and_resets_badge(client, dynamodb_table):
    client.post("/cart/add", data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "1"})

    response = client.post("/cart/clear")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "leeg" in html
    assert ">0<" in html

    cart_html = client.get("/cart").get_data(as_text=True)
    assert "leeg" in cart_html
