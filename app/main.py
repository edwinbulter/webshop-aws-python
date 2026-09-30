import os

from asgiref.wsgi import WsgiToAsgi
from flask import Flask, render_template, request
from mangum import Mangum
from werkzeug.exceptions import HTTPException

from app.routes import cart, catalog, checkout

CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net https://cdn.tailwindcss.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https://www.ikea.com; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_DEBUG") != "1"
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(catalog.bp)
    app.register_blueprint(cart.bp)
    app.register_blueprint(checkout.bp)

    @app.after_request
    def set_security_headers(response):
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.errorhandler(404)
    def not_found(_error):
        message = "Pagina niet gevonden."
        if request.headers.get("HX-Request"):
            return render_template("_error_fragment.html", message=message), 404
        return render_template("error.html", message=message), 404

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        app.logger.exception("Unhandled exception while handling %s %s", request.method, request.path)
        message = "Er is een onverwachte fout opgetreden. Probeer het later opnieuw."
        if request.headers.get("HX-Request"):
            return render_template("_error_fragment.html", message=message), 500
        return render_template("error.html", message=message), 500

    return app


app = create_app()
handler = Mangum(WsgiToAsgi(app), lifespan="off")
