from app.aws_clients import sqs_client
from app.config import PAYMENT_QUEUE_NAME
from app.events.publisher import publish_order_placed
from app.models.order import Order, OrderLine, OrderStatus
from app.repositories import single_table
from consumers.payment_service.handler import handler as payment_handler
from scripts.run_local_consumers import _poll_queue_once


def test_poll_queue_once_advances_order_through_the_async_pipeline(
    dynamodb_table, eventbridge_bus_and_queues
):
    order = Order.new(
        order_id="local-consumer-order",
        lines=[OrderLine(product_id="p", title="t", color="Zwart", quantity=1, price_cents=1999)],
    )
    single_table.create_order(order)
    assert single_table.get_order(order.id).status == OrderStatus.AWAITING_PAYMENT

    publish_order_placed(order)

    processed = _poll_queue_once(sqs_client(), PAYMENT_QUEUE_NAME, payment_handler)

    assert processed == 1
    assert single_table.get_order(order.id).status == OrderStatus.IN_PROGRESS


def test_poll_queue_once_is_a_noop_when_the_queue_is_empty(dynamodb_table, eventbridge_bus_and_queues):
    processed = _poll_queue_once(sqs_client(), PAYMENT_QUEUE_NAME, payment_handler)
    assert processed == 0
