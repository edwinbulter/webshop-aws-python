import re
from datetime import datetime, timedelta, timezone

from app.models.order import Order, OrderLine, OrderStatus
from app.repositories import single_table
from consumers.payment_service.handler import handler as payment_handler

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


def _csrf_token(client) -> str:
    # The profile page always renders a csrf_token field, unlike order_detail's
    # cancel/return forms, which are conditionally hidden depending on order
    # state -- the token itself is the same for the whole session either way.
    html = client.get("/account").get_data(as_text=True)
    start = html.index('name="csrf_token" value="') + len('name="csrf_token" value="')
    return html[start : html.index('"', start)]


def _payment_event(order_id: str) -> dict:
    import json

    envelope = {
        "detail-type": "OrderPlaced",
        "source": "webshop.orders",
        "detail": {"schema_version": 1, "order_id": order_id, "total_cents": 1999, "item_count": 1},
    }
    return {"Records": [{"messageId": "m1", "body": json.dumps(envelope)}]}


def _force_order_into_status(order_id: str, status: str, created_at: str | None = None) -> None:
    order = single_table.get_order(order_id)
    backdated = Order(
        id=order.id,
        status=status,
        total_cents=order.total_cents,
        created_at=created_at or order.created_at,
        lines=order.lines,
        user_sub=order.user_sub,
    )
    single_table.create_order(backdated)


def test_new_order_starts_awaiting_payment(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "status-new@example.com")
    order_id = _place_order(client)

    order = single_table.get_order(order_id)
    assert order.status == OrderStatus.AWAITING_PAYMENT

    html = client.get(f"/account/orders/{order_id}").get_data(as_text=True)
    assert "In afwachting van betaling" in html
    assert 'data-testid="cancel-order-button"' in html


def test_payment_consumer_advances_awaiting_payment_to_in_progress(client, dynamodb_table):
    order = Order.new(
        order_id="order-lifecycle-1",
        lines=[OrderLine(product_id="p", title="t", color="Zwart", quantity=1, price_cents=1999)],
    )
    single_table.create_order(order)
    assert single_table.get_order(order.id).status == OrderStatus.AWAITING_PAYMENT

    result = payment_handler(_payment_event(order.id))

    assert result == {"batchItemFailures": []}
    assert single_table.get_order(order.id).status == OrderStatus.IN_PROGRESS


def test_payment_consumer_is_a_noop_if_already_cancelled(client, dynamodb_table):
    order = Order.new(
        order_id="order-lifecycle-2",
        lines=[OrderLine(product_id="p", title="t", color="Zwart", quantity=1, price_cents=1999)],
    )
    single_table.create_order(order)
    single_table.set_order_status(
        order.id, OrderStatus.CANCELLED, allowed_from={OrderStatus.AWAITING_PAYMENT}
    )

    result = payment_handler(_payment_event(order.id))

    assert result == {"batchItemFailures": []}
    assert single_table.get_order(order.id).status == OrderStatus.CANCELLED


def test_cancel_succeeds_while_in_progress(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "cancel-ok@example.com")
    order_id = _place_order(client)
    single_table.set_order_status(
        order_id, OrderStatus.IN_PROGRESS, allowed_from={OrderStatus.AWAITING_PAYMENT}
    )
    csrf_token = _csrf_token(client)

    response = client.post(f"/account/orders/{order_id}/cancel", data={"csrf_token": csrf_token})
    assert response.status_code == 302
    assert single_table.get_order(order_id).status == OrderStatus.CANCELLED

    html = client.get(f"/account/orders/{order_id}").get_data(as_text=True)
    assert 'data-testid="cancel-order-button"' not in html


def test_cancel_fails_once_shipped(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "cancel-too-late@example.com")
    order_id = _place_order(client)
    _force_order_into_status(order_id, OrderStatus.SHIPPED)
    csrf_token = _csrf_token(client)

    response = client.post(f"/account/orders/{order_id}/cancel", data={"csrf_token": csrf_token})
    assert response.status_code == 302
    assert single_table.get_order(order_id).status == OrderStatus.SHIPPED

    html = client.get(f"/account/orders/{order_id}").get_data(as_text=True)
    assert "niet meer geannuleerd" in html


def test_cancel_rejects_missing_csrf_token(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "cancel-csrf@example.com")
    order_id = _place_order(client)

    response = client.post(f"/account/orders/{order_id}/cancel", data={})
    assert response.status_code == 400
    assert single_table.get_order(order_id).status == OrderStatus.AWAITING_PAYMENT


