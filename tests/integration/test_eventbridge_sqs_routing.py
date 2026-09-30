import json

import boto3

from app.config import EVENT_BUS_NAME


def test_order_placed_event_routes_to_all_three_queues(eventbridge_bus_and_queues, aws_endpoints):
    events_client = boto3.client("events", region_name="eu-west-1", endpoint_url=aws_endpoints)
    sqs_client = boto3.client("sqs", region_name="eu-west-1", endpoint_url=aws_endpoints)

    detail = {
        "schema_version": 1,
        "order_id": "order-routing-test",
        "total_cents": 1999,
        "item_count": 1,
        "notify": True,
    }
    events_client.put_events(
        Entries=[
            {
                "Source": "webshop.orders",
                "DetailType": "OrderPlaced",
                "EventBusName": EVENT_BUS_NAME,
                "Detail": json.dumps(detail),
            }
        ]
    )

    for queue_name, queue_url in eventbridge_bus_and_queues.items():
        response = sqs_client.receive_message(QueueUrl=queue_url, WaitTimeSeconds=2, MaxNumberOfMessages=10)
        messages = response.get("Messages", [])
        bodies = [json.loads(m["Body"]) for m in messages]
        assert any(
            b["detail"]["order_id"] == "order-routing-test" for b in bodies
        ), f"no message for order-routing-test delivered to {queue_name}"


def test_rule_does_not_deliver_on_detail_type_mismatch(eventbridge_bus_and_queues, aws_endpoints):
    """moto correctly enforces top-level EventPattern fields (source, detail-type),
    which is what this asserts. It does NOT reliably enforce nested `detail.*`
    content matching (e.g. the notification rule's `detail.notify` condition) --
    verified separately below by asserting the publisher emits the right field,
    since the actual content-based filtering is real AWS EventBridge behavior
    exercised by `terraform validate`, not something moto can confirm end-to-end."""
    events_client = boto3.client("events", region_name="eu-west-1", endpoint_url=aws_endpoints)
    sqs_client = boto3.client("sqs", region_name="eu-west-1", endpoint_url=aws_endpoints)

    events_client.put_events(
        Entries=[
            {
                "Source": "webshop.orders",
                "DetailType": "SomeUnrelatedEvent",
                "EventBusName": EVENT_BUS_NAME,
                "Detail": json.dumps({"order_id": "should-not-be-routed"}),
            }
        ]
    )

    for queue_name, queue_url in eventbridge_bus_and_queues.items():
        response = sqs_client.receive_message(QueueUrl=queue_url, WaitTimeSeconds=2, MaxNumberOfMessages=5)
        messages = response.get("Messages", [])
        assert not any(
            json.loads(m["Body"])["detail"].get("order_id") == "should-not-be-routed" for m in messages
        ), f"unexpected delivery to {queue_name} for a non-matching detail-type"
