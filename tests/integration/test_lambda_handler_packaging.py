from app.main import handler


def _apigw_v2_event(method: str, path: str) -> dict:
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"host": "example.com"},
        "requestContext": {
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "pytest",
            },
            "domainName": "example.com",
            "stage": "$default",
            "requestId": "test-request-id",
            "routeKey": "$default",
            "time": "01/Jan/2026:00:00:00 +0000",
            "timeEpoch": 0,
        },
        "isBase64Encoded": False,
    }


def test_mangum_handler_serves_index_via_apigw_v2_event(dynamodb_table):
    event = _apigw_v2_event("GET", "/")
    response = handler(event, None)

    assert response["statusCode"] == 200
    assert "text/html" in response["headers"]["content-type"]
    assert "Bureaulampen" in response["body"]


def test_mangum_handler_returns_404_for_unknown_route(dynamodb_table):
    event = _apigw_v2_event("GET", "/does-not-exist")
    response = handler(event, None)

    assert response["statusCode"] == 404
