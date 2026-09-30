from boto3.dynamodb.conditions import Attr, Key

from app.aws_clients import dynamodb_resource
from app.config import CATEGORY_DESK_LAMPS, GSI1_NAME, TABLE_NAME
from app.models.cart import CartItem
from app.models.order import Order, OrderLine
from app.models.product import Product


def get_table():
    return dynamodb_resource().Table(TABLE_NAME)


def list_products(sort: str = "price_asc", color: str | None = None) -> list[Product]:
    table = get_table()
    query_kwargs = {
        "IndexName": GSI1_NAME,
        "KeyConditionExpression": Key("GSI1PK").eq(f"CATEGORY#{CATEGORY_DESK_LAMPS}"),
        "ScanIndexForward": sort != "price_desc",
    }
    if color:
        query_kwargs["FilterExpression"] = Attr("colors").contains(color)

    items: list[dict] = []
    last_evaluated_key = None
    while True:
        if last_evaluated_key:
            query_kwargs["ExclusiveStartKey"] = last_evaluated_key
        response = table.query(**query_kwargs)
        items.extend(response.get("Items", []))
        last_evaluated_key = response.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

    return [Product.from_item(item) for item in items]


def put_products(products: list[Product]) -> None:
    table = get_table()
    with table.batch_writer() as batch:
        for product in products:
            batch.put_item(Item=product.to_item())


def get_product(product_id: str) -> Product | None:
    table = get_table()
    response = table.get_item(Key={"PK": f"PRODUCT#{product_id}", "SK": "METADATA"})
    item = response.get("Item")
    return Product.from_item(item) if item else None


def get_cart_items(cart_id: str) -> list[CartItem]:
    table = get_table()
    response = table.query(KeyConditionExpression=Key("PK").eq(f"CART#{cart_id}"))
    return [CartItem.from_item(item) for item in response.get("Items", [])]


def add_cart_item(cart_id: str, product: Product, color: str, quantity: int) -> None:
    table = get_table()
    table.update_item(
        Key={"PK": f"CART#{cart_id}", "SK": f"ITEM#{product.id}"},
        UpdateExpression=(
            "SET cart_id = :cart_id, product_id = :product_id, title = :title, "
            "image_url = :image_url, price_cents = :price_cents, #color = :color "
            "ADD quantity :quantity"
        ),
        ExpressionAttributeNames={"#color": "color"},
        ExpressionAttributeValues={
            ":cart_id": cart_id,
            ":product_id": product.id,
            ":title": product.title,
            ":image_url": product.image_url,
            ":price_cents": product.price_cents,
            ":color": color,
            ":quantity": quantity,
        },
    )


def clear_cart(cart_id: str) -> None:
    table = get_table()
    items = get_cart_items(cart_id)
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"PK": f"CART#{cart_id}", "SK": f"ITEM#{item.product_id}"})


def create_order(order: Order) -> None:
    table = get_table()
    with table.batch_writer() as batch:
        batch.put_item(Item=order.to_metadata_item())
        for line in order.lines:
            batch.put_item(Item=line.to_item(order.id))


def set_order_status_field(order_id: str, field_name: str, value: str) -> None:
    table = get_table()
    table.update_item(
        Key={"PK": f"ORDER#{order_id}", "SK": "METADATA"},
        UpdateExpression="SET #f = :v",
        ExpressionAttributeNames={"#f": field_name},
        ExpressionAttributeValues={":v": value},
    )


def get_order(order_id: str) -> Order | None:
    table = get_table()
    response = table.query(KeyConditionExpression=Key("PK").eq(f"ORDER#{order_id}"))
    items = response.get("Items", [])
    if not items:
        return None

    metadata = next(item for item in items if item["SK"] == "METADATA")
    lines = [OrderLine.from_item(item) for item in items if item["SK"] != "METADATA"]
    return Order(
        id=metadata["id"],
        status=metadata["status"],
        total_cents=int(metadata["total_cents"]),
        created_at=metadata["created_at"],
        lines=lines,
    )
