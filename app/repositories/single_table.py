from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from app.aws_clients import dynamodb_resource
from app.config import CATEGORY_DESK_LAMPS, GSI1_NAME, GSI2_NAME, TABLE_NAME
from app.models.cart import CartItem
from app.models.order import Order, OrderLine
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.models.return_request import ReturnRequest
from app.models.user import UserProfile


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


def list_variants(product_id: str) -> list[ProductVariant]:
    table = get_table()
    response = table.query(
        KeyConditionExpression=Key("PK").eq(f"PRODUCT#{product_id}") & Key("SK").begins_with("VARIANT#")
    )
    return [ProductVariant.from_item(item) for item in response.get("Items", [])]


def put_variant_stock(product_id: str, color: str, stock_qty: int) -> None:
    table = get_table()
    table.put_item(Item=ProductVariant(product_id=product_id, color=color, stock_qty=stock_qty).to_item())


def get_variant_stock(product_id: str, color: str) -> int:
    """0 for a color with no VARIANT# row yet, same default list_variants() uses."""
    table = get_table()
    response = table.get_item(Key={"PK": f"PRODUCT#{product_id}", "SK": f"VARIANT#{color}"})
    item = response.get("Item")
    return int(item["stock_qty"]) if item else 0


def decrement_variant_stock(product_id: str, color: str, quantity: int) -> bool:
    """Atomically decrements one variant's stock -- the ConditionExpression
    guards against it ever going negative (e.g. a race between two admins
    shipping orders for the same low-stock color). Returns False (not an
    exception) if there wasn't enough stock at the moment of the write; the
    caller is expected to have already checked availability for every line
    via get_variant_stock() before shipping any of them, so this should only
    ever trip on a genuine race, not on the common "no stock" case."""
    table = get_table()
    try:
        table.update_item(
            Key={"PK": f"PRODUCT#{product_id}", "SK": f"VARIANT#{color}"},
            UpdateExpression="SET stock_qty = stock_qty - :quantity",
            ConditionExpression="attribute_exists(SK) AND stock_qty >= :quantity",
            ExpressionAttributeValues={":quantity": quantity},
        )
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return False


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


def set_cart_item_quantity(cart_id: str, product_id: str, quantity: int) -> None:
    """Overwrites (not ADD, unlike add_cart_item) the quantity for a cart line
    the shopper already has -- used by the quantity dropdown on the cart page.
    ConditionExpression guards against update_item's default upsert behaviour
    silently creating a malformed item (missing title/image_url/etc.) if the
    line was already removed, e.g. by a concurrent request in another tab."""
    table = get_table()
    try:
        table.update_item(
            Key={"PK": f"CART#{cart_id}", "SK": f"ITEM#{product_id}"},
            UpdateExpression="SET quantity = :quantity",
            ConditionExpression="attribute_exists(SK)",
            ExpressionAttributeValues={":quantity": quantity},
        )
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def remove_cart_item(cart_id: str, product_id: str) -> None:
    table = get_table()
    table.delete_item(Key={"PK": f"CART#{cart_id}", "SK": f"ITEM#{product_id}"})


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


def set_order_status(order_id: str, new_status: str, allowed_from: set[str]) -> bool:
    """Atomically transitions `status` only if it's currently one of
    allowed_from -- a ConditionExpression guard against races (e.g. a
    concurrent cancel attempt and an admin/consumer status update). Returns
    False (not an exception) when the current status wasn't in allowed_from,
    so callers can show "no longer possible" instead of treating it as a
    server error."""
    table = get_table()
    try:
        table.update_item(
            Key={"PK": f"ORDER#{order_id}", "SK": "METADATA"},
            UpdateExpression="SET #status = :new",
            ConditionExpression=Attr("status").is_in(list(allowed_from)),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":new": new_status},
        )
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def get_order(order_id: str) -> Order | None:
    table = get_table()
    response = table.query(KeyConditionExpression=Key("PK").eq(f"ORDER#{order_id}"))
    items = response.get("Items", [])
    if not items:
        return None

    metadata = next(item for item in items if item["SK"] == "METADATA")
    # Not `!= "METADATA"`: a RETURN sibling item under the same PK (added in a
    # later step) would otherwise be mis-parsed as an OrderLine and raise KeyError.
    lines = [OrderLine.from_item(item) for item in items if item["SK"].startswith("ITEM#")]
    return Order(
        id=metadata["id"],
        status=metadata["status"],
        total_cents=int(metadata["total_cents"]),
        created_at=metadata["created_at"],
        lines=lines,
        user_sub=metadata.get("user_sub"),
    )


