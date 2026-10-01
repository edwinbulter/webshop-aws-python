from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class OrderStatus(StrEnum):
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    IN_PROGRESS = "IN_PROGRESS"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURN_REPORTED = "RETURN_REPORTED"
    RETURN_COMPLETED = "RETURN_COMPLETED"


ORDER_STATUS_LABELS: dict[str, str] = {
    OrderStatus.AWAITING_PAYMENT: "In afwachting van betaling",
    OrderStatus.IN_PROGRESS: "In behandeling",
    OrderStatus.SHIPPED: "Verzonden",
    OrderStatus.DELIVERED: "Afgeleverd",
    OrderStatus.CANCELLED: "Geannuleerd",
    OrderStatus.RETURN_REPORTED: "Retour gemeld",
    OrderStatus.RETURN_COMPLETED: "Retour verwerkt",
}

# Cancel: only while nothing has shipped yet. Report a return: only once
# something has actually shipped/arrived. Both sets are used as the
# ConditionExpression guard in single_table.set_order_status, so a race (e.g.
# a concurrent admin status update) fails the transition instead of silently
# corrupting it.
CANCELLABLE_STATUSES = {OrderStatus.AWAITING_PAYMENT, OrderStatus.IN_PROGRESS}
RETURNABLE_STATUSES = {OrderStatus.SHIPPED, OrderStatus.DELIVERED}

# Admin-driven forward transitions for the Orders & Logistics screen -- manual
# fulfilment steps (no shipping-carrier integration exists in this PoC) and
# the one admin-only step of finishing a reported return.
ADMIN_NEXT_STATUS: dict[str, str] = {
    OrderStatus.IN_PROGRESS: OrderStatus.SHIPPED,
    OrderStatus.SHIPPED: OrderStatus.DELIVERED,
    OrderStatus.RETURN_REPORTED: OrderStatus.RETURN_COMPLETED,
}


@dataclass(frozen=True)
class OrderLine:
    product_id: str
    title: str
    color: str
    quantity: int
    price_cents: int
    # Snapshotted at checkout time, same reasoning as price_cents/title: the
    # order should keep showing the photo as it was at purchase time, not
    # whatever the product's image happens to be today.
    image_url: str = ""

    def to_item(self, order_id: str) -> dict:
        return {
            "PK": f"ORDER#{order_id}",
            "SK": f"ITEM#{self.product_id}",
            "product_id": self.product_id,
            "title": self.title,
            "color": self.color,
            "quantity": self.quantity,
            "price_cents": self.price_cents,
            "image_url": self.image_url,
        }

    @staticmethod
    def from_item(item: dict) -> "OrderLine":
        return OrderLine(
            product_id=item["product_id"],
            title=item["title"],
            color=item["color"],
            quantity=int(item["quantity"]),
            price_cents=int(item["price_cents"]),
            # Absent on orders placed before this field existed.
            image_url=item.get("image_url", ""),
        )


@dataclass(frozen=True)
class Order:
    id: str
    status: str
    total_cents: int
    created_at: str
    lines: list[OrderLine] = field(default_factory=list)
    user_sub: str | None = None

    @property
    def total_display(self) -> str:
        return f"€ {self.total_cents / 100:.2f}"

    @property
    def status_label(self) -> str:
        return ORDER_STATUS_LABELS.get(self.status, self.status)

    @property
    def created_at_display(self) -> str:
        return datetime.fromisoformat(self.created_at).strftime("%d-%m-%Y %H:%M")

    @staticmethod
    def new(order_id: str, lines: list[OrderLine], user_sub: str | None = None) -> "Order":
        total_cents = sum(line.quantity * line.price_cents for line in lines)
        return Order(
            id=order_id,
            status=OrderStatus.AWAITING_PAYMENT,
            total_cents=total_cents,
            created_at=datetime.now(timezone.utc).isoformat(),
            lines=lines,
            user_sub=user_sub,
        )

    def to_metadata_item(self) -> dict:
        item = {
            "PK": f"ORDER#{self.id}",
            "SK": "METADATA",
            "id": self.id,
            "status": self.status,
            "total_cents": self.total_cents,
            "created_at": self.created_at,
            # Always populated: lets the admin Orders & Logistics screen list
            # every order (guest and customer alike) via a single-partition
            # bucket -- the same trade-off already accepted for products'
            # GSI1PK="CATEGORY#DESK_LAMPS".
            "GSI2PK": "ORDER",
            "GSI2SK": f"{self.created_at}#{self.id}",
        }
        if self.user_sub:
            # Sparse on purpose: guest orders have no user_sub, so they never
            # populate GSI1 here, keeping "this customer's orders" queries
            # free of guest noise.
            item["user_sub"] = self.user_sub
            item["GSI1PK"] = f"USER#{self.user_sub}"
            item["GSI1SK"] = f"ORDER#{self.created_at}#{self.id}"
        return item
