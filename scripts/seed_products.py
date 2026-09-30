"""Loads app/seed/products.json into whichever table TABLE_NAME points at --
local (moto, if DYNAMODB_ENDPOINT_URL is set) or real AWS (if it isn't).
Never touches infrastructure: the table itself must already exist (see
scripts/bootstrap_local_infra.py for local dev, or Terraform for a real
environment -- README's "Deployment naar AWS"). Safe to re-run: products
are keyed by their own id, so this overwrites the same items rather than
duplicating them."""

import json
from pathlib import Path

from app.models.product import Product
from app.repositories.single_table import put_products

SEED_FILE = Path(__file__).resolve().parent.parent / "app" / "seed" / "products.json"


def load_products() -> list[Product]:
    raw = json.loads(SEED_FILE.read_text())
    return [Product.from_item(item) for item in raw]


def main() -> None:
    products = load_products()
    put_products(products)
    print(f"Seeded {len(products)} products into the table.")


if __name__ == "__main__":
    main()