def list_orders_for_customer(user_sub: str) -> list[Order]:
    table = get_table()
    response = table.query(
        IndexName=GSI1_NAME,
        KeyConditionExpression=Key("GSI1PK").eq(f"USER#{user_sub}"),
        ScanIndexForward=False,
    )
    return [
        Order(
            id=item["id"],
            status=item["status"],
            total_cents=int(item["total_cents"]),
            created_at=item["created_at"],
            user_sub=item.get("user_sub"),
        )
        for item in response.get("Items", [])
    ]


def list_all_orders() -> list[Order]:
    """For the admin Orders & Logistics screen -- every order, newest first,
    guest and customer alike."""
    table = get_table()
    response = table.query(
        IndexName=GSI2_NAME,
        KeyConditionExpression=Key("GSI2PK").eq("ORDER"),
        ScanIndexForward=False,
    )
    return [
        Order(
            id=item["id"],
            status=item["status"],
            total_cents=int(item["total_cents"]),
            created_at=item["created_at"],
            user_sub=item.get("user_sub"),
        )
        for item in response.get("Items", [])
    ]


def list_all_returns() -> list[ReturnRequest]:
    """For the admin returns queue -- every reported return, newest first."""
    table = get_table()
    response = table.query(
        IndexName=GSI2_NAME,
        KeyConditionExpression=Key("GSI2PK").eq("RETURN"),
        ScanIndexForward=False,
    )
    return [ReturnRequest.from_item(item) for item in response.get("Items", [])]


def create_session(
    session_id: str,
    cognito_sub: str,
    email: str,
    groups: list[str],
    cart_id: str,
    csrf_token: str,
    expires_at: int,
) -> None:
    table = get_table()
    table.put_item(
        Item={
            "PK": f"SESSION#{session_id}",
            "SK": "METADATA",
            "cognito_sub": cognito_sub,
            "email": email,
            "groups": groups,
            "cart_id": cart_id,
            "csrf_token": csrf_token,
            "expires_at": expires_at,
        }
    )


def get_session(session_id: str) -> dict | None:
    table = get_table()
    response = table.get_item(Key={"PK": f"SESSION#{session_id}", "SK": "METADATA"})
    return response.get("Item")


def delete_session(session_id: str) -> None:
    table = get_table()
    table.delete_item(Key={"PK": f"SESSION#{session_id}", "SK": "METADATA"})


def get_user_profile(sub: str) -> UserProfile | None:
    table = get_table()
    response = table.get_item(Key={"PK": f"USER#{sub}", "SK": "PROFILE"})
    item = response.get("Item")
    return UserProfile.from_item(item) if item else None


def put_user_profile(profile: UserProfile) -> None:
    table = get_table()
    table.put_item(Item=profile.to_item())


def create_return_request(return_request: ReturnRequest) -> bool:
    """ConditionExpression enforces "one return per order" at the key level --
    also makes a double form-submit idempotent rather than creating two
    records. Returns False (not an exception) if one already exists."""
    table = get_table()
    try:
        table.put_item(
            Item=return_request.to_item(),
            ConditionExpression="attribute_not_exists(SK)",
        )
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def get_return_request(order_id: str) -> ReturnRequest | None:
    table = get_table()
    response = table.get_item(Key={"PK": f"ORDER#{order_id}", "SK": "RETURN"})
    item = response.get("Item")
    return ReturnRequest.from_item(item) if item else None
