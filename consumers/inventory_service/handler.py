import json
import logging

from app.repositories.single_table import set_order_status_field
from consumers.common import process_sqs_event

logger = logging.getLogger(__name__)


def handle_order_placed(detail: dict) -> None:
    order_id = detail["order_id"]
    item_count = detail["item_count"]
    logger.info(
        json.dumps({"event": "inventory_reserved_simulated", "order_id": order_id, "item_count": item_count})
    )
    set_order_status_field(order_id, "inventory_status", "RESERVED")


def handler(event, _context=None):
    return process_sqs_event(event, handle_order_placed)
