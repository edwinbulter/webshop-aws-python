from flask import Blueprint, render_template, request

from app.repositories import single_table

bp = Blueprint("catalog", __name__)

VALID_SORTS = ("price_asc", "price_desc")


def _sort_and_color() -> tuple[str, str | None]:
    sort = request.args.get("sort", "price_asc")
    if sort not in VALID_SORTS:
        sort = "price_asc"
    color = request.args.get("color") or None
    return sort, color


@bp.get("/")
def index():
    sort, color = _sort_and_color()
    products = single_table.list_products(sort=sort, color=color)
    all_products = single_table.list_products(sort="price_asc")
    all_colors = sorted({c for product in all_products for c in product.colors})
    return render_template(
        "index.html",
        products=products,
        sort=sort,
        color=color,
        all_colors=all_colors,
    )


@bp.get("/products")
def products_fragment():
    sort, color = _sort_and_color()
    products = single_table.list_products(sort=sort, color=color)
    return render_template("_products_grid.html", products=products)
