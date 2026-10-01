import os

import boto3

from app.models.user import Address, UserProfile
from app.repositories import single_table

PASSWORD = "StrongPassw0rd!"


def _register_confirm(client, email):
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})
    client.post("/confirm", data={"email": email, "action": "confirm", "code": "123456"})


def _login(client, email):
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})


def _promote_to_admin(aws_endpoints, email):
    idp = boto3.client("cognito-idp", region_name="eu-west-1", endpoint_url=aws_endpoints)
    idp.admin_add_user_to_group(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=email, GroupName="Admins"
    )


def test_customers_list_shows_registered_customer(client, dynamodb_table, cognito_pool, aws_endpoints):
    _register_confirm(client, "crm-customer@example.com")
    _login(client, "crm-customer@example.com")
    client.post("/logout")

    _register_confirm(client, "crm-admin@example.com")
    _login(client, "crm-admin@example.com")
    _promote_to_admin(aws_endpoints, "crm-admin@example.com")
    _login(client, "crm-admin@example.com")

    html = client.get("/admin/customers").get_data(as_text=True)
    assert "crm-customer@example.com" in html
    assert "crm-admin@example.com" in html


def test_customer_detail_404s_for_unknown_email(client, dynamodb_table, cognito_pool, aws_endpoints):
    _register_confirm(client, "crm-404-admin@example.com")
    _login(client, "crm-404-admin@example.com")
    _promote_to_admin(aws_endpoints, "crm-404-admin@example.com")
    _login(client, "crm-404-admin@example.com")

    response = client.get("/admin/customers/does-not-exist@example.com")
    assert response.status_code == 404


def test_customer_detail_shows_profile_and_orders(client, dynamodb_table, cognito_pool, aws_endpoints):
    _register_confirm(client, "crm-detail-customer@example.com")
    _login(client, "crm-detail-customer@example.com")

    # Place an order as this customer, which is the one reliable way to learn
    # their Cognito sub from the test side (the profile page never prints it).
    client.post(
        "/cart/add", data={"product_id": "vindlys-bureaulamp-zwart", "color": "Zwart", "quantity": "1"}
    )
    order_response = client.post("/checkout")
    html = order_response.get_data(as_text=True)
    start = html.index('data-testid="order-id">') + len('data-testid="order-id">')
    order_id = html[start : html.index("<", start)].strip()
    sub = single_table.get_order(order_id).user_sub

    single_table.put_user_profile(
        UserProfile(
            sub=sub,
            email="crm-detail-customer@example.com",
            given_name="Test",
            family_name="Klant",
            shipping_address=Address(street="Teststraat 1", postal_code="1234AB", city="Amsterdam"),
        )
    )
    client.post("/logout")

    _register_confirm(client, "crm-detail-admin@example.com")
    _login(client, "crm-detail-admin@example.com")
    _promote_to_admin(aws_endpoints, "crm-detail-admin@example.com")
    _login(client, "crm-detail-admin@example.com")

    html = client.get("/admin/customers/crm-detail-customer@example.com").get_data(as_text=True)
    assert "crm-detail-customer@example.com" in html
    assert "Teststraat 1" in html
    assert order_id in html


def test_customer_detail_handles_no_profile_or_orders(client, dynamodb_table, cognito_pool, aws_endpoints):
    _register_confirm(client, "crm-empty-customer@example.com")
    _login(client, "crm-empty-customer@example.com")
    client.post("/logout")

    _register_confirm(client, "crm-empty-admin@example.com")
    _login(client, "crm-empty-admin@example.com")
    _promote_to_admin(aws_endpoints, "crm-empty-admin@example.com")
    _login(client, "crm-empty-admin@example.com")

    html = client.get("/admin/customers/crm-empty-customer@example.com").get_data(as_text=True)
    assert 'data-testid="admin-customer-no-profile"' in html
    assert 'data-testid="admin-customer-no-orders"' in html
