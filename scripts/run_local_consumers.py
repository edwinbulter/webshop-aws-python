"""Polls the 3 local (moto) SQS queues and invokes each consumer Lambda's own
`handler(event, context)` locally -- for local development only.

On real AWS, each queue's `aws_lambda_event_source_mapping` (see
terraform/modules/lambda) does this automatically: SQS delivers batches of
messages straight to the consumer Lambda, no polling code needed anywhere in
this repo. Locally there is no such trigger, so without this script an order
placed via a manually-run `flask run` sits in AWAITING_PAYMENT forever --
nothing ever processes the OrderPlaced message sitting in payment-service-queue
to advance it to IN_PROGRESS (see README's "Orderstatus-levenscyclus").

Usage: uv run python -m scripts.run_local_consumers        # polls forever
       uv run python -m scripts.run_local_consumers --once  # one pass, then exit
"""

import sys
import time

from app.aws_clients import sqs_client
from app.config import INVENTORY_QUEUE_NAME, NOTIFICATION_QUEUE_NAME, PAYMENT_QUEUE_NAME
from consumers.inventory_service.handler import handler as inventory_handler
from consumers.notification_service.handler import handler as notification_handler
from consumers.payment_service.handler import handler as payment_handler

_QUEUES = [
    (PAYMENT_QUEUE_NAME, payment_handler),
    (INVENTORY_QUEUE_NAME, inventory_handler),
    (NOTIFICATION_QUEUE_NAME, notification_handler),
]


def _poll_queue_once(sqs, queue_name: str, handler) -> int:
    queue_url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
    response = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=1)
    messages = response.get("Messages", [])
    if not messages:
        return 0

    # Same event shape consumers/common.py::process_sqs_event already expects
    # (and the same shape a real SQS event-source-mapping would deliver).
    event = {"Records": [{"messageId": m["MessageId"], "body": m["Body"]} for m in messages]}
    result = handler(event)
    failed_ids = {failure["itemIdentifier"] for failure in result.get("batchItemFailures", [])}

    processed = 0
    for message in messages:
        if message["MessageId"] in failed_ids:
            continue
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
        processed += 1
    return processed


def main() -> None:
    run_once = "--once" in sys.argv
    sqs = sqs_client()

    if not run_once:
        print("Polling local queues for OrderPlaced messages (Ctrl-C to stop)...")

    while True:
        total_processed = 0
        for queue_name, handler in _QUEUES:
            total_processed += _poll_queue_once(sqs, queue_name, handler)

        if run_once:
            print(f"Processed {total_processed} message(s).")
            break
        time.sleep(1)


if __name__ == "__main__":
    main()
