from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

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
