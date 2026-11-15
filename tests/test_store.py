import io, json, uuid
import pytest
from PIL import Image
from werkzeug.security import generate_password_hash
from app import create_app


@pytest.fixture(params=["sqlite", "postgres"])
def store(tmp_path, request):
    url = request.getfixturevalue("postgres_url") if request.param == "postgres" else ""
    app = create_app(
        {
            "TESTING": True,
            "DATA_DIR": str(tmp_path),
            "PREVIEW": True,
            "STORE": {
                "whatsapp": "2348000000000",
                "categories": ["Bags"],
                "features": {"instalments": True},
            },
            "DATABASE_URL": url,
        }
    )
    with app.app_context():
        app.db().execute(
            "INSERT INTO owner VALUES(1,?,?)",
            ("owner", generate_password_hash("test-only-password")),
        )
        app.db().commit()
    client = app.test_client()
    csrf = client.get("/api/session").json["csrf"]

    def post(url, body):
        return client.post(
            "/api/" + url,
            json=body,
            headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]},
        )

    assert (
        post(
            "login", {"username": "owner", "password": "test-only-password"}
        ).status_code
        == 200
    )
    product = {
        "name": "Verification Bag",
        "category": "Bags",
        "price": 1200000,
        "description": "Test sample",
        "images": ["/static/demo-object.svg"],
        "variants": [
            {"id": "brown38", "size": "38", "colour": "Brown", "stock": 50},
            {"id": "black38", "size": "38", "colour": "Black", "stock": 0},
        ],
        "published": True,
    }
    product["id"] = post("products", product).json["id"]

    def checkout(key=None, variant="brown38", price=1200000):
        return post(
            "checkout",
            {
                "key": key or str(uuid.uuid4()),
                "items": [
                    {
                        "product_id": product["id"],
                        "variant_id": variant,
                        "qty": 1,
                        "price": price,
                    }
                ],
                "fulfilment": "Pickup",
            },
        )

    def payment(ref, amount=400000, delivery=0, **kw):
        return post(
            "orders/" + ref + "/payments",
            {
                "key": str(uuid.uuid4()),
                "products": amount,
                "delivery": delivery,
                "received": "2026-11-13",
                "note": "Verified transfer; exception if needed",
                **kw,
            },
        )

    return app, client, post, product, checkout, payment


def test_three_instalments_and_dashboard(store):
    app, c, post, p, checkout, payment = store
    handoff = checkout().json
    ref = handoff["reference"]
    assert "https://wa.me/2348000000000?text=" in handoff["url"]
    assert ref in handoff["message"]
    assert "12,000" in handoff["message"]
    assert "Pickup" in handoff["message"]
    for expected in [800000, 400000, 0]:
        assert payment(ref).json["balance"] == expected
    o = c.get("/api/orders").json[0]
    assert o["status"] == "Paid"
    assert len(o["payments"]) == 3
    d = c.get("/api/dashboard").json
    assert (
        d["paid_orders"],
        d["product_sales"],
        d["items_sold"],
        d["bestseller"]["units"],
    ) == (1, 1200000, 1, 1)
    assert d["open_payments"] == 0


def test_full_payment_and_reopening_correction(store):
    app, c, post, p, checkout, payment = store
    ref = checkout().json["reference"]
    o = payment(ref, 1200000).json
    completed = o["completed"]
    pid = o["payments"][0]["id"]
    assert o["status"] == "Paid"
    o = payment(
        ref, 800000, corrects=pid, reason="Original amount transcribed incorrectly"
    ).json
    assert (
        o["status"] == "Part-paid" and o["balance"] == 400000 and o["completed"] is None
    )
    assert len(o["payments"]) == 2 and o["payments"][0]["products"] == 1200000
    assert c.get("/api/dashboard").json["product_sales"] == 0
    assert c.get("/api/products").json[0]["variants"][0]["stock"] == 50
    assert payment(ref).json["status"] == "Paid"


