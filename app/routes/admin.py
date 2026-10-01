from collections import Counter

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from app.auth import cognito
from app.auth.session import verify_csrf_token
from app.models.order import ADMIN_NEXT_STATUS, ORDER_STATUS_LABELS, OrderStatus
from app.repositories import single_table


bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
def require_admin():
    # 404, never 403 -- an anonymous visitor or a logged-in customer gets the
    # exact same "page not found" as a route that doesn't exist at all, same
    # principle as the order-ownership check in app/routes/account.py.
    if g.current_user is None or not g.current_user.is_admin:
        abort(404)


@bp.get("/ping")
def ping():
    return "pong"


@bp.get("")
def dashboard():
    orders = single_table.list_all_orders()
    returns = single_table.list_all_returns()
    status_counts = Counter(order.status for order in orders)
    status_breakdown = [
        (label, status_counts.get(status, 0)) for status, label in ORDER_STATUS_LABELS.items()
    ]

    return render_template(
        "admin/dashboard.html",
        total_orders=len(orders),
        status_breakdown=status_breakdown,
        pending_returns_count=len(returns),
        recent_orders=orders[:10],
    )


@bp.get("/orders")
def orders():
    status_filter = request.args.get("status", "")
    all_orders = single_table.list_all_orders()
    if status_filter:
        all_orders = [order for order in all_orders if order.status == status_filter]
    return render_template(
        "admin/orders.html",
        orders=all_orders,
        status_filter=status_filter,
        status_labels=ORDER_STATUS_LABELS,
    )


def _get_order_or_404(order_id: str):
    order = single_table.get_order(order_id)
    if order is None:
        abort(404)
    return order


def _stock_shortages(order) -> list:
    """Order lines whose color doesn't have enough stock to ship right now --
    only meaningful for the IN_PROGRESS -> SHIPPED step, which is the one
    transition that consumes stock (see advance_order)."""
    return [
        line
        for line in order.lines
        if single_table.get_variant_stock(line.product_id, line.color) < line.quantity
    ]


@bp.get("/orders/<order_id>")
def order_detail(order_id: str):
    order = _get_order_or_404(order_id)
    return_request = single_table.get_return_request(order_id)
    next_status = ADMIN_NEXT_STATUS.get(order.status)
    stock_shortages = _stock_shortages(order) if next_status == OrderStatus.SHIPPED else []
    return render_template(
        "admin/order_detail.html",
        order=order,
        return_request=return_request,
        next_status=next_status,
        next_status_label=ORDER_STATUS_LABELS.get(next_status) if next_status else None,
        stock_shortages=stock_shortages,
    )


@bp.post("/orders/<order_id>/advance")
def advance_order(order_id: str):
    if not verify_csrf_token(request.form.get("csrf_token", "")):
        abort(400)
    order = _get_order_or_404(order_id)

    next_status = ADMIN_NEXT_STATUS.get(order.status)
    if next_status is None:
        flash("Voor deze bestelling is geen volgende stap beschikbaar.", "error")
        return redirect(url_for("admin.order_detail", order_id=order_id))

    if next_status == OrderStatus.SHIPPED:
        shortages = _stock_shortages(order)
        if shortages:
            names = ", ".join(f"{line.title} ({line.color})" for line in shortages)
            flash(
                f"Onvoldoende voorraad om te verzenden: {names}. Verhoog eerst de voorraad.",
                "error",
            )
            return redirect(url_for("admin.order_detail", order_id=order_id))

        for line in order.lines:
            if not single_table.decrement_variant_stock(line.product_id, line.color, line.quantity):
                # Only reachable via a genuine race (stock changed between the
                # check above and this write) -- the lines before this one in
                # the loop have already been decremented and are deliberately
                # not rolled back (no dynamodb:TransactWriteItems in this PoC's
                # IAM policy; see README's "Admin-backoffice" scope note).
                flash("Voorraad is ondertussen gewijzigd. Probeer het opnieuw.", "error")
                return redirect(url_for("admin.order_detail", order_id=order_id))

    if single_table.set_order_status(order_id, next_status, allowed_from={order.status}):
        flash(f"Status bijgewerkt naar '{ORDER_STATUS_LABELS[next_status]}'.", "success")
    else:
        flash("De status is ondertussen al gewijzigd.", "error")

    return redirect(url_for("admin.order_detail", order_id=order_id))


@bp.get("/returns")
def returns():
    return_requests = single_table.list_all_returns()
    orders_by_id = {
        return_request.order_id: single_table.get_order(return_request.order_id)
        for return_request in return_requests
    }
    return render_template("admin/returns.html", return_requests=return_requests, orders_by_id=orders_by_id)


def _get_product_or_404(product_id: str):
    product = single_table.get_product(product_id)
    if product is None:
        abort(404)
    return product


@bp.get("/products")
def products():
    all_products = single_table.list_products()
    stock_by_product_id = {
        product.id: sum(variant.stock_qty for variant in single_table.list_variants(product.id))
        for product in all_products
    }
    return render_template(
        "admin/products.html", products=all_products, stock_by_product_id=stock_by_product_id
    )


@bp.get("/products/<product_id>")
def product_detail(product_id: str):
    product = _get_product_or_404(product_id)
    stock_by_color = {variant.color: variant.stock_qty for variant in single_table.list_variants(product_id)}
    variants = [(color, stock_by_color.get(color, 0)) for color in product.colors]
    return render_template("admin/product_detail.html", product=product, variants=variants)


@bp.post("/products/<product_id>/stock")
def update_stock(product_id: str):
    if not verify_csrf_token(request.form.get("csrf_token", "")):
        abort(400)
    product = _get_product_or_404(product_id)

    for color in product.colors:
        raw_value = request.form.get(f"stock_{color}", "").strip()
        if not raw_value:
            continue
        try:
            stock_qty = int(raw_value)
        except ValueError:
            continue
        if stock_qty < 0:
            continue
        single_table.put_variant_stock(product_id, color, stock_qty)

    flash("Voorraad bijgewerkt.", "success")
    return redirect(url_for("admin.product_detail", product_id=product_id))


@bp.get("/customers")
def customers():
    return render_template("admin/customers.html", customers=cognito.list_users())


@bp.get("/customers/<email>")
def customer_detail(email: str):
    customer = cognito.get_user(email)
    if customer is None:
        abort(404)
    sub = customer["sub"]
    profile = single_table.get_user_profile(sub)
    orders = single_table.list_orders_for_customer(sub)
    return render_template("admin/customer_detail.html", customer=customer, profile=profile, orders=orders)
