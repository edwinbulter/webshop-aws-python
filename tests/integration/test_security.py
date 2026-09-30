from app.repositories import single_table


def _boom(*_args, **_kwargs):
    raise RuntimeError("internal secret stack detail that must never leak")


def test_unhandled_exception_returns_generic_full_page_without_leaking_details(
    client, dynamodb_table, monkeypatch
):
    monkeypatch.setattr(single_table, "list_products", _boom)

    response = client.get("/")
    assert response.status_code == 500
    body = response.get_data(as_text=True)
    assert "internal secret stack detail" not in body
    assert "Traceback" not in body
    assert "onverwachte fout" in body


def test_unhandled_exception_returns_generic_fragment_for_htmx_requests(client, dynamodb_table, monkeypatch):
    monkeypatch.setattr(single_table, "list_products", _boom)

    response = client.get("/products", headers={"HX-Request": "true"})
    assert response.status_code == 500
    body = response.get_data(as_text=True)
    assert "internal secret stack detail" not in body
    assert "Traceback" not in body
    assert 'data-testid="error-fragment"' in body


def test_security_headers_are_present(client, dynamodb_table):
    response = client.get("/")
    assert "Content-Security-Policy" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
