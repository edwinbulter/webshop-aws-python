import uuid

from flask import session


def get_or_create_cart_id() -> str:
    cart_id = session.get("cart_id")
    if not cart_id:
        cart_id = str(uuid.uuid4())
        session["cart_id"] = cart_id
    return cart_id