def test_underpaid_third_equal_intentional_and_duplicate_payment(store):
    app, c, post, p, checkout, payment = store
    ref = checkout().json["reference"]
    key = str(uuid.uuid4())
    first = payment(ref, 300000, key=key).json
    duplicate = payment(ref, 300000, key=key).json
    assert len(duplicate["payments"]) == 1 and duplicate["paid_products"] == 300000
    payment(ref, 300000)
    o = payment(ref, 300000).json
    assert (
        len(o["payments"]) == 3
        and o["balance"] == 300000
        and o["follow_up"]
        and o["status"] == "Part-paid"
    )
    assert payment(ref, 300000, note="").status_code == 400
    assert (
        payment(ref, 300000, note="Fourth verified transfer, outside agreement").json[
            "status"
        ]
        == "Paid"
    )


def test_checkout_double_tap_and_changed_key_payload(store):
    app, c, post, p, checkout, payment = store
    key = str(uuid.uuid4())
    a = checkout(key).json
    b = checkout(key).json
    assert a["reference"] == b["reference"]
    assert len(c.get("/api/orders").json) == 1
    assert checkout(key, price=100).status_code == 409


def test_delivery_rider_and_combined_transfer(store):
    app, c, post, p, checkout, payment = store
    ref = checkout().json["reference"]
    assert (
        post(
            f"orders/{ref}/agreement", {"delivery_fee": 250000, "rider_direct": True}
        ).status_code
        == 200
    )
    o = payment(ref, 1200000).json
    assert o["paid_delivery"] == 0 and o["delivery_balance"] == 0
    ref2 = checkout().json["reference"]
    post(f"orders/{ref2}/agreement", {"delivery_fee": 250000, "rider_direct": False})
    o = payment(ref2, 1200000, 250000).json
    assert (
        o["paid_delivery"] == 250000
        and o["paid_products"] == 1200000
        and o["delivery_balance"] == 0
    )
    assert c.get("/api/dashboard").json["product_sales"] == 2400000


def test_abandoned_and_paid_history_closing_review(store):
    app, c, post, p, checkout, payment = store
    ref = checkout().json["reference"]
    assert post(f"orders/{ref}/dismiss", {}).status_code == 200
    ref = checkout().json["reference"]
    payment(ref)
    assert post(f"orders/{ref}/dismiss", {}).status_code == 409
    assert (
        post(
            f"orders/{ref}/dismiss",
            {
                "review": ref,
                "reason": "Customer cancelled; transfer remains recorded for refund follow-up",
            },
        ).status_code
        == 200
    )
    o = c.get("/api/orders").json[0]
    assert o["status"] == "Dismissed" and len(o["payments"]) == 1
    assert payment(ref).status_code == 400


def test_sold_out_reserved_and_release_exact_combination(store):
    app, c, post, p, checkout, payment = store
    assert checkout(variant="black38").status_code == 409
    ref = checkout().json["reference"]
    assert (
        post(
            f"orders/{ref}/reserve",
            {"product_id": p["id"], "variant_id": "brown38", "qty": 1},
        ).status_code
        == 200
    )
    assert c.get("/api/products").json[0]["variants"][0]["available"] == 49
    assert c.get("/api/products").json[0]["variants"][1]["available"] == 0
    assert (
        post(
            f"orders/{ref}/reserve",
            {"product_id": p["id"], "variant_id": "brown38", "qty": 0},
        ).status_code
        == 200
    )
    assert c.get("/api/products").json[0]["variants"][0]["available"] == 50
    with app.app_context():
        variants = [
            {"id": "brown38", "size": "38", "colour": "Brown", "stock": 1},
            {"id": "black38", "size": "38", "colour": "Black", "stock": 0},
        ]
        app.db().execute("UPDATE products SET variants=?", (json.dumps(variants),))
        app.db().commit()
    post(
        f"orders/{ref}/reserve",
        {"product_id": p["id"], "variant_id": "brown38", "qty": 1},
    )
    assert checkout().status_code == 409
    post(
        f"orders/{ref}/reserve",
        {"product_id": p["id"], "variant_id": "brown38", "qty": 0},
    )
    assert checkout().status_code == 200


def test_prices_publishing_and_validation(store):
    app, c, post, p, checkout, payment = store
    assert checkout(price=1).status_code == 409
    p["published"] = False
    assert post("products", p).status_code == 200
    assert c.get("/api/products").json == []
    assert checkout().status_code == 409
    p["price"] = 1.5
    assert post("products", p).status_code == 400
    assert post("orders/not-real/payments", {}).status_code == 400


