import json
import logging

from app.models.order import OrderStatus
from app.repositories.single_table import set_order_status, set_order_status_field
from consumers.common import process_sqs_event

logger = logging.getLogger(__name__)


def handle_order_placed(detail: dict) -> None:
    order_id = detail["order_id"]
    total_cents = detail["total_cents"]
    logger.info(json.dumps({"event": "payment_simulated", "order_id": order_id, "total_cents": total_cents}))
    set_order_status_field(order_id, "payment_status", "PAID")
    # The ConditionExpression guard means this is a no-op (not an error) if the
    # customer already cancelled the order before this async event was processed.
    set_order_status(order_id, OrderStatus.IN_PROGRESS, allowed_from={OrderStatus.AWAITING_PAYMENT})


def handler(event, _context=None):
    return process_sqs_event(event, handle_order_placed)
