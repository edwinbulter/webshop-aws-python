import os

import boto3

PASSWORD = "StrongPassw0rd!"


def _register_confirm_login(client, email):
    client.post("/register", data={"email": email, "password": PASSWORD, "password_confirm": PASSWORD})
    client.post("/confirm", data={"email": email, "action": "confirm", "code": "123456"})
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})


def _admin_rule_endpoints(app) -> list[str]:
    return [rule.endpoint for rule in app.url_map.iter_rules() if rule.rule.startswith("/admin")]


def test_admin_ping_rejects_anonymous_visitor(client, dynamodb_table, cognito_pool):
    response = client.get("/admin/ping")
    assert response.status_code == 404


def test_admin_ping_rejects_authenticated_customer(client, dynamodb_table, cognito_pool):
    _register_confirm_login(client, "customer-not-admin@example.com")
    response = client.get("/admin/ping")
    assert response.status_code == 404


def test_admin_ping_allows_admin(client, dynamodb_table, cognito_pool, aws_endpoints):
    email = "real-admin@example.com"
    _register_confirm_login(client, email)

    idp = boto3.client("cognito-idp", region_name="eu-west-1", endpoint_url=aws_endpoints)
    idp.admin_add_user_to_group(
        UserPoolId=os.environ["COGNITO_USER_POOL_ID"], Username=email, GroupName="Admins"
    )
    # Group membership is cached at login time, so the admin must log in again
    # after being promoted for AdminListGroupsForUser to be re-queried.
    client.post("/login", data={"email": email, "password": PASSWORD, "next": ""})

    response = client.get("/admin/ping")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "pong"


def test_every_admin_route_rejects_anonymous_and_non_admin_sessions(
    client, app, dynamodb_table, cognito_pool
):
    endpoints = _admin_rule_endpoints(app)
    assert endpoints, "expected at least one /admin/* route to exist"

    for rule in app.url_map.iter_rules():
        if rule.endpoint not in endpoints:
            continue
        if "GET" not in rule.methods:
            continue
        url = rule.rule
        if "<" in url:
            continue

        anonymous_response = client.get(url)
        assert anonymous_response.status_code == 404, f"{url} did not 404 for an anonymous visitor"

    _register_confirm_login(client, "non-admin-sweep@example.com")
    for rule in app.url_map.iter_rules():
        if rule.endpoint not in endpoints:
            continue
        if "GET" not in rule.methods:
            continue
        url = rule.rule
        if "<" in url:
            continue

        customer_response = client.get(url)
        assert customer_response.status_code == 404, f"{url} did not 404 for a logged-in non-admin customer"
