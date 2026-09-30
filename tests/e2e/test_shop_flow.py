import json
from pathlib import Path

from playwright.sync_api import Page, expect

SEED_FILE = Path(__file__).resolve().parent.parent.parent / "app" / "seed" / "products.json"
SEED_PRODUCTS = json.loads(SEED_FILE.read_text())
TOTAL_PRODUCTS = len(SEED_PRODUCTS)
TURQUOISE_COUNT = sum(1 for p in SEED_PRODUCTS if "Turkoois" in p["colors"])


def test_full_shop_flow_browse_filter_cart_checkout(page: Page, live_server_url: str):
    page.goto(live_server_url)
    expect(page.get_by_role("heading", name="Bureaulampen")).to_be_visible()

    all_cards = page.locator('[data-testid="product-card"]')
    expect(all_cards).to_have_count(TOTAL_PRODUCTS)

    page.locator("#color").select_option("Turkoois")
    turquoise_cards = page.locator('[data-testid="product-card"]')
    expect(turquoise_cards).to_have_count(TURQUOISE_COUNT)

    first_card = turquoise_cards.first
    first_card.locator("button[type=submit]").click()

    expect(page.locator("#cart-count")).to_have_text("1")
    expect(first_card.get_by_test_id("add-to-cart-status")).to_contain_text("Toegevoegd")

    page.get_by_role("link", name="Winkelwagen", exact=False).click()
    expect(page.get_by_test_id("cart-items")).to_be_visible()
    expect(page.get_by_test_id("cart-item")).to_have_count(1)

    page.get_by_test_id("checkout-button").click()

    confirmation = page.get_by_test_id("order-confirmation")
    expect(confirmation).to_be_visible()
    order_id = page.get_by_test_id("order-id").inner_text()
    assert order_id.strip() != ""
    expect(page.locator("#cart-count")).to_have_text("0")


def test_sort_by_price_reorders_the_grid(page: Page, live_server_url: str):
    page.goto(live_server_url)
    expect(page.locator('[data-testid="product-card"]')).to_have_count(TOTAL_PRODUCTS)

    first_asc_id = page.locator('[data-testid="product-card"]').first.get_attribute("data-product-id")

    page.locator("#sort").select_option("price_desc")
    expect(page.locator('[data-testid="product-card"]').first).not_to_have_attribute(
        "data-product-id", first_asc_id
    )
    expect(page.locator('[data-testid="product-card"]')).to_have_count(TOTAL_PRODUCTS)


def test_new_session_cart_page_shows_empty_state(page: Page, live_server_url: str):
    page.goto(f"{live_server_url}/cart")
    expect(page.get_by_test_id("cart-empty")).to_be_visible()
