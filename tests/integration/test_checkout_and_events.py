import json

import boto3

from app.models.cart import CartItem
from app.repositories import single_table

PRODUCT_ID = "vindlys-bureaulamp-zwart"
PRODUCT_COLOR = "Zwart"
PRODUCT_PRICE_CENTS = 1999


def test_checkout_creates_order_and_clears_cart(
    client, dynamodb_table, eventbridge_bus_and_queues, aws_endpoints
):
    client.post("/cart/add", data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "2"})

    response = client.post("/checkout")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Bestelling geplaatst" in html
    assert f"€ {2 * PRODUCT_PRICE_CENTS / 100:.2f}" in html

    cart_html = client.get("/cart").get_data(as_text=True)
    assert "leeg" in cart_html

    sqs_client = boto3.client("sqs", region_name="eu-west-1", endpoint_url=aws_endpoints)
    queue_url = eventbridge_bus_and_queues["inventory-service-queue"]
    messages = sqs_client.receive_message(QueueUrl=queue_url, WaitTimeSeconds=2, MaxNumberOfMessages=10).get(
        "Messages", []
    )
    bodies = [json.loads(m["Body"]) for m in messages]
    assert any(b["detail"]["total_cents"] == 2 * PRODUCT_PRICE_CENTS for b in bodies)


def test_checkout_with_empty_cart_is_rejected(client, dynamodb_table):
    response = client.post("/checkout")
    assert response.status_code == 400
    assert "leeg" in response.get_data(as_text=True)


def test_checkout_rejects_cart_item_with_stale_color(client, dynamodb_table):
    cart_id = "tamper-test-cart"
    with client.session_transaction() as session:
        session["cart_id"] = cart_id

    tampered_item = CartItem(
        cart_id=cart_id,
        product_id=PRODUCT_ID,
        title="VINDLYS Bureaulamp, zwart",
        image_url="https://www.ikea.com/nl/nl/images/products/forsa-bureaulamp-zwart__0609293_pe684430_s5.jpg?f=xxs",
        color="Deze kleur bestaat niet",
        quantity=1,
        price_cents=PRODUCT_PRICE_CENTS,
    )
    table = single_table.get_table()
    table.put_item(Item=tampered_item.to_item())

    response = client.post("/checkout")
    assert response.status_code == 400
    assert "niet meer beschikbaar" in response.get_data(as_text=True)


def test_checkout_clamps_a_tampered_quantity_to_the_max(client, dynamodb_table):
    cart_id = "tamper-quantity-cart"
    with client.session_transaction() as session:
        session["cart_id"] = cart_id

    tampered_item = CartItem(
        cart_id=cart_id,
        product_id=PRODUCT_ID,
        title="VINDLYS Bureaulamp, zwart",
        image_url="https://www.ikea.com/nl/nl/images/products/forsa-bureaulamp-zwart__0609293_pe684430_s5.jpg?f=xxs",
        color=PRODUCT_COLOR,
        quantity=500,
        price_cents=PRODUCT_PRICE_CENTS,
    )
    table = single_table.get_table()
    table.put_item(Item=tampered_item.to_item())

    response = client.post("/checkout")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f"€ {10 * PRODUCT_PRICE_CENTS / 100:.2f}" in html
