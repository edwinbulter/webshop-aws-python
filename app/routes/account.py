import json
from datetime import datetime, timedelta, timezone

from botocore.exceptions import ClientError
from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for

from app.auth import cognito
from app.auth import session as session_module
from app.auth.session import verify_csrf_token
from app.config import RETURN_WINDOW_DAYS
from app.models.order import CANCELLABLE_STATUSES, RETURNABLE_STATUSES, OrderStatus
from app.models.return_request import ReturnRequest
from app.models.user import Address, UserProfile
from app.repositories import single_table


bp = Blueprint("account", __name__, url_prefix="/account")


@bp.before_request
def require_login():
    if g.current_user is None:
        return redirect(url_for("auth.login", next=request.path))


def _address_from_form(prefix: str) -> Address:
    return Address(
        name=request.form.get(f"{prefix}_name", "").strip(),
        street=request.form.get(f"{prefix}_street", "").strip(),
        postal_code=request.form.get(f"{prefix}_postal_code", "").strip(),
        city=request.form.get(f"{prefix}_city", "").strip(),
        country=request.form.get(f"{prefix}_country", "").strip(),
    )


@bp.get("")
def profile():
    user_profile = single_table.get_user_profile(g.current_user.sub)
    if user_profile is None:
        user_profile = UserProfile(sub=g.current_user.sub, email=g.current_user.email)
    return render_template("account/profile.html", profile=user_profile)


@bp.post("")
def profile_submit():
    if not verify_csrf_token(request.form.get("csrf_token", "")):
        abort(400)

    user_profile = UserProfile(
        sub=g.current_user.sub,
        email=g.current_user.email,
        given_name=request.form.get("given_name", "").strip(),
        family_name=request.form.get("family_name", "").strip(),
        shipping_address=_address_from_form("shipping"),
        billing_address=_address_from_form("billing"),
    )
    single_table.put_user_profile(user_profile)

    flash("Profiel bijgewerkt.", "success")
    return redirect(url_for("account.profile"))


@bp.get("/export")
def export_data():
    """AVG Art. 20 (right to data portability) -- a structured, machine-readable
    (JSON) export of everything this account's own pages let someone see about
    themselves: their profile and their order history. Internal storage details
    (PK/SK, GSI keys) are deliberately left out -- this is the person's data,
    not a dump of this app's DynamoDB item shape."""
    profile = single_table.get_user_profile(g.current_user.sub)
    orders = [
        single_table.get_order(order.id)
        for order in single_table.list_orders_for_customer(g.current_user.sub)
    ]

    payload = {
        "profiel": (
            {
                "email": profile.email,
                "voornaam": profile.given_name,
                "achternaam": profile.family_name,
                "afleveradres": profile.shipping_address.to_dict(),
                "factuuradres": profile.billing_address.to_dict(),
            }
            if profile
            else None
        ),
        "bestellingen": [
            {
                "id": order.id,
                "status": order.status_label,
                "geplaatst_op": order.created_at,
                "totaal": order.total_display,
                "regels": [
                    {
                        "product": line.title,
                        "kleur": line.color,
                        "aantal": line.quantity,
                        "prijs_per_stuk": f"€ {line.price_cents / 100:.2f}",
                    }
                    for line in order.lines
                ],
            }
            for order in orders
            if order is not None
        ],
    }

    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=mijn-gegevens.json"},
    )


def _get_own_order_or_404(order_id: str):
    """404, never 403, and identical for "doesn't exist" vs. "not yours" --
    an order-detail request never reveals whether an order exists at all."""
    order = single_table.get_order(order_id)
    if order is None or order.user_sub != g.current_user.sub:
        abort(404)
    return order


@bp.get("/orders")
def orders():
    customer_orders = single_table.list_orders_for_customer(g.current_user.sub)
    return render_template("account/orders.html", orders=customer_orders)


def _within_return_window(order) -> bool:
    created_at = datetime.fromisoformat(order.created_at)
    return datetime.now(timezone.utc) - created_at <= timedelta(days=RETURN_WINDOW_DAYS)


@bp.get("/orders/<order_id>")
def order_detail(order_id: str):
    order = _get_own_order_or_404(order_id)
    existing_return = single_table.get_return_request(order_id)
    can_cancel = order.status in CANCELLABLE_STATUSES
    can_report_return = (
        order.status in RETURNABLE_STATUSES and existing_return is None and _within_return_window(order)
    )
    return render_template(
        "account/order_detail.html",
        order=order,
        can_cancel=can_cancel,
        can_report_return=can_report_return,
        existing_return=existing_return,
        return_window_days=RETURN_WINDOW_DAYS,
    )


@bp.post("/orders/<order_id>/cancel")
def cancel_order(order_id: str):
    if not verify_csrf_token(request.form.get("csrf_token", "")):
        abort(400)
    _get_own_order_or_404(order_id)

    if single_table.set_order_status(order_id, OrderStatus.CANCELLED, allowed_from=CANCELLABLE_STATUSES):
        flash("Bestelling geannuleerd.", "success")
    else:
        flash("Deze bestelling kan niet meer geannuleerd worden.", "error")
    return redirect(url_for("account.order_detail", order_id=order_id))


@bp.post("/orders/<order_id>/return")
def report_return(order_id: str):
    if not verify_csrf_token(request.form.get("csrf_token", "")):
        abort(400)
    order = _get_own_order_or_404(order_id)
    reason = request.form.get("reason", "").strip()

    if order.status not in RETURNABLE_STATUSES:
        flash("Voor deze bestelling kan geen retour gemeld worden.", "error")
    elif not _within_return_window(order):
        flash(f"De retourtermijn van {RETURN_WINDOW_DAYS} dagen is verstreken.", "error")
    elif not reason:
        flash("Geef een reden op voor de retour.", "error")
    elif not single_table.set_order_status(
        order_id, OrderStatus.RETURN_REPORTED, allowed_from=RETURNABLE_STATUSES
    ):
        flash("Voor deze bestelling kan geen retour gemeld worden.", "error")
    else:
        single_table.create_return_request(ReturnRequest.new(order_id, reason))
        flash("Retour gemeld.", "success")

    return redirect(url_for("account.order_detail", order_id=order_id))


@bp.get("/delete")
def delete_account_confirm():
    return render_template("account/delete.html")


@bp.post("/delete")
def delete_account():
    """AVG Art. 17 (right to erasure). Deletes the Cognito account and the
    profile (name/address) -- the identifying data. Deliberately does NOT
    touch this sub's orders: see
    single_table.delete_user_profile's docstring and
    docs/gdpr-nis2-compliance.md for why order retention is a separate
    decision (Dutch bookkeeping-retention law), not the same choice as
    "delete my account"."""
    if not verify_csrf_token(request.form.get("csrf_token", "")):
        abort(400)

    password = request.form.get("password", "")
    try:
        cognito.login(g.current_user.email, password)
    except ClientError:
        flash("Onjuist wachtwoord. Je account is niet verwijderd.", "error")
        return redirect(url_for("account.delete_account_confirm"))

    sub = g.current_user.sub
    email = g.current_user.email
    cognito.admin_delete_user(email)
    single_table.delete_user_profile(sub)
    session_module.logout_user()

    flash("Je account is verwijderd.", "success")
    return redirect(url_for("catalog.index"))
