import os

AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")
TABLE_NAME = os.environ.get("TABLE_NAME", "WebshopTable")
GSI1_NAME = os.environ.get("GSI1_NAME", "GSI1")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "webshop-event-bus")
CATEGORY_DESK_LAMPS = "DESK_LAMPS"

# Must match the queue names provisioned in terraform/main.tf.
PAYMENT_QUEUE_NAME = "payment-service-queue"
INVENTORY_QUEUE_NAME = "inventory-service-queue"
NOTIFICATION_QUEUE_NAME = "notification-service-queue"

CART_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7
MAX_ITEM_QUANTITY = 10
MIN_ITEM_QUANTITY = 1
