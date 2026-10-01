import os

import boto3

from app.models.order import Order, OrderLine, OrderStatus
from app.models.return_request import ReturnRequest
from app.repositories import single_table

PASSWORD = "StrongPassw0rd!"


def _login_as_admin(client, aws_endpoints, email):
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})
    client.post("/confirm", data={"email": email, "action": "confirm", "code": "123456"})
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})
    idp = boto3.client("cognito-idp", region_name="eu-west-1", endpoint_url=aws_endpoints)
    idp.admin_add_user_to_group(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=email, GroupName="Admins"
    )
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})


def _make_order(order_id: str, status: str = OrderStatus.IN_PROGRESS, stock: int = 100) -> Order:
    order = Order.new(
        order_id=order_id,
        lines=[OrderLine(product_id="p", title="t", color="Zwart", quantity=1, price_cents=1999)],
    )
    single_table.create_order(order)
    single_table.set_order_status(order_id, status, allowed_from={OrderStatus.AWAITING_PAYMENT})
    # Plenty of stock by default -- tests about shipping-eligibility override
    # this explicitly; everything else shouldn't have to care about stock at all.
    single_table.put_variant_stock("p", "Zwart", stock)
    return single_table.get_order(order_id)


def _csrf_token(client) -> str:
    html = client.get("/admin").get_data(as_text=True)
    marker = 'data-testid="admin-csrf-token"'
    marker_pos = html.index(marker)
    tag_start = html.rindex("<input", 0, marker_pos)
    value_start = html.index('value="', tag_start) + len('value="')
    return html[value_start : html.index('"', value_start)]


def test_orders_list_shows_all_orders(client, dynamodb_table, cognito_pool, aws_endpoints):
    _make_order("admin-list-order-1")
    _login_as_admin(client, aws_endpoints, "orders-list-admin@example.com")

    response = client.get("/admin/orders")
    assert response.status_code == 200
    assert "admin-list-order-1" in response.get_data(as_text=True)


def test_orders_list_filters_by_status(client, dynamodb_table, cognito_pool, aws_endpoints):
    _make_order("admin-filter-shipped", status=OrderStatus.SHIPPED)
    _make_order("admin-filter-in-progress", status=OrderStatus.IN_PROGRESS)
    _login_as_admin(client, aws_endpoints, "orders-filter-admin@example.com")

    html = client.get(f"/admin/orders?status={OrderStatus.SHIPPED}").get_data(as_text=True)
    assert "admin-filter-shipped" in html
    assert "admin-filter-in-progress" not in html


def test_order_detail_shows_advance_button_for_eligible_status(
    client, dynamodb_table, cognito_pool, aws_endpoints
):
    order = _make_order("admin-detail-advance", status=OrderStatus.IN_PROGRESS)
    _login_as_admin(client, aws_endpoints, "orders-detail-admin@example.com")

    html = client.get(f"/admin/orders/{order.id}").get_data(as_text=True)
    assert 'data-testid="admin-advance-status-button"' in html
    assert "Verzonden" in html


def test_order_detail_404s_for_unknown_order(client, dynamodb_table, cognito_pool, aws_endpoints):
    _login_as_admin(client, aws_endpoints, "orders-404-admin@example.com")
    response = client.get("/admin/orders/does-not-exist")
    assert response.status_code == 404


def test_advance_order_moves_status_forward(client, dynamodb_table, cognito_pool, aws_endpoints):
    order = _make_order("admin-advance-order", status=OrderStatus.IN_PROGRESS)
    _login_as_admin(client, aws_endpoints, "advance-admin@example.com")
    csrf_token = _csrf_token(client)

    response = client.post(f"/admin/orders/{order.id}/advance", data={"csrf_token": csrf_token})
    assert response.status_code == 302
    assert single_table.get_order(order.id).status == OrderStatus.SHIPPED


def test_advance_order_rejects_missing_csrf_token(client, dynamodb_table, cognito_pool, aws_endpoints):
    order = _make_order("admin-advance-csrf", status=OrderStatus.IN_PROGRESS)
    _login_as_admin(client, aws_endpoints, "advance-csrf-admin@example.com")

    response = client.post(f"/admin/orders/{order.id}/advance", data={})
    assert response.status_code == 400
    assert single_table.get_order(order.id).status == OrderStatus.IN_PROGRESS


def test_advance_order_is_noop_with_no_next_status(client, dynamodb_table, cognito_pool, aws_endpoints):
    order = _make_order("admin-advance-terminal", status=OrderStatus.CANCELLED)
    _login_as_admin(client, aws_endpoints, "advance-terminal-admin@example.com")
    csrf_token = _csrf_token(client)

    response = client.post(f"/admin/orders/{order.id}/advance", data={"csrf_token": csrf_token})
    assert response.status_code == 302
    assert single_table.get_order(order.id).status == OrderStatus.CANCELLED


