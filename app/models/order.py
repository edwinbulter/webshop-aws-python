from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class OrderLine:
    product_id: str
    title: str
    color: str
    quantity: int
    price_cents: int

    def to_item(self, order_id: str) -> dict:
        return {
            "PK": f"ORDER#{order_id}",
            "SK": f"ITEM#{self.product_id}",
            "product_id": self.product_id,
            "title": self.title,
            "color": self.color,
            "quantity": self.quantity,
            "price_cents": self.price_cents,
        }

    @staticmethod
    def from_item(item: dict) -> "OrderLine":
        return OrderLine(
            product_id=item["product_id"],
            title=item["title"],
            color=item["color"],
            quantity=int(item["quantity"]),
            price_cents=int(item["price_cents"]),
        )


@dataclass(frozen=True)
class Order:
    id: str
    status: str
    total_cents: int
    created_at: str
    lines: list[OrderLine] = field(default_factory=list)

    @property
    def total_display(self) -> str:
        return f"€ {self.total_cents / 100:.2f}"

    @staticmethod
    def new(order_id: str, lines: list[OrderLine]) -> "Order":
        total_cents = sum(line.quantity * line.price_cents for line in lines)
        return Order(
            id=order_id,
            status="PLACED",
            total_cents=total_cents,
            created_at=datetime.now(timezone.utc).isoformat(),
            lines=lines,
        )

    def to_metadata_item(self) -> dict:
        return {
            "PK": f"ORDER#{self.id}",
            "SK": "METADATA",
            "id": self.id,
            "status": self.status,
            "total_cents": self.total_cents,
            "created_at": self.created_at,
        }
