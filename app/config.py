import os

AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")
TABLE_NAME = os.environ.get("TABLE_NAME", "WebshopTable")
GSI1_NAME = os.environ.get("GSI1_NAME", "GSI1")
GSI2_NAME = os.environ.get("GSI2_NAME", "GSI2")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "webshop-event-bus")
CATEGORY_DESK_LAMPS = "DESK_LAMPS"

# Deliberately NOT read here as frozen constants: moto generates a pool
# id/client id/secret at runtime (unlike TABLE_NAME etc., which are known
# string literals set before any app.* import happens), so app/auth/cognito.py
# reads these three fresh from os.environ on every call instead -- the same
# pattern app/aws_clients.py already uses for *_ENDPOINT_URL.

ADMIN_GROUP_NAME = "Admins"
# Fixed-length sessions, no silent refresh-token renewal (see README/plan): a
# deliberate simplification that keeps no reusable Cognito credential in
# DynamoDB at all.
SESSION_TTL_SECONDS = 8 * 60 * 60
RETURN_WINDOW_DAYS = 14

# Must match the queue names provisioned in terraform/main.tf.
PAYMENT_QUEUE_NAME = "payment-service-queue"
INVENTORY_QUEUE_NAME = "inventory-service-queue"
NOTIFICATION_QUEUE_NAME = "notification-service-queue"

CART_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
MAX_ITEM_QUANTITY = 10
MIN_ITEM_QUANTITY = 1
