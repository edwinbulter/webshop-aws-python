import json

import boto3

from app.events.publisher import build_order_placed_detail, publish_order_placed
from app.models.order import Order, OrderLine


def _sample_order() -> Order:
    lines = [OrderLine(product_id="p1", title="Test lamp", color="Zwart", quantity=2, price_cents=1999)]
    return Order.new(order_id="order-1", lines=lines)


def test_build_order_placed_detail_includes_routing_fields():
    detail = build_order_placed_detail(_sample_order())
    assert detail["schema_version"] == 1
    assert detail["order_id"] == "order-1"
    assert detail["total_cents"] == 3998
    assert detail["item_count"] == 2
    assert detail["notify"] is True


def test_publish_order_placed_sends_expected_entry(eventbridge_bus_and_queues, aws_endpoints):
    order = _sample_order()
    assert publish_order_placed(order) is True

    sqs_client = boto3.client("sqs", region_name="eu-west-1", endpoint_url=aws_endpoints)
    queue_url = eventbridge_bus_and_queues["payment-service-queue"]
    response = sqs_client.receive_message(QueueUrl=queue_url, WaitTimeSeconds=2, MaxNumberOfMessages=5)
    matching = [
        m for m in response.get("Messages", []) if json.loads(m["Body"])["detail"]["order_id"] == "order-1"
    ]
    assert matching, "OrderPlaced event was not routed to payment-service-queue"

    envelope = json.loads(matching[0]["Body"])
    assert envelope["source"] == "webshop.orders"
    assert envelope["detail-type"] == "OrderPlaced"
    assert envelope.get("detail", {}).get("schema_version") == 1
