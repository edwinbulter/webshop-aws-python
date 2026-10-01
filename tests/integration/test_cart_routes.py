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
    assert 'value="10" selected' in cart_html


def test_update_cart_item_quantity_changes_total(client, dynamodb_table):
    client.post("/cart/add", data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "1"})

    response = client.post(f"/cart/items/{PRODUCT_ID}/quantity", data={"quantity": "3"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'value="3" selected' in html
    expected_total = f"€ {3 * PRODUCT_PRICE_CENTS / 100:.2f}"
    assert expected_total in html


def test_update_cart_item_quantity_clamps_to_max(client, dynamodb_table):
    client.post("/cart/add", data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "1"})

    response = client.post(f"/cart/items/{PRODUCT_ID}/quantity", data={"quantity": "999"})
    assert 'value="10" selected' in response.get_data(as_text=True)


def test_update_cart_item_quantity_is_a_noop_for_an_already_removed_item(client, dynamodb_table):
    # No add_to_cart call first -- the item doesn't exist, so the
    # ConditionExpression guard must prevent a malformed item being created.
    response = client.post(f"/cart/items/{PRODUCT_ID}/quantity", data={"quantity": "3"})
    assert response.status_code == 200
    assert "leeg" in response.get_data(as_text=True)


def test_remove_cart_item_deletes_just_that_line(client, dynamodb_table):
    other_product_id = "bjorkvik-bureaulamp-donkergrijs"
    client.post("/cart/add", data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "1"})
    client.post("/cart/add", data={"product_id": other_product_id, "color": "Donkergrijs", "quantity": "1"})

    response = client.post(f"/cart/items/{PRODUCT_ID}/remove")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert PRODUCT_ID not in html
    assert other_product_id in html


def test_remove_cart_item_empties_cart_when_it_was_the_only_item(client, dynamodb_table):
    client.post("/cart/add", data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "1"})

    response = client.post(f"/cart/items/{PRODUCT_ID}/remove")
    assert "leeg" in response.get_data(as_text=True)


def test_clear_cart_empties_it_and_resets_badge(client, dynamodb_table):
    client.post("/cart/add", data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "1"})

    response = client.post("/cart/clear")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "leeg" in html
    assert ">0<" in html

    cart_html = client.get("/cart").get_data(as_text=True)
    assert "leeg" in cart_html
