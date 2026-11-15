import hashlib
import hmac
import json
import secrets
import pytest
from app import create_app
from test_store import store
from store_config import validate
import extensions


def test_settings_and_permissions(store):
    app, c, post, p, checkout, payment = store
    assert (
        post(
            "settings",
            {
                "businessName": "Independent Shop",
                "theme": {
                    "primary": "#123456",
                    "secondary": "#ffffff",
                    "accent": "#789abc",
                },
            },
        ).status_code
        == 200
    )
    assert c.get("/api/store").json["businessName"] == "Independent Shop"
    assert "#123456" in c.get("/store-theme.css").text
    assert post("settings", {"storeId": "other"}).status_code == 400
    assert post("settings", {"PAYSTACK_SECRET_KEY": "private"}).status_code == 400
    assert post("settings", {"theme": {"primary": "red;url(evil)"}}).status_code == 400
    post("logout", {})
    assert post("settings", {"businessName": "Intruder"}).status_code == 401
    assert c.get("/api/enquiries").status_code == 401


def test_archive_delete_and_category_cycle(store):
    app, c, post, p, checkout, payment = store
    assert (
        post(
            "products", dict(p, featured=True, specifications={"Storage": "256 GB"})
        ).status_code
        == 200
    )
    assert c.get("/api/products").json[0]["specifications"] == {"Storage": "256 GB"}
    assert (
        post("category-tree", {"name": "Phones", "parent": "Bags"}).status_code == 200
    )
    assert (
        post("category-tree", {"name": "Bags", "parent": "Phones"}).status_code == 400
    )
    assert (
        post("products/" + p["id"] + "/lifecycle", {"action": "archive"}).status_code
        == 200
    )
    assert c.get("/api/products").json == []
    assert checkout().status_code == 409
    assert (
        post("products/" + p["id"] + "/lifecycle", {"action": "restore"}).status_code
        == 200
    )
    assert post("products", p).status_code == 200
    checkout()
    assert (
        post("products/" + p["id"] + "/lifecycle", {"action": "delete"}).status_code
        == 400
    )
    other = dict(p, id="unused")
    assert post("products", other).status_code == 200
    assert post("products/unused/lifecycle", {"action": "delete"}).status_code == 200


def test_enquiries_and_rate_limiting(store):
    app, c, post, p, checkout, payment = store
    assert (
        post("enquiries", {"name": "A", "email": "bad", "message": "Hi"}).status_code
        == 400
    )
    assert (
        post(
            "enquiries",
            {
                "name": "Customer",
                "email": "person@example.test",
                "message": "Is this available?",
            },
        ).status_code
        == 200
    )
    enquiry = c.get("/api/enquiries").json[0]
    assert post("enquiries/" + enquiry["id"], {"status": "Resolved"}).status_code == 200
    assert c.get("/api/enquiries").json[0]["status"] == "Resolved"
    for _ in range(19):
        post(
            "enquiries",
            {
                "name": "Customer",
                "email": "person@example.test",
                "message": "Another question",
            },
        )
    assert post("enquiries", {}).status_code == 429


def test_unverified_transfer_does_not_mark_paid(store):
    app, c, post, p, checkout, payment = store
    assert (
        post(
            "settings",
            {
                "features": {
                    "whatsappCheckout": True,
                    "bankTransfer": True,
                    "onlinePayment": False,
                    "instalments": False,
                    "delivery": True,
                    "pickup": True,
                }
            },
        ).status_code
        == 200
    )
    key = secrets.token_hex(16)
    order = checkout(key).json
    assert (
        post(
            "transfer",
            {
                "reference": order["reference"],
                "key": "wrong",
                "transferReference": "sent",
            },
        ).status_code
        == 400
    )
    assert (
        post(
            "transfer",
            {
                "reference": order["reference"],
                "key": key,
                "transferReference": "bank-123",
            },
        ).status_code
        == 200
    )
    assert c.get("/api/orders").json[0]["status"] == "Awaiting payment"
    assert c.get("/api/transfer-claims").json[0]["reference"] == "bank-123"