def test_cancel_404s_for_someone_elses_order(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "cancel-victim@example.com")
    victim_order_id = _place_order(client)
    client.post("/logout")

    # The attacker is a genuine, legitimately authenticated user attempting an
    # IDOR against someone else's order_id -- using their OWN valid CSRF token
    # (which they do have), so this isolates the ownership check from CSRF.
    _register_confirm_login(client, "cancel-attacker@example.com")
    attacker_csrf_token = _csrf_token(client)

    response = client.post(
        f"/account/orders/{victim_order_id}/cancel", data={"csrf_token": attacker_csrf_token}
    )
    assert response.status_code == 404
    assert single_table.get_order(victim_order_id).status == OrderStatus.AWAITING_PAYMENT


def test_report_return_succeeds_once_shipped_and_within_window(
    client, dynamodb_table, eventbridge_bus_and_queues
):
    _register_confirm_login(client, "return-ok@example.com")
    order_id = _place_order(client)
    _force_order_into_status(order_id, OrderStatus.SHIPPED)
    csrf_token = _csrf_token(client)

    response = client.post(
        f"/account/orders/{order_id}/return", data={"csrf_token": csrf_token, "reason": "Verkeerde kleur"}
    )
    assert response.status_code == 302
    assert single_table.get_order(order_id).status == OrderStatus.RETURN_REPORTED

    return_request = single_table.get_return_request(order_id)
    assert return_request.reason == "Verkeerde kleur"

    html = client.get(f"/account/orders/{order_id}").get_data(as_text=True)
    assert "Verkeerde kleur" in html
    assert 'data-testid="report-return-button"' not in html

    match = re.search(r"Retour gemeld op ([^<]+)</p>", html)
    assert match is not None
    assert re.fullmatch(r"\d{2}-\d{2}-\d{4} \d{2}:\d{2}", match.group(1).strip())


def test_report_return_fails_while_in_progress(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "return-too-early@example.com")
    order_id = _place_order(client)

    csrf_token = _csrf_token(client)
    response = client.post(
        f"/account/orders/{order_id}/return", data={"csrf_token": csrf_token, "reason": "Spijt"}
    )
    assert response.status_code == 302
    assert single_table.get_order(order_id).status == OrderStatus.AWAITING_PAYMENT

    html = client.get(f"/account/orders/{order_id}").get_data(as_text=True)
    assert "geen retour gemeld worden" in html


def test_report_return_fails_outside_the_window(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "return-expired@example.com")
    order_id = _place_order(client)
    old_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    _force_order_into_status(order_id, OrderStatus.SHIPPED, created_at=old_date)
    csrf_token = _csrf_token(client)

    response = client.post(
        f"/account/orders/{order_id}/return", data={"csrf_token": csrf_token, "reason": "Te laat"}
    )
    assert response.status_code == 302
    assert single_table.get_order(order_id).status == OrderStatus.SHIPPED

    html = client.get(f"/account/orders/{order_id}").get_data(as_text=True)
    assert "retourtermijn" in html


def test_report_return_requires_a_reason(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "return-noreason@example.com")
    order_id = _place_order(client)
    _force_order_into_status(order_id, OrderStatus.SHIPPED)
    csrf_token = _csrf_token(client)

    response = client.post(
        f"/account/orders/{order_id}/return", data={"csrf_token": csrf_token, "reason": ""}
    )
    assert response.status_code == 302
    assert single_table.get_order(order_id).status == OrderStatus.SHIPPED

    html = client.get(f"/account/orders/{order_id}").get_data(as_text=True)
    assert "Geef een reden" in html


def test_report_return_rejects_wrong_csrf_token(client, dynamodb_table, eventbridge_bus_and_queues):
    _register_confirm_login(client, "return-csrf@example.com")
    order_id = _place_order(client)
    _force_order_into_status(order_id, OrderStatus.SHIPPED)

    response = client.post(f"/account/orders/{order_id}/return", data={"csrf_token": "wrong", "reason": "x"})
    assert response.status_code == 400
    assert single_table.get_order(order_id).status == OrderStatus.SHIPPED


def test_report_return_is_idempotent_against_double_submit(
    client, dynamodb_table, eventbridge_bus_and_queues
):
    _register_confirm_login(client, "return-double@example.com")
    order_id = _place_order(client)
    _force_order_into_status(order_id, OrderStatus.SHIPPED)
    csrf_token = _csrf_token(client)

    client.post(f"/account/orders/{order_id}/return", data={"csrf_token": csrf_token, "reason": "Eerste"})
    # Simulate a double form-submit arriving after the status already flipped:
    # re-force SHIPPED (as if the first request raced ahead) and submit again.
    _force_order_into_status(order_id, OrderStatus.SHIPPED)
    client.post(f"/account/orders/{order_id}/return", data={"csrf_token": csrf_token, "reason": "Tweede"})

    # The ConditionExpression on create_return_request means the first reason wins.
    assert single_table.get_return_request(order_id).reason == "Eerste"
