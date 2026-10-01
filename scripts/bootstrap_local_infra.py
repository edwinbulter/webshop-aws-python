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
import sys

from botocore.exceptions import ClientError

from app.aws_clients import cognito_idp_client, dynamodb_resource, events_client, sqs_client
from app.config import (
    ADMIN_GROUP_NAME,
    EVENT_BUS_NAME,
    GSI1_NAME,
    GSI2_NAME,
    INVENTORY_QUEUE_NAME,
    NOTIFICATION_QUEUE_NAME,
    PAYMENT_QUEUE_NAME,
    TABLE_NAME,
)
from app.models.user import Address, UserProfile
from app.repositories import single_table

_LOCAL_POOL_NAME = "webshop-local-pool"
_LOCAL_CLIENT_NAME = "webshop-local-client"

# Same two accounts as the live deployment (see README's "Demo-inloggegevens"), so
# logging in locally works out-of-the-box instead of only against the real,
# deployed Cognito pool.
_DEMO_ADMIN_EMAIL = "admin@demo.nl"
_DEMO_CUSTOMER_EMAIL = "klant@demo.nl"
_DEMO_PASSWORD = "Demo1234!"

# Fictional profile for klant@demo.nl, filled in on every demo account across
# every environment -- a demo visitor shouldn't land on an empty profile form.
# Factuuradres is deliberately identical to Afleveradres (same object, not a
# separate copy) rather than left empty.
_DEMO_CUSTOMER_GIVEN_NAME = "Klaas"
_DEMO_CUSTOMER_FAMILY_NAME = "Jansen"
_DEMO_CUSTOMER_ADDRESS = Address(
    name="Klaas Jansen",
    street="Dorpsstraat 12",
    postal_code="1234 AB",
    city="Amsterdam",
    country="Nederland",
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
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
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
                },
                {
                    "IndexName": GSI2_NAME,
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        )
        client.get_waiter("table_exists").wait(TableName=TABLE_NAME)
        client.update_time_to_live(
            TableName=TABLE_NAME,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"},
        )
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


def ensure_cognito_pool_exists() -> dict:
    """Creates a local Cognito User Pool + confidential app client + Admins
    group against moto, mirroring terraform/modules/cognito -- without this,
    a manually-run `flask run` fails on the first /login or /register with a
    missing COGNITO_CLIENT_ID. Idempotent within the lifetime of one
    moto-server process: reuses an existing pool/client by name rather than
    creating duplicates on every re-run of this script."""
    client = cognito_idp_client()

    pool_id = next(
        (
            pool["Id"]
            for pool in client.list_user_pools(MaxResults=60)["UserPools"]
            if pool["Name"] == _LOCAL_POOL_NAME
        ),
        None,
    )
    if pool_id is None:
        pool_id = client.create_user_pool(
            PoolName=_LOCAL_POOL_NAME,
            UsernameAttributes=["email"],
            AutoVerifiedAttributes=["email"],
            MfaConfiguration="OFF",
            Policies={
                "PasswordPolicy": {
                    "MinimumLength": 8,
                    "RequireUppercase": True,
                    "RequireLowercase": True,
                    "RequireNumbers": True,
                    "RequireSymbols": False,
                }
            },
        )["UserPool"]["Id"]

    app_client = next(
        (
            c
            for c in client.list_user_pool_clients(UserPoolId=pool_id, MaxResults=60)["UserPoolClients"]
            if c["ClientName"] == _LOCAL_CLIENT_NAME
        ),
        None,
    )
    if app_client is None:
        app_client = client.create_user_pool_client(
            UserPoolId=pool_id,
            ClientName=_LOCAL_CLIENT_NAME,
            GenerateSecret=True,
            ExplicitAuthFlows=["ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
        )["UserPoolClient"]
        client_id, client_secret = app_client["ClientId"], app_client["ClientSecret"]
    else:
        client_id = app_client["ClientId"]
        client_secret = client.describe_user_pool_client(UserPoolId=pool_id, ClientId=client_id)[
            "UserPoolClient"
        ]["ClientSecret"]

    try:
        client.create_group(UserPoolId=pool_id, GroupName=ADMIN_GROUP_NAME)
    except ClientError as error:
        if error.response["Error"]["Code"] != "GroupExistsException":
            raise

    return {"pool_id": pool_id, "client_id": client_id, "client_secret": client_secret}


def _ensure_demo_user(client, pool_id: str, email: str, group_name: str | None) -> str:
    """Creates the user if missing (idempotent); returns their sub either way,
    so callers can key a DynamoDB profile item to it."""
    try:
        response = client.admin_create_user(
            UserPoolId=pool_id,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
            ],
            MessageAction="SUPPRESS",
        )
        client.admin_set_user_password(
            UserPoolId=pool_id, Username=email, Password=_DEMO_PASSWORD, Permanent=True
        )
        attributes = {a["Name"]: a["Value"] for a in response["User"]["Attributes"]}
    except ClientError as error:
        if error.response["Error"]["Code"] != "UsernameExistsException":
            raise
        existing = client.admin_get_user(UserPoolId=pool_id, Username=email)
        attributes = {a["Name"]: a["Value"] for a in existing["UserAttributes"]}

    if group_name:
        client.admin_add_user_to_group(UserPoolId=pool_id, Username=email, GroupName=group_name)

    return attributes["sub"]


def _ensure_demo_customer_profile(sub: str) -> None:
    single_table.put_user_profile(
        UserProfile(
            sub=sub,
            email=_DEMO_CUSTOMER_EMAIL,
            given_name=_DEMO_CUSTOMER_GIVEN_NAME,
            family_name=_DEMO_CUSTOMER_FAMILY_NAME,
            shipping_address=_DEMO_CUSTOMER_ADDRESS,
            billing_address=_DEMO_CUSTOMER_ADDRESS,
        )
    )


def ensure_demo_users_exist(pool_id: str) -> None:
    client = cognito_idp_client()
    _ensure_demo_user(client, pool_id, _DEMO_ADMIN_EMAIL, group_name=ADMIN_GROUP_NAME)
    customer_sub = _ensure_demo_user(client, pool_id, _DEMO_CUSTOMER_EMAIL, group_name=None)
    _ensure_demo_customer_profile(customer_sub)


def main() -> None:
    ensure_table_exists()
    ensure_event_infrastructure_exists()
    cognito = ensure_cognito_pool_exists()
    ensure_demo_users_exist(cognito["pool_id"])

    # Status messages go to stderr, and *only* the `export` lines to stdout --
    # on purpose, so this script can be run as `eval "$(... bootstrap_local_infra)"`
    # (see README's "Lokaal draaien"). That actually sets the variables in the
    # calling shell; a plain `uv run python -m ...` cannot, since a child
    # process can never modify its parent shell's environment, no matter what
    # it prints -- a human has to copy-paste the printed lines themselves,
    # which is exactly the step that's easy to forget.
    print(
        f"Created table '{TABLE_NAME}', event bus '{EVENT_BUS_NAME}', its 3 fan-out queues, "
        "and a local Cognito pool.",
        file=sys.stderr,
    )
    print(f'export COGNITO_USER_POOL_ID="{cognito["pool_id"]}"')
    print(f'export COGNITO_CLIENT_ID="{cognito["client_id"]}"')
    print(f'export COGNITO_CLIENT_SECRET="{cognito["client_secret"]}"')


if __name__ == "__main__":
    main()