def test_signed_out_authorization_and_csrf(store):
    app, c, post, p, checkout, payment = store
    post("logout", {})
    for url in ["orders", "dashboard"]:
        assert c.get("/api/" + url).status_code == 401
    for url, body in [
        ("products", p),
        ("categories", {"name": "Test"}),
        ("orders/guess/payments", {}),
        ("orders/guess/reserve", {}),
        ("orders/guess/agreement", {}),
        ("orders/guess/dismiss", {}),
    ]:
        assert post(url, body).status_code == 401
    assert c.post("/api/products", json=p).status_code == 403
    assert c.get("/api/products?admin=1").status_code == 200
    assert (
        c.post(
            "/api/upload", headers={"X-CSRF-Token": c.get("/api/session").json["csrf"]}
        ).status_code
        == 401
    )


def test_image_upload_persistence_and_production_samples(store):
    app, c, post, p, checkout, payment = store
    im = Image.new("RGB", (2000, 1000), "pink")
    buff = io.BytesIO()
    im.save(buff, "JPEG")
    buff.seek(0)
    response = c.post(
        "/api/upload",
        data={"photo": (buff, "phone.jpg")},
        headers={"X-CSRF-Token": c.get("/api/session").json["csrf"]},
    )
    assert response.status_code == 200
    image = c.get(response.json["url"])
    assert image.status_code == 200
    assert Image.open(io.BytesIO(image.data)).width == 1600
    other = create_app(
        {
            "TESTING": True,
            "DATA_DIR": app.config["DATA_DIR"],
            "PREVIEW": False,
            "DATABASE_URL": app.config["DATABASE_URL"],
        }
    )
    assert other.test_client().get("/api/products").json[0]["price"] == 1200000
    with app.app_context():
        app.db().execute("UPDATE products SET sample=1")
        app.db().commit()
    assert other.test_client().get("/api/products").json == []


def test_overdue_excess_and_date_filters(store):
    app, c, post, p, checkout, payment = store
    ref = checkout().json["reference"]
    post(
        f"orders/{ref}/agreement",
        {"due": "2026-01-01", "note": "Agreed timeline", "delivery_fee": 0},
    )
    o = payment(ref, 100000).json
    assert o["overdue"]
    assert payment(ref, 1300000, note="").status_code == 400
    o = payment(ref, 1300000).json
    assert o["excess"] == 200000 and o["status"] == "Paid"
    assert c.get("/api/dashboard?start=2099-01-01").json["paid_orders"] == 0
    assert c.get("/api/dashboard?end=2000-01-01").json["paid_orders"] == 0


def test_simultaneous_checkout_and_payment_retries(store):
    from concurrent.futures import ThreadPoolExecutor

    app, c, post, p, checkout, payment = store
    checkout_key = str(uuid.uuid4())
    payload = {
        "key": checkout_key,
        "items": [
            {"product_id": p["id"], "variant_id": "brown38", "qty": 1, "price": 1200000}
        ],
        "fulfilment": "Pickup",
    }

    def submit(url, body):
        client = app.test_client()
        csrf = client.get("/api/session").json["csrf"]
        assert (
            client.post(
                "/api/login",
                json={"username": "owner", "password": "test-only-password"},
                headers={"X-CSRF-Token": csrf},
            ).status_code
            == 200
        )
        csrf = client.get("/api/session").json["csrf"]
        response = client.post("/api/" + url, json=body, headers={"X-CSRF-Token": csrf})
        assert response.status_code == 200, response.get_data(as_text=True)
        return response.json

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: submit("checkout", payload), range(2)))
    assert results[0]["reference"] == results[1]["reference"]
    ref = results[0]["reference"]
    key = str(uuid.uuid4())
    transfer = {
        "key": key,
        "products": 1200000,
        "delivery": 0,
        "received": "2026-11-13",
        "note": "Verified full transfer",
    }
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(lambda _: submit(f"orders/{ref}/payments", transfer), range(2))
        )
    assert len(results[0]["payments"]) == len(results[1]["payments"]) == 1
    assert c.get("/api/dashboard").json["product_sales"] == 1200000


