import os

import boto3

from app.config import AWS_REGION


def _endpoint_url(env_var: str) -> str | None:
    return os.environ.get(env_var) or None


def dynamodb_resource():
    return boto3.resource(
        "dynamodb",
        region_name=AWS_REGION,
        endpoint_url=_endpoint_url("DYNAMODB_ENDPOINT_URL"),
    )


def events_client():
    return boto3.client(
        "events",
        region_name=AWS_REGION,
        endpoint_url=_endpoint_url("EVENTS_ENDPOINT_URL"),
    )


def sqs_client():
    return boto3.client(
        "sqs",
        region_name=AWS_REGION,
        endpoint_url=_endpoint_url("SQS_ENDPOINT_URL"),
    )


def cognito_idp_client():
    return boto3.client(
        "cognito-idp",
        region_name=AWS_REGION,
        endpoint_url=_endpoint_url("COGNITO_IDP_ENDPOINT_URL"),
    )
