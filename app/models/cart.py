from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CartItem:
    cart_id: str
    product_id: str
    title: str
    image_url: str
    color: str
    quantity: int
    price_cents: int

    @property
    def line_total_cents(self) -> int:
        return self.quantity * self.price_cents

    @property
    def price_display(self) -> str:
        return f"€ {self.price_cents / 100:.2f}"

    @property
    def line_total_display(self) -> str:
        return f"€ {self.line_total_cents / 100:.2f}"

    def to_item(self) -> dict:
        return {
            "PK": f"CART#{self.cart_id}",
            "SK": f"ITEM#{self.product_id}",
            "cart_id": self.cart_id,
            "product_id": self.product_id,
            "title": self.title,
            "image_url": self.image_url,
            "color": self.color,
            "quantity": self.quantity,
            "price_cents": self.price_cents,
        }

    @staticmethod
    def from_item(item: dict) -> "CartItem":
        return CartItem(
            cart_id=item["cart_id"],
            product_id=item["product_id"],
            title=item["title"],
            image_url=item["image_url"],
            color=item["color"],
            quantity=int(item["quantity"]),
            price_cents=int(item["price_cents"]),
        )
