import json
import logging
from typing import Callable

logger = logging.getLogger(__name__)


def process_sqs_event(event: dict, process_detail: Callable[[dict], None]) -> dict:
    batch_item_failures = []
    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            envelope = json.loads(record["body"])
            process_detail(envelope["detail"])
        except Exception:
            logger.exception("Failed to process SQS record %s", message_id)
            batch_item_failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": batch_item_failures}
