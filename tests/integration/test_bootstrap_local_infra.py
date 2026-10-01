from app.auth import cognito
from app.repositories import single_table
from scripts.bootstrap_local_infra import (
    _DEMO_ADMIN_EMAIL,
    _DEMO_CUSTOMER_EMAIL,
    _DEMO_PASSWORD,
    ensure_cognito_pool_exists,
    ensure_demo_users_exist,
)


def test_ensure_cognito_pool_exists_is_idempotent(aws_endpoints):
    # Re-running `scripts.bootstrap_local_infra` against an already-running
    # local moto-server must reuse the same pool/client, not create duplicates.
    first = ensure_cognito_pool_exists()
    second = ensure_cognito_pool_exists()
    assert first == second


def test_local_cognito_pool_supports_signup_and_login(aws_endpoints, monkeypatch):
    pool = ensure_cognito_pool_exists()
    # monkeypatch, not os.environ directly, so these don't leak into the rest
    # of the suite, which points COGNITO_* at the separate `cognito_pool`
    # fixture's own pool/client.
    monkeypatch.setenv("COGNITO_USER_POOL_ID", pool["pool_id"])
    monkeypatch.setenv("COGNITO_CLIENT_ID", pool["client_id"])
    monkeypatch.setenv("COGNITO_CLIENT_SECRET", pool["client_secret"])

    cognito.sign_up("local-bootstrap@example.com", "StrongPassw0rd!")
    cognito.confirm_sign_up("local-bootstrap@example.com", "123456")
    auth_result = cognito.login("local-bootstrap@example.com", "StrongPassw0rd!")

    assert "AccessToken" in auth_result


def test_demo_users_can_log_in_and_have_the_right_roles(aws_endpoints, dynamodb_table, monkeypatch):
    pool = ensure_cognito_pool_exists()
    ensure_demo_users_exist(pool["pool_id"])
    # Re-running must stay idempotent -- not raise UsernameExistsException.
    ensure_demo_users_exist(pool["pool_id"])

    monkeypatch.setenv("COGNITO_USER_POOL_ID", pool["pool_id"])
    monkeypatch.setenv("COGNITO_CLIENT_ID", pool["client_id"])
    monkeypatch.setenv("COGNITO_CLIENT_SECRET", pool["client_secret"])

    cognito.login(_DEMO_ADMIN_EMAIL, _DEMO_PASSWORD)
    cognito.login(_DEMO_CUSTOMER_EMAIL, _DEMO_PASSWORD)
    assert cognito.admin_list_groups(_DEMO_ADMIN_EMAIL) == ["Admins"]
    assert cognito.admin_list_groups(_DEMO_CUSTOMER_EMAIL) == []


def test_demo_customer_has_a_filled_in_profile_with_matching_addresses(
    aws_endpoints, dynamodb_table, monkeypatch
):
    pool = ensure_cognito_pool_exists()
    ensure_demo_users_exist(pool["pool_id"])
    monkeypatch.setenv("COGNITO_USER_POOL_ID", pool["pool_id"])

    customer_sub = next(user["sub"] for user in cognito.list_users() if user["email"] == _DEMO_CUSTOMER_EMAIL)
    profile = single_table.get_user_profile(customer_sub)

    assert profile is not None
    assert profile.given_name
    assert profile.family_name
    assert profile.shipping_address.street
    assert profile.billing_address == profile.shipping_address
