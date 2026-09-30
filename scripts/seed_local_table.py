"""Loads app/seed/products.json into the DynamoDB table pointed at by
DYNAMODB_ENDPOINT_URL / TABLE_NAME. Used for local development and as part of
the pytest fixtures; never run against a real AWS account for this PoC."""

import json
from pathlib import Path

from botocore.exceptions import ClientError

from app.aws_clients import dynamodb_resource
from app.config import GSI1_NAME, TABLE_NAME
from app.models.product import Product
from app.repositories.single_table import put_products

SEED_FILE = Path(__file__).resolve().parent.parent / "app" / "seed" / "products.json"


def load_products() -> list[Product]:
    raw = json.loads(SEED_FILE.read_text())
    return [Product.from_item(item) for item in raw]


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


def main() -> None:
    ensure_table_exists()
    products = load_products()
    put_products(products)
    print(f"Seeded {len(products)} products into the table.")


if __name__ == "__main__":
    main()