def test_returns_queue_lists_reported_returns(client, dynamodb_table, cognito_pool, aws_endpoints):
    order = _make_order("admin-return-queue-order", status=OrderStatus.SHIPPED)
    single_table.create_return_request(ReturnRequest.new(order.id, "Verkeerd besteld"))
    _login_as_admin(client, aws_endpoints, "returns-queue-admin@example.com")

    html = client.get("/admin/returns").get_data(as_text=True)
    assert "admin-return-queue-order" in html
    assert "Verkeerd besteld" in html


def test_order_detail_shows_stock_warning_instead_of_button_when_out_of_stock(
    client, dynamodb_table, cognito_pool, aws_endpoints
):
    order = _make_order("admin-detail-out-of-stock", status=OrderStatus.IN_PROGRESS, stock=0)
    _login_as_admin(client, aws_endpoints, "orders-outofstock-admin@example.com")

    html = client.get(f"/admin/orders/{order.id}").get_data(as_text=True)
    assert 'data-testid="stock-shortage-warning"' in html
    assert 'data-testid="admin-advance-status-button"' not in html


def test_advance_order_blocks_shipping_when_out_of_stock(client, dynamodb_table, cognito_pool, aws_endpoints):
    order = _make_order("admin-advance-out-of-stock", status=OrderStatus.IN_PROGRESS, stock=0)
    _login_as_admin(client, aws_endpoints, "advance-outofstock-admin@example.com")
    csrf_token = _csrf_token(client)

    response = client.post(f"/admin/orders/{order.id}/advance", data={"csrf_token": csrf_token})
    assert response.status_code == 302
    assert single_table.get_order(order.id).status == OrderStatus.IN_PROGRESS
    assert single_table.get_variant_stock("p", "Zwart") == 0


def test_advance_order_blocks_shipping_when_stock_is_insufficient_for_quantity(
    client, dynamodb_table, cognito_pool, aws_endpoints
):
    order_id = "admin-advance-partial-stock"
    order = Order.new(
        order_id=order_id,
        lines=[OrderLine(product_id="p", title="t", color="Zwart", quantity=3, price_cents=1999)],
    )
    single_table.create_order(order)
    single_table.set_order_status(
        order_id, OrderStatus.IN_PROGRESS, allowed_from={OrderStatus.AWAITING_PAYMENT}
    )
    single_table.put_variant_stock("p", "Zwart", 2)
    _login_as_admin(client, aws_endpoints, "advance-partialstock-admin@example.com")
    csrf_token = _csrf_token(client)

    response = client.post(f"/admin/orders/{order_id}/advance", data={"csrf_token": csrf_token})
    assert response.status_code == 302
    assert single_table.get_order(order_id).status == OrderStatus.IN_PROGRESS
    assert single_table.get_variant_stock("p", "Zwart") == 2


def test_advance_order_decrements_stock_when_shipping_succeeds(
    client, dynamodb_table, cognito_pool, aws_endpoints
):
    order = _make_order("admin-advance-decrement", status=OrderStatus.IN_PROGRESS, stock=5)
    _login_as_admin(client, aws_endpoints, "advance-decrement-admin@example.com")
    csrf_token = _csrf_token(client)

    response = client.post(f"/admin/orders/{order.id}/advance", data={"csrf_token": csrf_token})
    assert response.status_code == 302
    assert single_table.get_order(order.id).status == OrderStatus.SHIPPED
    assert single_table.get_variant_stock("p", "Zwart") == 4


def test_advance_order_does_not_touch_stock_for_non_shipping_transitions(
    client, dynamodb_table, cognito_pool, aws_endpoints
):
    order = _make_order("admin-advance-no-stock-touch", status=OrderStatus.SHIPPED, stock=7)
    _login_as_admin(client, aws_endpoints, "advance-nostocktouch-admin@example.com")
    csrf_token = _csrf_token(client)

    response = client.post(f"/admin/orders/{order.id}/advance", data={"csrf_token": csrf_token})
    assert response.status_code == 302
    assert single_table.get_order(order.id).status == OrderStatus.DELIVERED
    assert single_table.get_variant_stock("p", "Zwart") == 7


def test_advance_completes_a_reported_return(client, dynamodb_table, cognito_pool, aws_endpoints):
    order = _make_order("admin-return-complete-order", status=OrderStatus.SHIPPED)
    single_table.set_order_status(order.id, OrderStatus.RETURN_REPORTED, allowed_from={OrderStatus.SHIPPED})
    single_table.create_return_request(ReturnRequest.new(order.id, "Kapot"))
    _login_as_admin(client, aws_endpoints, "returns-complete-admin@example.com")
    csrf_token = _csrf_token(client)

    response = client.post(f"/admin/orders/{order.id}/advance", data={"csrf_token": csrf_token})
    assert response.status_code == 302
    assert single_table.get_order(order.id).status == OrderStatus.RETURN_COMPLETED
