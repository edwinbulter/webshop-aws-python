import json
import logging

from app.aws_clients import events_client
from app.config import EVENT_BUS_NAME
from app.models.order import Order

logger = logging.getLogger(__name__)

EVENT_SOURCE = "webshop.orders"
EVENT_DETAIL_TYPE = "OrderPlaced"
SCHEMA_VERSION = 1


def build_order_placed_detail(order: Order) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "order_id": order.id,
        "total_cents": order.total_cents,
        "item_count": sum(line.quantity for line in order.lines),
        "notify": True,
    }


def publish_order_placed(order: Order) -> bool:
    detail = build_order_placed_detail(order)
    try:
        response = events_client().put_events(
            Entries=[
                {
                    "Source": EVENT_SOURCE,
                    "DetailType": EVENT_DETAIL_TYPE,
                    "EventBusName": EVENT_BUS_NAME,
                    "Detail": json.dumps(detail),
                }
            ]
        )
    except Exception:
        logger.exception("Failed to publish OrderPlaced event for order %s", order.id)
        return False

    if response.get("FailedEntryCount", 0) > 0:
        logger.error("OrderPlaced event rejected for order %s: %s", order.id, response.get("Entries"))
        return False

    return True
