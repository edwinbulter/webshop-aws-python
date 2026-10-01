import flask
import pytest

from app.auth.decorators import admin_required, login_required
from app.auth.session import CurrentUser


@pytest.fixture()
def minimal_app():
    """A standalone Flask app, independent of the real app/main.py, so these
    decorator tests don't depend on auth.bp/admin.bp existing yet (later steps)."""
    test_app = flask.Flask(__name__)
    test_app.config["SECRET_KEY"] = "test"

    auth_bp = flask.Blueprint("auth", __name__)

    @auth_bp.get("/login")
    def login():
        return "login page", 200

    test_app.register_blueprint(auth_bp)

    @test_app.before_request
    def establish_g_current_user_baseline():
        # Mirrors app/main.py's app.before_request(load_current_user): g.current_user
        # always exists (None or a CurrentUser) before any decorator runs.
        flask.g.current_user = getattr(flask.g, "current_user", None)

    @test_app.get("/protected")
    @login_required
    def protected():
        return "secret", 200

    @test_app.get("/admin-only")
    @admin_required
    def admin_only():
        return "admin secret", 200

    return test_app


def test_login_required_redirects_anonymous_to_login(minimal_app):
    response = minimal_app.test_client().get("/protected", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_required_allows_authenticated_user(minimal_app):
    @minimal_app.before_request
    def force_login():
        flask.g.current_user = CurrentUser(session_id="s", sub="sub", email="e@example.com")

    response = minimal_app.test_client().get("/protected")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "secret"


def test_admin_required_404s_for_anonymous(minimal_app):
    response = minimal_app.test_client().get("/admin-only")
    assert response.status_code == 404


def test_admin_required_404s_for_non_admin_customer(minimal_app):
    @minimal_app.before_request
    def force_customer():
        flask.g.current_user = CurrentUser(session_id="s", sub="sub", email="e@example.com", groups=[])

    response = minimal_app.test_client().get("/admin-only")
    assert response.status_code == 404


def test_admin_required_allows_admin(minimal_app):
    @minimal_app.before_request
    def force_admin():
        flask.g.current_user = CurrentUser(
            session_id="s", sub="sub", email="e@example.com", groups=["Admins"]
        )

    response = minimal_app.test_client().get("/admin-only")
    assert response.status_code == 200
