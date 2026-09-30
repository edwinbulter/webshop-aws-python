import json

from app.models.order import Order, OrderLine
from app.repositories import single_table
from consumers.inventory_service.handler import handler as inventory_handler
from consumers.notification_service.handler import handler as notification_handler
from consumers.payment_service.handler import handler as payment_handler


def _sqs_event(order_id: str, message_id: str = "msg-1", malformed: bool = False) -> dict:
    if malformed:
        body = "not-json"
    else:
        envelope = {
            "version": "0",
            "id": "evt-1",
            "detail-type": "OrderPlaced",
            "source": "webshop.orders",
            "detail": {
                "schema_version": 1,
                "order_id": order_id,
                "total_cents": 1999,
                "item_count": 1,
                "notify": True,
            },
        }
        body = json.dumps(envelope)
    return {"Records": [{"messageId": message_id, "body": body}]}


def _create_order(order_id: str) -> None:
    order = Order.new(
        order_id=order_id,
        lines=[OrderLine(product_id="p", title="t", color="Zwart", quantity=1, price_cents=1999)],
    )
    single_table.create_order(order)


def _order_item(order_id: str) -> dict:
    table = single_table.get_table()
    return table.get_item(Key={"PK": f"ORDER#{order_id}", "SK": "METADATA"})["Item"]


def test_payment_handler_marks_order_paid(dynamodb_table):
    _create_order("order-payment")
    result = payment_handler(_sqs_event("order-payment"))
    assert result == {"batchItemFailures": []}
    assert _order_item("order-payment")["payment_status"] == "PAID"


def test_inventory_handler_marks_order_reserved(dynamodb_table):
    _create_order("order-inventory")
    result = inventory_handler(_sqs_event("order-inventory"))
    assert result == {"batchItemFailures": []}
    assert _order_item("order-inventory")["inventory_status"] == "RESERVED"


def test_notification_handler_marks_order_notified(dynamodb_table):
    _create_order("order-notify")
    result = notification_handler(_sqs_event("order-notify"))
    assert result == {"batchItemFailures": []}
    assert _order_item("order-notify")["notification_status"] == "SENT"


def test_malformed_message_is_reported_as_batch_item_failure(dynamodb_table):
    result = payment_handler(_sqs_event("order-x", message_id="bad-msg", malformed=True))
    assert result == {"batchItemFailures": [{"itemIdentifier": "bad-msg"}]}


def test_one_bad_message_does_not_block_the_rest_of_the_batch(dynamodb_table):
    _create_order("order-good")
    good_record = _sqs_event("order-good")["Records"][0]
    bad_record = _sqs_event("order-bad", message_id="bad-msg", malformed=True)["Records"][0]

    result = payment_handler({"Records": [bad_record, good_record]})

    assert result == {"batchItemFailures": [{"itemIdentifier": "bad-msg"}]}
    assert _order_item("order-good")["payment_status"] == "PAID"
