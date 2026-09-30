"""Creates the DynamoDB table + GSI and the EventBridge bus/queues/rules
against whatever DYNAMODB_ENDPOINT_URL/EVENTS_ENDPOINT_URL/SQS_ENDPOINT_URL
point at -- for local development (moto) only. Mirrors terraform/main.tf's
resource shapes closely enough for local testing, but is not a substitute
for it and must never be pointed at a real AWS account: real infra is owned
by Terraform (see README's "Deployment naar AWS"), which configures things
this script doesn't replicate (e.g. DLQ redrive policies). To seed products
into an already-provisioned environment (local or real), use
scripts/seed_products.py instead."""

import json

from botocore.exceptions import ClientError

from app.aws_clients import dynamodb_resource, events_client, sqs_client
from app.config import (
    EVENT_BUS_NAME,
    GSI1_NAME,
    INVENTORY_QUEUE_NAME,
    NOTIFICATION_QUEUE_NAME,
    PAYMENT_QUEUE_NAME,
    TABLE_NAME,
)


def ensure_table_exists() -> None:
    client = dynamodb_resource().meta.client
    try:
        client.create_table(
            TableName=TABLE_NAME,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": GSI1_NAME,
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        client.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceInUseException":
            raise


def _create_queue_and_rule(events, sqs, queue_name: str, rule_name: str, event_pattern: dict) -> None:
    queue_url = sqs.create_queue(QueueName=queue_name)["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])["Attributes"][
        "QueueArn"
    ]
    events.put_rule(
        Name=rule_name,
        EventBusName=EVENT_BUS_NAME,
        EventPattern=json.dumps(event_pattern),
        State="ENABLED",
    )
    events.put_targets(
        Rule=rule_name,
        EventBusName=EVENT_BUS_NAME,
        Targets=[{"Id": f"{rule_name}-target", "Arn": queue_arn}],
    )


def ensure_event_infrastructure_exists() -> None:
    """Creates the EventBridge bus + 3 SQS queues + fan-out rules locally, mirroring
    terraform/main.tf, so a manually-run `flask run` can complete checkout's OrderPlaced
    publish instead of only logging a caught ResourceNotFoundException (see A10)."""
    events = events_client()
    sqs = sqs_client()

    try:
        events.create_event_bus(Name=EVENT_BUS_NAME)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise

    base_pattern = {"source": ["webshop.orders"], "detail-type": ["OrderPlaced"]}
    notification_pattern = {**base_pattern, "detail": {"notify": [True]}}

    _create_queue_and_rule(events, sqs, PAYMENT_QUEUE_NAME, "payment-rule", base_pattern)
    _create_queue_and_rule(events, sqs, INVENTORY_QUEUE_NAME, "inventory-rule", base_pattern)
    _create_queue_and_rule(events, sqs, NOTIFICATION_QUEUE_NAME, "notification-rule", notification_pattern)


def main() -> None:
    ensure_table_exists()
    ensure_event_infrastructure_exists()
    print(f"Created table '{TABLE_NAME}', event bus '{EVENT_BUS_NAME}', and its 3 fan-out queues.")


if __name__ == "__main__":
    main()
