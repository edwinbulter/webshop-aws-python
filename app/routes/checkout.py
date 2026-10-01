import uuid

from flask import Blueprint, abort, g, render_template

from app.config import MAX_ITEM_QUANTITY, MIN_ITEM_QUANTITY
from app.events.publisher import publish_order_placed
from app.models.order import Order, OrderLine
from app.repositories import single_table
from app.session_cart import get_or_create_cart_id

bp = Blueprint("checkout", __name__)


@bp.before_request
def require_non_admin():
    if g.current_user is not None and g.current_user.is_admin:
        abort(404)


@bp.post("/checkout")
def checkout():
    cart_id = get_or_create_cart_id()
    cart_items = single_table.get_cart_items(cart_id)

    if not cart_items:
        return render_template("_error_fragment.html", message="Je winkelwagen is leeg."), 400

    lines: list[OrderLine] = []
    for item in cart_items:
        product = single_table.get_product(item.product_id)
        if product is None or item.color not in product.colors:
            return (
                render_template(
                    "_error_fragment.html",
                    message=f"'{item.title}' is niet meer beschikbaar in de gekozen kleur.",
                ),
                400,
            )
        quantity = max(MIN_ITEM_QUANTITY, min(MAX_ITEM_QUANTITY, item.quantity))
        lines.append(
            OrderLine(
                product_id=product.id,
                title=product.title,
                color=item.color,
                quantity=quantity,
                price_cents=product.price_cents,
                image_url=product.image_url,
            )
        )

    user_sub = g.current_user.sub if g.current_user else None
    order = Order.new(order_id=str(uuid.uuid4()), lines=lines, user_sub=user_sub)
    single_table.create_order(order)
    single_table.clear_cart(cart_id)
    publish_order_placed(order)

    return render_template("_order_confirmation.html", order=order)
