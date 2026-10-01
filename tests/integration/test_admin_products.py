import os
import re

import boto3

from app.repositories import single_table

PASSWORD = "StrongPassw0rd!"
PRODUCT_ID = "vindlys-bureaulamp-zwart"


def _login_as_admin(client, aws_endpoints, email):
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})
    client.post("/confirm", data={"email": email, "action": "confirm", "code": "123456"})
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})
    idp = boto3.client("cognito-idp", region_name="eu-west-1", endpoint_url=aws_endpoints)
    idp.admin_add_user_to_group(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=email, GroupName="Admins"
    )
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})


def _csrf_token(client) -> str:
    html = client.get("/admin").get_data(as_text=True)
    marker = 'data-testid="admin-csrf-token"'
    marker_pos = html.index(marker)
    tag_start = html.rindex("<input", 0, marker_pos)
    value_start = html.index('value="', tag_start) + len('value="')
    return html[value_start : html.index('"', value_start)]


def test_products_list_shows_catalog_products(client, dynamodb_table, cognito_pool, aws_endpoints):
    _login_as_admin(client, aws_endpoints, "products-list-admin@example.com")
    html = client.get("/admin/products").get_data(as_text=True)
    assert PRODUCT_ID in html


def test_product_detail_404s_for_unknown_product(client, dynamodb_table, cognito_pool, aws_endpoints):
    _login_as_admin(client, aws_endpoints, "products-404-admin@example.com")
    response = client.get("/admin/products/does-not-exist")
    assert response.status_code == 404


def test_product_detail_shows_a_stock_input_per_color(client, dynamodb_table, cognito_pool, aws_endpoints):
    _login_as_admin(client, aws_endpoints, "products-detail-admin@example.com")
    html = client.get(f"/admin/products/{PRODUCT_ID}").get_data(as_text=True)
    assert 'data-testid="stock-input-Zwart"' in html
    assert 'data-testid="stock-input-Wit"' in html
    assert 'data-testid="stock-input-Vernikkeld"' in html


def test_update_stock_persists_values_per_color(client, dynamodb_table, cognito_pool, aws_endpoints):
    _login_as_admin(client, aws_endpoints, "products-update-admin@example.com")
    csrf_token = _csrf_token(client)

    response = client.post(
        f"/admin/products/{PRODUCT_ID}/stock",
        data={"csrf_token": csrf_token, "stock_Zwart": "5", "stock_Wit": "0", "stock_Vernikkeld": "12"},
    )
    assert response.status_code == 302

    variants = {v.color: v.stock_qty for v in single_table.list_variants(PRODUCT_ID)}
    assert variants == {"Zwart": 5, "Wit": 0, "Vernikkeld": 12}

    html = client.get(f"/admin/products/{PRODUCT_ID}").get_data(as_text=True)
    assert 'name="stock_Zwart" value="5"' in html


def test_update_stock_rejects_missing_csrf_token(client, dynamodb_table, cognito_pool, aws_endpoints):
    _login_as_admin(client, aws_endpoints, "products-update-csrf-admin@example.com")

    response = client.post(f"/admin/products/{PRODUCT_ID}/stock", data={"stock_Zwart": "99"})
    assert response.status_code == 400


def test_products_list_shows_total_stock_across_colors(client, dynamodb_table, cognito_pool, aws_endpoints):
    # The product table is session-scoped, so every color must be pinned
    # explicitly here -- otherwise a prior test's leftover stock on a color
    # this test doesn't touch would silently change the expected total.
    single_table.put_variant_stock(PRODUCT_ID, "Zwart", 3)
    single_table.put_variant_stock(PRODUCT_ID, "Wit", 4)
    single_table.put_variant_stock(PRODUCT_ID, "Vernikkeld", 0)
    _login_as_admin(client, aws_endpoints, "products-total-admin@example.com")

    html = client.get("/admin/products").get_data(as_text=True)
    assert re.search(r'data-testid="admin-product-stock">\s*7\s*</p>', html)
