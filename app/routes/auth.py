from botocore.exceptions import ClientError
from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.auth import cognito, session as session_module

bp = Blueprint("auth", __name__)

_ERROR_MESSAGES = {
    "UsernameExistsException": "Dit e-mailadres is al geregistreerd.",
    "InvalidPasswordException": (
        "Wachtwoord voldoet niet aan de eisen: minimaal 8 tekens, met een hoofdletter, "
        "een kleine letter en een cijfer."
    ),
    "InvalidParameterException": "Ongeldige invoer.",
    "CodeMismatchException": "Onjuiste verificatiecode.",
    "ExpiredCodeException": "Deze verificatiecode is verlopen. Vraag een nieuwe aan.",
    "LimitExceededException": "Te veel pogingen. Probeer het straks opnieuw.",
    # NotAuthorizedException and UserNotFoundException deliberately share one
    # generic message (both for login and for forgot-password) -- the Cognito
    # app client has prevent_user_existence_errors=ENABLED, and this app
    # follows that same policy at the UI layer: never reveal whether an
    # email is registered.
    "NotAuthorizedException": "Onjuiste combinatie van e-mailadres en wachtwoord.",
    "UserNotFoundException": "Onjuiste combinatie van e-mailadres en wachtwoord.",
}
_DEFAULT_ERROR_MESSAGE = "Er is iets misgegaan. Probeer het opnieuw."


def _cognito_error_message(error: ClientError) -> str:
    code = error.response["Error"]["Code"]
    return _ERROR_MESSAGES.get(code, _DEFAULT_ERROR_MESSAGE)


def _safe_next_url(next_url: str | None) -> str:
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return url_for("catalog.index")


@bp.get("/register")
def register():
    return render_template("auth/register.html")


@bp.post("/register")
def register_submit():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    password_confirm = request.form.get("password_confirm", "")

    if not email or not password:
        flash("Vul een e-mailadres en wachtwoord in.", "error")
        return render_template("auth/register.html", email=email), 400

    if password != password_confirm:
        flash("De wachtwoorden komen niet overeen.", "error")
        return render_template("auth/register.html", email=email), 400

    try:
        cognito.sign_up(email, password)
    except ClientError as error:
        flash(_cognito_error_message(error), "error")
        return render_template("auth/register.html", email=email), 400

    flash("Account aangemaakt. Check je e-mail voor de verificatiecode.", "success")
    return redirect(url_for("auth.confirm", email=email))


@bp.get("/confirm")
def confirm():
    return render_template("auth/confirm.html", email=request.args.get("email", ""))


@bp.post("/confirm")
def confirm_submit():
    email = request.form.get("email", "").strip().lower()
    action = request.form.get("action", "confirm")

    if action == "resend":
        try:
            cognito.resend_confirmation_code(email)
            flash("Nieuwe verificatiecode verstuurd.", "success")
        except ClientError as error:
            flash(_cognito_error_message(error), "error")
        return render_template("auth/confirm.html", email=email)

    code = request.form.get("code", "").strip()
    try:
        cognito.confirm_sign_up(email, code)
    except ClientError as error:
        flash(_cognito_error_message(error), "error")
        return render_template("auth/confirm.html", email=email), 400

    flash("Account bevestigd. Je kan nu inloggen.", "success")
    return redirect(url_for("auth.login"))


@bp.get("/login")
def login():
    return render_template("auth/login.html", next=request.args.get("next", ""))


@bp.post("/login")
def login_submit():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    next_url = request.form.get("next", "")

    try:
        auth_result = cognito.login(email, password)
    except ClientError as error:
        code = error.response["Error"]["Code"]
        if code == "UserNotConfirmedException":
            flash("Bevestig eerst je account met de verificatiecode.", "error")
            return redirect(url_for("auth.confirm", email=email))
        flash(_cognito_error_message(error), "error")
        return render_template("auth/login.html", email=email, next=next_url), 400

    sub = cognito.get_user_sub(auth_result["AccessToken"])
    groups = cognito.admin_list_groups(email)
    session_module.login_user(sub, email, groups)

    flash("Ingelogd.", "success")
    return redirect(_safe_next_url(next_url))


@bp.post("/logout")
def logout():
    # Cognito tokens are never persisted past login (see app/auth/session.py),
    # so there is no AccessToken left to call GlobalSignOut with -- only this
    # app's own session is destroyed. The old Cognito tokens remain valid
    # until their own ~1h expiry, but this app never accepts a raw Cognito
    # token as a credential again after login, only its own session_id, so
    # that's immaterial to this app's own access control.
    session_module.logout_user()
    flash("Uitgelogd.", "success")
    return redirect(url_for("catalog.index"))


@bp.get("/forgot-password")
def forgot_password():
    return render_template("auth/forgot_password.html")


@bp.post("/forgot-password")
def forgot_password_submit():
    email = request.form.get("email", "").strip().lower()
    try:
        cognito.forgot_password(email)
    except ClientError:
        # Deliberately swallowed: never reveal whether the email is
        # registered, matching prevent_user_existence_errors=ENABLED.
        pass

    flash("Als dit e-mailadres bekend is, is er een verificatiecode verstuurd.", "success")
    return redirect(url_for("auth.reset_password", email=email))


@bp.get("/reset-password")
def reset_password():
    return render_template("auth/reset_password.html", email=request.args.get("email", ""))


@bp.post("/reset-password")
def reset_password_submit():
    email = request.form.get("email", "").strip().lower()
    code = request.form.get("code", "").strip()
    new_password = request.form.get("password", "")
    new_password_confirm = request.form.get("password_confirm", "")

    if new_password != new_password_confirm:
        flash("De wachtwoorden komen niet overeen.", "error")
        return render_template("auth/reset_password.html", email=email), 400

    try:
        cognito.confirm_forgot_password(email, code, new_password)
    except ClientError as error:
        flash(_cognito_error_message(error), "error")
        return render_template("auth/reset_password.html", email=email), 400

    flash("Wachtwoord gewijzigd. Je kan nu inloggen.", "success")
    return redirect(url_for("auth.login"))
