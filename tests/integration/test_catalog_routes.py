import json
import re
from pathlib import Path

SEED_FILE = Path(__file__).resolve().parent.parent.parent / "app" / "seed" / "products.json"
PRODUCTS_BY_ID = {p["id"]: p for p in json.loads(SEED_FILE.read_text())}


def _product_order(html: str) -> list[str]:
    return re.findall(r'data-product-id="([^"]+)"', html)


def test_index_returns_all_products_sorted_by_price_ascending(client, dynamodb_table):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    order = _product_order(html)
    assert len(order) == len(PRODUCTS_BY_ID)

    prices = [PRODUCTS_BY_ID[pid]["price_cents"] for pid in order]
    assert prices == sorted(prices)


def test_products_fragment_sorts_descending(client, dynamodb_table):
    response = client.get("/products?sort=price_desc")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    order = _product_order(html)
    prices = [PRODUCTS_BY_ID[pid]["price_cents"] for pid in order]
    assert prices == sorted(prices, reverse=True)


def test_products_fragment_filters_by_color(client, dynamodb_table):
    response = client.get("/products?color=Turkoois")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    order = _product_order(html)
    assert order, "expected at least one product with color Turkoois"
    for pid in order:
        assert "Turkoois" in PRODUCTS_BY_ID[pid]["colors"]


def test_product_images_are_hotlinked_to_ikea(client, dynamodb_table):
    response = client.get("/")
    html = response.get_data(as_text=True)
    assert "https://www.ikea.com/nl/nl/images/products/" in html
