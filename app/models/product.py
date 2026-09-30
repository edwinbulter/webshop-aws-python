from __future__ import annotations

from dataclasses import dataclass, field

from app.config import CATEGORY_DESK_LAMPS


@dataclass(frozen=True)
class Product:
    id: str
    title: str
    price_cents: int
    image_url: str
    colors: list[str] = field(default_factory=list)
    rating_value: float = 0.0
    rating_count: int = 0

    @property
    def price_display(self) -> str:
        return f"€ {self.price_cents / 100:.2f}"

    def to_item(self) -> dict:
        return {
            "PK": f"PRODUCT#{self.id}",
            "SK": "METADATA",
            "GSI1PK": f"CATEGORY#{CATEGORY_DESK_LAMPS}",
            "GSI1SK": f"PRICE#{self.price_cents:08d}",
            "id": self.id,
            "title": self.title,
            "price_cents": self.price_cents,
            "image_url": self.image_url,
            "colors": self.colors,
            "rating_value": str(self.rating_value),
            "rating_count": self.rating_count,
        }

    @staticmethod
    def from_item(item: dict) -> "Product":
        return Product(
            id=item["id"],
            title=item["title"],
            price_cents=int(item["price_cents"]),
            image_url=item["image_url"],
            colors=list(item.get("colors", [])),
            rating_value=float(item.get("rating_value", 0)),
            rating_count=int(item.get("rating_count", 0)),
        )
