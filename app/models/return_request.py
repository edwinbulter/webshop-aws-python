from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ReturnRequest:
    order_id: str
    reason: str
    reported_at: str

    @property
    def reported_at_display(self) -> str:
        return datetime.fromisoformat(self.reported_at).strftime("%d-%m-%Y %H:%M")

    def to_item(self) -> dict:
        return {
            "PK": f"ORDER#{self.order_id}",
            "SK": "RETURN",
            "reason": self.reason,
            "reported_at": self.reported_at,
            # Admin returns queue: a single-partition bucket, same trade-off
            # already accepted for GSI1PK="CATEGORY#DESK_LAMPS" and
            # GSI2PK="ORDER".
            "GSI2PK": "RETURN",
            "GSI2SK": f"{self.reported_at}#{self.order_id}",
        }

    @staticmethod
    def from_item(item: dict) -> "ReturnRequest":
        return ReturnRequest(
            order_id=item["PK"].removeprefix("ORDER#"),
            reason=item["reason"],
            reported_at=item["reported_at"],
        )

    @staticmethod
    def new(order_id: str, reason: str) -> "ReturnRequest":
        return ReturnRequest(
            order_id=order_id, reason=reason, reported_at=datetime.now(timezone.utc).isoformat()
        )