def test_option_edits_require_shopper_review_and_old_reservation_is_clear(store):
    app, c, post, p, checkout, payment = store
    ref = checkout().json["reference"]
    p["variants"][0]["size"] = "40"
    p["variants"][0]["colour"] = "Green"
    assert post("products", p).status_code == 200
    current = c.get("/api/products").json[0]
    assert current["variants"][0]["id"] != "brown38"
    assert checkout().status_code == 409
    response = post(
        f"orders/{ref}/reserve",
        {"product_id": p["id"], "variant_id": "brown38", "qty": 1},
    )
    assert (
        response.status_code == 409 and "original size/colour" in response.json["error"]
    )
    assert (
        post(
            f"orders/{ref}/reserve",
            {"product_id": p["id"], "variant_id": "brown38", "qty": 0},
        ).status_code
        == 200
    )


def test_delivery_excess_requires_note_and_stays_visible(store):
    app, c, post, p, checkout, payment = store
    ref = checkout().json["reference"]
    post(f"orders/{ref}/agreement", {"delivery_fee": 250000})
    assert payment(ref, 1200000, 350000, note="").status_code == 400
    response = payment(
        ref,
        1200000,
        350000,
        note="Verified extra delivery receipt; review with customer",
    )
    assert response.status_code == 200
    assert response.json["delivery_excess"] == 100000
    assert response.json["paid_delivery"] == 350000
    assert c.get("/api/dashboard").json["product_sales"] == 1200000


def test_correcting_a_paid_entry_needs_reason_without_spurious_exception(store):
    app, c, post, p, checkout, payment = store
    ref = checkout().json["reference"]
    original = payment(ref, 1200000, note="").json["payments"][0]["id"]
    response = payment(
        ref,
        800000,
        corrects=original,
        reason="Correct amount from bank statement",
        note="",
    )
    assert response.status_code == 200
    assert response.json["balance"] == 400000
    assert response.json["payment_count"] == 1


def test_retry_key_cannot_silently_change_received_amount(store):
    app, c, post, p, checkout, payment = store
    ref = checkout().json["reference"]
    key = str(uuid.uuid4())
    assert payment(ref, 400000, key=key).status_code == 200
    assert payment(ref, 800000, key=key).status_code == 409
    assert c.get("/api/orders").json[0]["paid_products"] == 400000


def test_actual_receipts_retained_but_stock_conflicts_are_flagged(store):
    app, c, post, p, checkout, payment = store
    p["variants"][0]["stock"] = 1
    assert post("products", p).status_code == 200
    a = checkout().json["reference"]
    b = checkout().json["reference"]
    post(
        f"orders/{a}/reserve",
        {"product_id": p["id"], "variant_id": "brown38", "qty": 1},
    )
    received = payment(b, 1200000).json
    assert received["status"] == "Paid" and received["inventory_conflicts"]
    assert payment(a, 1200000).json["inventory_conflicts"]
    assert all(o["inventory_conflicts"] for o in c.get("/api/orders").json)


def test_invitation_roles_and_revocation(store):
    app, c, post, product, checkout, payment = store
    guest = app.test_client()

    def send(client, endpoint, body):
        return client.post(
            "/api/" + endpoint,
            json=body,
            headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]},
        )

    assert send(guest, "staff", {"username": "intruder"}).status_code == 401
    assert (
        send(
            guest,
            "staff/activate",
            {"token": "invented", "password": "long-test-password"},
        ).status_code
        == 400
    )
    token = post("staff", {"username": "helper", "role": "superadmin"}).json["token"]
    assert (
        send(guest, "staff/activate", {"token": token, "password": "short"}).status_code
        == 400
    )
    assert (
        send(
            guest, "staff/activate", {"token": token, "password": "long-test-password"}
        ).status_code
        == 200
    )
    assert (
        send(
            guest, "staff/activate", {"token": token, "password": "long-test-password"}
        ).status_code
        == 400
    )
    assert (
        send(
            guest, "login", {"username": "helper", "password": "long-test-password"}
        ).status_code
        == 200
    )
    assert guest.get("/api/session").json["role"] == "product_admin"
    for endpoint in ["staff", "orders", "dashboard", "product-activity"]:
        assert guest.get("/api/" + endpoint).status_code == 403
    assert send(guest, "staff", {"username": "another"}).status_code == 403
    ref = checkout().json["reference"]
    for endpoint in ["agreement", "payments", "dismiss", "reserve"]:
        assert send(guest, "orders/" + ref + "/" + endpoint, {}).status_code == 403
    assert send(guest, "products", product).status_code == 403
    assert send(guest, "products", dict(product, published=False)).status_code == 403
    draft = dict(product, id="staff-draft", published=False)
    assert send(guest, "products", draft).status_code == 200
    assert "staff-draft" not in [p["id"] for p in c.get("/api/products").json]
    assert c.get("/api/product-activity").json[0]["actor"] == "helper"
    assert post("products", dict(draft, published=True)).status_code == 200
    assert send(guest, "products", draft).status_code == 403
    member = c.get("/api/staff").json[0]
    assert "password" not in member and "invite_hash" not in member
    assert post("staff", {"action": "revoke", "id": member["id"]}).status_code == 200
    assert guest.get("/api/session").json["role"] is None
    assert send(guest, "products", draft).status_code == 401
    assert (
        send(
            guest, "login", {"username": "helper", "password": "long-test-password"}
        ).status_code
        == 401
    )
    reset = post("staff", {"action": "reset", "id": member["id"]}).json["token"]
    assert (
        send(
            guest,
            "staff/activate",
            {"token": reset, "password": "new-long-test-password"},
        ).status_code
        == 200
    )
    assert (
        send(
            guest, "login", {"username": "helper", "password": "new-long-test-password"}
        ).status_code
        == 200
    )
    assert guest.get("/api/session").json["role"] == "product_admin"