def test_gateway_verification_idempotency_and_webhook(store, monkeypatch):
    app, c, post, p, checkout, payment = store
    app.config["PAYSTACK_SECRET_KEY"] = "test-secret"
    flags = dict(c.get("/api/store").json["features"], onlinePayment=True)
    post("settings", {"features": flags})
    key = secrets.token_hex(16)
    order = checkout(key).json
    verification = {"status": "success", "currency": "NGN", "amount": p["price"]}
    reference = None

    def transport(secret, path, body=None):
        nonlocal reference
        if body:
            reference = body["reference"]
            return {"authorization_url": "https://checkout.paystack.com/test"}
        return dict(verification, reference=reference)

    monkeypatch.setattr(extensions, "paystack", transport)
    assert (
        post(
            "gateway/initialize",
            {
                "key": key,
                "reference": order["reference"],
                "email": "customer@example.test",
            },
        ).status_code
        == 200
    )
    verification["amount"] = 1
    assert post("gateway/verify", {"reference": reference}).status_code == 400
    assert c.get("/api/orders").json[0]["status"] == "Awaiting payment"
    verification["amount"] = p["price"]
    verification["currency"] = "USD"
    assert post("gateway/verify", {"reference": reference}).status_code == 400
    verification["currency"] = "NGN"
    assert post("gateway/verify", {"reference": reference}).status_code == 200
    assert post("gateway/verify", {"reference": reference}).status_code == 200
    recorded = c.get("/api/orders").json[0]
    assert recorded["status"] == "Paid" and len(recorded["payments"]) == 1
    assert c.get("/api/products").json[0]["variants"][0]["stock"] == 49
    raw = json.dumps(
        {"event": "charge.success", "data": {"reference": reference}}
    ).encode()
    assert (
        c.post(
            "/api/gateway/webhook", data=raw, content_type="application/json"
        ).status_code
        == 403
    )
    signature = hmac.new(b"test-secret", raw, hashlib.sha512).hexdigest()
    assert (
        c.post(
            "/api/gateway/webhook",
            data=raw,
            content_type="application/json",
            headers={"x-paystack-signature": signature},
        ).status_code
        == 200
    )
    assert len(c.get("/api/orders").json[0]["payments"]) == 1


def test_independent_client_isolation(tmp_path):
    apps = [
        create_app(
            {
                "TESTING": True,
                "DATA_DIR": str(tmp_path / name),
                "STORE": {"storeId": name, "businessName": name},
            }
        )
        for name in ["client-a", "client-b"]
    ]
    a, b = [app.test_client() for app in apps]
    assert (
        apps[0].config["SESSION_COOKIE_NAME"] != apps[1].config["SESSION_COOKIE_NAME"]
    )
    a.get("/api/session")
    cookie = a.get_cookie(apps[0].config["SESSION_COOKIE_NAME"])
    b.set_cookie(apps[1].config["SESSION_COOKIE_NAME"], cookie.value)
    assert b.get("/api/session").json["owner"] is None
    with apps[0].app_context():
        apps[0].db().execute(
            "INSERT INTO enquiries VALUES(?,?,?,?,?,?)",
            ("a", "A", "a@example.test", "Private", "New", "now"),
        )
        apps[0].db().commit()
    with apps[1].app_context():
        assert apps[1].db().execute("SELECT COUNT(*) FROM enquiries").fetchone()[0] == 0
    assert a.get("/api/store").json["businessName"] == "client-a"
    assert b.get("/api/store").json["businessName"] == "client-b"
    assert b.get("/api/products").json == []


def test_config_and_malformed_input(store):
    app, c, post, p, checkout, payment = store
    for payload in [
        {"whatsapp": "not-a-number"},
        {"theme": {"primary": "javascript:bad"}},
        {"features": {"onlinePayment": "true"}},
        {"secret": "no"},
        {"logo": "https://untrusted.example/logo"},
    ]:
        with pytest.raises(ValueError):
            validate(payload)
    assert post("login", {"username": [], "password": "bad"}).status_code == 400
    assert post("products", dict(p, published="false")).status_code == 400
    assert c.post("/api/products", json=p).status_code == 403
