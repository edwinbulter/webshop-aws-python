import os

import boto3

from app.models.user import Address, UserProfile
from app.repositories import single_table

PASSWORD = "StrongPassw0rd!"
PRODUCT_ID = "vindlys-bureaulamp-zwart"
PRODUCT_COLOR = "Zwart"


def _register_confirm_login(client, email):
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})
    client.post("/confirm", data={"email": email, "action": "confirm", "code": "123456"})
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})


def _promote_to_admin(aws_endpoints, email):
    idp = boto3.client("cognito-idp", region_name="eu-west-1", endpoint_url=aws_endpoints)
    idp.admin_add_user_to_group(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=email, GroupName="Admins"
    )


def test_anonymous_nav_shows_login_not_welcome(client, dynamodb_table):
    html = client.get("/").get_data(as_text=True)
    assert 'data-testid="nav-login"' in html
    assert "Welkom" not in html
    assert 'data-testid="account-menu"' not in html


def test_customer_nav_shows_welcome_and_dropdown_links(client, dynamodb_table, cognito_pool, aws_endpoints):
    _register_confirm_login(client, "navcustomer@example.com")
    html = client.get("/").get_data(as_text=True)

    assert 'data-testid="account-menu"' in html
    assert "Welkom" in html
    assert 'data-testid="nav-orders"' in html
    assert 'data-testid="nav-profile"' in html
    assert 'data-testid="nav-logout"' in html
    assert 'data-testid="nav-beheer"' not in html
    assert "Winkelwagen" in html


def test_customer_nav_welcome_uses_given_name_once_profile_is_filled_in(
    client, dynamodb_table, cognito_pool, aws_endpoints
):
    _register_confirm_login(client, "navname@example.com")
    # Fetch the sub the same way the app does: via the session record behind the cookie.
    with client.session_transaction() as flask_session:
        session_item = single_table.get_session(flask_session["session_id"])
    single_table.put_user_profile(
        UserProfile(
            sub=session_item["cognito_sub"],
            email="navname@example.com",
            given_name="Fictieve Voornaam",
            shipping_address=Address(),
            billing_address=Address(),
        )
    )

    html = client.get("/").get_data(as_text=True)
    assert "Fictieve Voornaam" in html


def test_admin_nav_shows_beheer_not_customer_links_and_no_cart(
    client, dynamodb_table, cognito_pool, aws_endpoints
):
    email = "navadmin@example.com"
    _register_confirm_login(client, email)
    _promote_to_admin(aws_endpoints, email)
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})

    html = client.get("/").get_data(as_text=True)
    assert 'data-testid="nav-beheer"' in html
    assert 'data-testid="nav-orders"' not in html
    assert 'data-testid="nav-profile"' not in html
    assert "Winkelwagen" not in html


def test_admin_cannot_view_or_add_to_cart(client, dynamodb_table, cognito_pool, aws_endpoints):
    email = "navadmin-cart@example.com"
    _register_confirm_login(client, email)
    _promote_to_admin(aws_endpoints, email)
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})

    assert client.get("/cart").status_code == 404
    response = client.post(
        "/cart/add", data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "1"}
    )
    assert response.status_code == 404
    assert client.post(f"/cart/items/{PRODUCT_ID}/quantity", data={"quantity": "2"}).status_code == 404
    assert client.post(f"/cart/items/{PRODUCT_ID}/remove").status_code == 404


def test_admin_cannot_checkout(client, dynamodb_table, cognito_pool, aws_endpoints):
    email = "navadmin-checkout@example.com"
    _register_confirm_login(client, email)
    _promote_to_admin(aws_endpoints, email)
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})

    assert client.post("/checkout").status_code == 404


def test_admin_login_drops_any_pre_existing_guest_cart(client, dynamodb_table, cognito_pool, aws_endpoints):
    # Add to cart as a guest first (same browser session an admin might share).
    client.post("/cart/add", data={"product_id": PRODUCT_ID, "color": PRODUCT_COLOR, "quantity": "1"})
    with client.session_transaction() as flask_session:
        assert "cart_id" in flask_session

    email = "navadmin-dropcart@example.com"
    _register_confirm_login(client, email)
    _promote_to_admin(aws_endpoints, email)
    # The *second* login, now that the account is in the Admins group, is the
    # one that must drop the inherited guest cart_id.
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})

    with client.session_transaction() as flask_session:
        assert "cart_id" not in flask_session