def test_expired_and_replaced_staff_invites(store):
    app, c, post, product, checkout, payment = store
    first = post("staff", {"username": "helper"}).json["token"]
    member = c.get("/api/staff").json[0]
    second = post("staff", {"action": "reset", "id": member["id"]}).json["token"]
    assert (
        post(
            "staff/activate", {"token": first, "password": "test-long-password"}
        ).status_code
        == 400
    )
    with app.app_context():
        app.db().execute(
            "UPDATE staff SET expires=? WHERE id=?",
            ("2000-01-01T00:00:00+00:00", member["id"]),
        )
        app.db().commit()
    assert (
        post(
            "staff/activate", {"token": second, "password": "test-long-password"}
        ).status_code
        == 400
    )
    assert post("staff", {"username": "owner"}).status_code == 400
    assert post("staff", {"username": "helper"}).status_code == 400


def test_owner_password_reset_invalidates_existing_session(store):
    app, c, post, product, checkout, payment = store
    assert c.get("/api/session").json["role"] == "superadmin"
    with app.app_context():
        app.db().execute(
            "UPDATE owner SET password=? WHERE id=1",
            (generate_password_hash("replacement-password"),),
        )
        app.db().commit()
    assert c.get("/api/session").json["role"] is None
    assert c.get("/api/staff").status_code == 401


def test_owner_setup_invitation(store):
    from app import issue_owner_invitation

    app, c, post, product, checkout, payment = store
    token = issue_owner_invitation(app, "owner")
    guest = app.test_client()

    def activate(body):
        return guest.post(
            "/api/owner-invitation",
            json=body,
            headers={"X-CSRF-Token": guest.get("/api/session").json["csrf"]},
        )

    assert activate({"token": "made-up"}).status_code == 400
    assert activate({"token": token}).json == {"username": "owner"}
    assert activate({"token": token, "password": "short"}).status_code == 400
    assert (
        activate({"token": token, "password": "new-long-password"}).status_code == 200
    )
    assert c.get("/api/session").json["role"] is None
    assert activate({"token": token}).status_code == 400
    assert (
        activate({"token": token, "password": "another-long-password"}).status_code
        == 400
    )


def test_owner_invitation_expiry_replacement_and_account_change(store):
    from app import issue_owner_invitation

    app, c, post, product, checkout, payment = store
    import pytest

    with pytest.raises(ValueError):
        issue_owner_invitation(app, "someoneelse")
    first = issue_owner_invitation(app, "owner")
    second = issue_owner_invitation(app, "owner")
    assert post("owner-invitation", {"token": first}).status_code == 400
    with app.app_context():
        app.db().execute("UPDATE owner_invitation SET expires=?", ("2000-01-01",))
        app.db().commit()
    assert post("owner-invitation", {"token": second}).status_code == 400
    third = issue_owner_invitation(app, "owner")
    with app.app_context():
        app.db().execute(
            "UPDATE owner SET password=?", (generate_password_hash("changed-password"),)
        )
        app.db().commit()
    assert post("owner-invitation", {"token": third}).status_code == 400
