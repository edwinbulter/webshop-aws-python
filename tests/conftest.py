import json
import os
import socket

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_REGION", "eu-west-1")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("TABLE_NAME", "WebshopTableTest")
os.environ.setdefault("GSI1_NAME", "GSI1")
os.environ.setdefault("EVENT_BUS_NAME", "webshop-event-bus-test")
os.environ.setdefault("FLASK_DEBUG", "1")

import boto3  # noqa: E402
import pytest  # noqa: E402
from moto.server import ThreadedMotoServer  # noqa: E402

from app.config import (  # noqa: E402
    EVENT_BUS_NAME,
    INVENTORY_QUEUE_NAME as INVENTORY_QUEUE,
    NOTIFICATION_QUEUE_NAME as NOTIFICATION_QUEUE,
    PAYMENT_QUEUE_NAME as PAYMENT_QUEUE,
    TABLE_NAME,
)
from app.repositories.single_table import put_products  # noqa: E402
from scripts.bootstrap_local_infra import ensure_table_exists  # noqa: E402
from scripts.seed_products import load_products  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def moto_server_url():
    port = _free_port()
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port)
    server.start()
    url = f"http://127.0.0.1:{port}"
    yield url
    server.stop()


@pytest.fixture(scope="session", autouse=True)
def aws_endpoints(moto_server_url):
    os.environ["DYNAMODB_ENDPOINT_URL"] = moto_server_url
    os.environ["EVENTS_ENDPOINT_URL"] = moto_server_url
    os.environ["SQS_ENDPOINT_URL"] = moto_server_url
    return moto_server_url


@pytest.fixture(scope="session")
def dynamodb_table(aws_endpoints):
    ensure_table_exists()
    put_products(load_products())
    return TABLE_NAME


def _create_queue_and_rule(
    events_client, sqs_client, queue_name: str, rule_name: str, event_pattern: dict
) -> str:
    queue_url = sqs_client.create_queue(QueueName=queue_name)["QueueUrl"]
    queue_arn = sqs_client.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])[
        "Attributes"
    ]["QueueArn"]

    events_client.put_rule(
        Name=rule_name,
        EventBusName=EVENT_BUS_NAME,
        EventPattern=json.dumps(event_pattern),
        State="ENABLED",
    )
    events_client.put_targets(
        Rule=rule_name,
        EventBusName=EVENT_BUS_NAME,
        Targets=[{"Id": f"{rule_name}-target", "Arn": queue_arn}],
    )
    return queue_url


@pytest.fixture(scope="session")
def eventbridge_bus_and_queues(aws_endpoints):
    events_client = boto3.client("events", region_name="eu-west-1", endpoint_url=aws_endpoints)
    sqs_client = boto3.client("sqs", region_name="eu-west-1", endpoint_url=aws_endpoints)

    events_client.create_event_bus(Name=EVENT_BUS_NAME)

    base_pattern = {"source": ["webshop.orders"], "detail-type": ["OrderPlaced"]}
    notification_pattern = {**base_pattern, "detail": {"notify": [True]}}

    queue_urls = {
        PAYMENT_QUEUE: _create_queue_and_rule(
            events_client, sqs_client, PAYMENT_QUEUE, "payment-rule", base_pattern
        ),
        INVENTORY_QUEUE: _create_queue_and_rule(
            events_client, sqs_client, INVENTORY_QUEUE, "inventory-rule", base_pattern
        ),
        NOTIFICATION_QUEUE: _create_queue_and_rule(
            events_client, sqs_client, NOTIFICATION_QUEUE, "notification-rule", notification_pattern
        ),
    }
    return queue_urls


@pytest.fixture()
def app(dynamodb_table, eventbridge_bus_and_queues):
    from app.main import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()
