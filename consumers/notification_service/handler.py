import json
import logging

from app.repositories.single_table import set_order_status_field
from consumers.common import process_sqs_event

logger = logging.getLogger(__name__)


def handle_order_placed(detail: dict) -> None:
    order_id = detail["order_id"]
    logger.info(json.dumps({"event": "confirmation_mail_simulated", "order_id": order_id}))
    set_order_status_field(order_id, "notification_status", "SENT")


def handler(event, _context=None):
    return process_sqs_event(event, handle_order_placed)
