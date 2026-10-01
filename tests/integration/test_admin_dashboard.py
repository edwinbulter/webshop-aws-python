import os

import boto3

from app.models.order import Order, OrderLine, OrderStatus
from app.models.return_request import ReturnRequest
from app.repositories import single_table

PASSWORD = "StrongPassw0rd!"


def _register_confirm_login(client, email):
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})
    client.post("/confirm", data={"email": email, "action": "confirm", "code": "123456"})
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})


def _login_as_admin(client, aws_endpoints, email):
    _register_confirm_login(client, email)
    idp = boto3.client("cognito-idp", region_name="eu-west-1", endpoint_url=aws_endpoints)
    idp.admin_add_user_to_group(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=email, GroupName="Admins"
    )
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})


def test_dashboard_shows_order_and_return_counts(client, dynamodb_table, cognito_pool, aws_endpoints):
    order = Order.new(
        order_id="dash-order-1",
        lines=[OrderLine(product_id="p", title="t", color="Zwart", quantity=1, price_cents=1999)],
    )
    single_table.create_order(order)
    single_table.set_order_status(order.id, OrderStatus.SHIPPED, allowed_from={OrderStatus.AWAITING_PAYMENT})
    single_table.create_return_request(ReturnRequest.new(order.id, "Kapot"))

    _login_as_admin(client, aws_endpoints, "dashboard-admin@example.com")

    response = client.get("/admin")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-testid="stat-total-orders"' in html
    assert 'data-testid="recent-order-row"' in html
    assert "dash-order-1" in html
