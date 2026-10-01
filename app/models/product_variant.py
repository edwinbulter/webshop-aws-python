from dataclasses import dataclass


@dataclass(frozen=True)
class ProductVariant:
    product_id: str
    color: str
    stock_qty: int

    def to_item(self) -> dict:
        return {
            "PK": f"PRODUCT#{self.product_id}",
            "SK": f"VARIANT#{self.color}",
            "stock_qty": self.stock_qty,
        }

    @staticmethod
    def from_item(item: dict) -> "ProductVariant":
        return ProductVariant(
            product_id=item["PK"].removeprefix("PRODUCT#"),
            color=item["SK"].removeprefix("VARIANT#"),
            stock_qty=int(item["stock_qty"]),
        )
