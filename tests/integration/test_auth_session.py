import time

import flask

from app.auth import session as session_module
from app.repositories import single_table
from app.session_cart import get_or_create_cart_id


def test_login_user_creates_session_record_and_cookie(app, dynamodb_table):
    with app.test_request_context():
        user = session_module.login_user("sub-1", "customer@example.com", [])

        assert flask.session["session_id"] == user.session_id
        assert user.cart_id  # a guest cart_id is created and carried forward

        resolved = session_module.resolve_current_user()
        assert resolved == user


def test_is_admin_reflects_group_membership(app, dynamodb_table):
    with app.test_request_context():
        customer = session_module.login_user("sub-2", "customer@example.com", [])
        assert customer.is_admin is False

    with app.test_request_context():
        admin = session_module.login_user("sub-3", "admin@example.com", ["Admins"])
        assert admin.is_admin is True


def test_logout_destroys_the_session_record_everywhere(app, dynamodb_table):
    with app.test_request_context():
        user = session_module.login_user("sub-4", "logout@example.com", [])
        session_id = user.session_id
        session_module.logout_user()
        assert flask.session.get("session_id") is None

    # Even presenting the old (now-dead) session_id again must resolve to nothing --
    # this is what makes logout actually immediate, unlike a client-held token.
    with app.test_request_context():
        flask.session["session_id"] = session_id
        assert session_module.resolve_current_user() is None


def test_expired_session_is_treated_as_absent(app, dynamodb_table):
    with app.test_request_context():
        single_table.create_session(
            session_id="expired-session",
            cognito_sub="sub-5",
            email="expired@example.com",
            groups=[],
            cart_id="cart-xyz",
            csrf_token="token",
            expires_at=int(time.time()) - 10,
        )
        flask.session["session_id"] = "expired-session"
        assert session_module.resolve_current_user() is None


def test_login_rotates_away_a_pre_existing_session(app, dynamodb_table):
    with app.test_request_context():
        first = session_module.login_user("sub-6", "first@example.com", [])
        first_id = first.session_id

        second = session_module.login_user("sub-7", "second@example.com", [])

        assert second.session_id != first_id
        assert single_table.get_session(first_id) is None


def test_cart_id_survives_login(app, dynamodb_table):
    with app.test_request_context():
        guest_cart_id = get_or_create_cart_id()
        user = session_module.login_user("sub-8", "cart@example.com", [])
        assert user.cart_id == guest_cart_id
        assert flask.session["cart_id"] == guest_cart_id


def test_csrf_token_verification(app, dynamodb_table):
    with app.test_request_context():
        user = session_module.login_user("sub-9", "csrf@example.com", [])
        session_module.load_current_user()

        assert session_module.verify_csrf_token(user.csrf_token) is True
        assert session_module.verify_csrf_token("wrong-token") is False
        assert session_module.verify_csrf_token("") is False


def test_resolve_current_user_without_cookie_is_none(app, dynamodb_table):
    with app.test_request_context():
        assert session_module.resolve_current_user() is None


def test_app_before_request_wiring_does_not_break_existing_guest_routes(client, dynamodb_table):
    """Regression check for app/main.py's new before_request(load_current_user) +
    context_processor: every existing guest route must keep working unchanged."""
    response = client.get("/")
    assert response.status_code == 200
    with client.session_transaction() as flask_session:
        assert "session_id" not in flask_session


def test_app_before_request_resolves_a_real_logged_in_session(client, dynamodb_table):
    single_table.create_session(
        session_id="wiring-test-session",
        cognito_sub="sub-wiring",
        email="wiring@example.com",
        groups=["Admins"],
        cart_id="cart-wiring",
        csrf_token="token-wiring",
        expires_at=int(time.time()) + 3600,
    )
    with client.session_transaction() as flask_session:
        flask_session["session_id"] = "wiring-test-session"

    response = client.get("/")
    assert response.status_code == 200
