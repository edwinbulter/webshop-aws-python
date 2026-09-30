from flask import Blueprint, render_template, request

from app.config import MAX_ITEM_QUANTITY, MIN_ITEM_QUANTITY
from app.repositories import single_table
from app.session_cart import get_or_create_cart_id

bp = Blueprint("cart", __name__)


def _cart_total_cents(cart_items) -> int:
    return sum(item.line_total_cents for item in cart_items)


def _cart_count(cart_items) -> int:
    return sum(item.quantity for item in cart_items)


@bp.get("/cart")
def view_cart():
    cart_id = get_or_create_cart_id()
    cart_items = single_table.get_cart_items(cart_id)
    return render_template(
        "cart.html",
        cart_items=cart_items,
        cart_total_cents=_cart_total_cents(cart_items),
        cart_count=_cart_count(cart_items),
    )


@bp.post("/cart/add")
def add_to_cart():
    cart_id = get_or_create_cart_id()
    product_id = request.form.get("product_id", "")
    color = request.form.get("color", "")

    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = MIN_ITEM_QUANTITY
    quantity = max(MIN_ITEM_QUANTITY, min(MAX_ITEM_QUANTITY, quantity))

    product = single_table.get_product(product_id)
    if product is None or color not in product.colors:
        return render_template("_error_fragment.html", message="Product of kleur niet gevonden."), 400

    single_table.add_cart_item(cart_id, product, color, quantity)
    cart_items = single_table.get_cart_items(cart_id)
    return render_template("_add_to_cart_status.html", cart_count=_cart_count(cart_items))


@bp.post("/cart/clear")
def clear_cart():
    cart_id = get_or_create_cart_id()
    single_table.clear_cart(cart_id)
    return render_template("_cart_contents.html", cart_items=[], cart_total_cents=0, cart_count=0)
