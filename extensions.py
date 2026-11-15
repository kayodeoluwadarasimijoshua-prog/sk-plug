"""Store settings, catalogue lifecycle, enquiries and payment adapters."""

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import quote, urlparse
from flask import request, jsonify, session
from store_config import validate, read_settings
from gateway import paystack


def register(app, db, owner, product_admin, identity, product, recalc, getorder):
    def now():
        return datetime.now(timezone.utc).isoformat()

    def settings():
        return read_settings(app, db())

    def controlled_order(body):
        row = (
            db()
            .execute(
                "SELECT * FROM orders WHERE id=? AND checkout_key=?",
                (body.get("reference"), body.get("key")),
            )
            .fetchone()
        )
        if not row:
            raise ValueError("Order access details are invalid.")
        if row["status"] == "Dismissed":
            raise ValueError("This order is closed.")
        return dict(row)

    @app.get("/store-theme.css")
    def theme_stylesheet():
        theme = settings()["theme"]
        from flask import Response

        return Response(
            ":root{" + ";".join("--" + k + ":" + v for k, v in theme.items()) + "}",
            mimetype="text/css",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/store")
    def public_store():
        result = settings()
        result["gatewayConfigured"] = bool(app.config["PAYSTACK_SECRET_KEY"])
        return jsonify(result)

    @app.post("/api/settings")
    @owner
    def save_settings():
        values = request.get_json()
        if (
            values.get("storeId", app.config["STORE"]["storeId"])
            != app.config["STORE"]["storeId"]
        ):
            raise ValueError("Store identity is fixed for this deployment.")
        config = validate({**settings(), **values})
        db().execute(
            "INSERT INTO store_settings(id,value) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value",
            (json.dumps(config),),
        )
        db().commit()
        return jsonify(ok=True)

    @app.get("/api/category-tree")
    def category_tree():
        return jsonify(
            [
                dict(r)
                for r in db().execute(
                    "SELECT c.name,m.parent FROM categories c LEFT JOIN category_meta m ON c.name=m.name ORDER BY c.name"
                )
            ]
        )

    @app.post("/api/category-tree")
    @owner
    def category_change():
        b = request.get_json()
        name = str(b.get("name", "")).strip()
        parent = b.get("parent") or None
        if not 1 <= len(name) <= 40:
            raise ValueError("Use a category name of 1–40 characters.")
        with db():
            db().execute("BEGIN IMMEDIATE")
            if parent:
                if (
                    not db()
                    .execute("SELECT 1 FROM categories WHERE name=?", (parent,))
                    .fetchone()
                ):
                    raise ValueError("Parent category does not exist.")
                seen = {name}
                current = parent
                while current:
                    if current in seen:
                        raise ValueError("Category hierarchy cannot contain a cycle.")
                    seen.add(current)
                    row = (
                        db()
                        .execute(
                            "SELECT parent FROM category_meta WHERE name=?", (current,)
                        )
                        .fetchone()
                    )
                    current = row[0] if row else None
            db().execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (name,))
            db().execute(
                "INSERT INTO category_meta(name,parent) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET parent=excluded.parent",
                (name, parent),
            )
        return jsonify(ok=True)

    @app.post("/api/products/<pid>/lifecycle")
    @owner
    def lifecycle(pid):
        action = request.get_json().get("action")
        if action not in ["archive", "restore", "delete"]:
            raise ValueError("Choose archive, restore or delete.")
        with db():
            db().execute("BEGIN IMMEDIATE")
            row = db().execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if not row:
                return jsonify(error="Product not found."), 404
            if action == "delete":
                used = any(
                    any(i["product_id"] == pid for i in json.loads(r[0]))
                    for r in db().execute("SELECT items FROM orders")
                )
                if used:
                    raise ValueError(
                        "Products referenced by orders must be archived to preserve records."
                    )
                db().execute("DELETE FROM product_meta WHERE product_id=?", (pid,))
                db().execute("DELETE FROM products WHERE id=?", (pid,))
            else:
                db().execute(
                    "INSERT INTO product_meta(product_id,archived) VALUES(?,?) ON CONFLICT(product_id) DO UPDATE SET archived=excluded.archived",
                    (pid, int(action == "archive")),
                )
                if action == "archive":
                    db().execute("UPDATE products SET published=0 WHERE id=?", (pid,))
            db().execute(
                "INSERT INTO product_audit VALUES(?,?,?,?,?)",
                (secrets.token_hex(16), pid, identity()[0], action, now()),
            )
        return jsonify(ok=True)

    @app.post("/api/enquiries")
    def enquire():
        b = request.get_json()
        name = str(b.get("name", "")).strip()
        email = str(b.get("email", "")).strip()
        message = str(b.get("message", "")).strip()
        if (
            not 1 <= len(name) <= 100
            or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
            or len(email) > 254
            or not 5 <= len(message) <= 3000
        ):
            raise ValueError(
                "Enter your name, valid email and a message of 5–3000 characters."
            )
        db().execute(
            "INSERT INTO enquiries VALUES(?,?,?,?,?,?)",
            (secrets.token_hex(16), name, email, message, "New", now()),
        )
        db().commit()
        return jsonify(ok=True)

    @app.get("/api/enquiries")
    @owner
    def enquiries():
        return jsonify(
            [
                dict(r)
                for r in db().execute(
                    "SELECT * FROM enquiries ORDER BY created DESC LIMIT 200"
                )
            ]
        )

    @app.post("/api/enquiries/<eid>")
    @owner
    def enquiry_status(eid):
        status = request.get_json().get("status")
        if status not in ["New", "Resolved"]:
            raise ValueError("Choose New or Resolved.")
        db().execute("UPDATE enquiries SET status=? WHERE id=?", (status, eid))
        db().commit()
        return jsonify(ok=True)

    @app.post("/api/transfer")
    def transfer_claim():
        if not settings()["features"]["bankTransfer"]:
            raise ValueError("Bank transfer is not enabled.")
        b = request.get_json()
        o = controlled_order(b)
        reference = str(b.get("transferReference", "")).strip()
        if not 3 <= len(reference) <= 150:
            raise ValueError("Enter a transfer reference of 3–150 characters.")
        db().execute(
            "INSERT INTO transfer_claims(order_id,reference,created) VALUES(?,?,?) ON CONFLICT(order_id) DO UPDATE SET reference=excluded.reference,created=excluded.created",
            (o["id"], reference, now()),
        )
        db().commit()
        return jsonify(ok=True, status="Awaiting verification")

    @app.get("/api/transfer-claims")
    @owner
    def transfer_claims():
        return jsonify(
            [
                dict(r)
                for r in db().execute(
                    "SELECT * FROM transfer_claims ORDER BY created DESC"
                )
            ]
        )

    def gateway_enabled():
        if (
            not settings()["features"]["onlinePayment"]
            or not app.config["PAYSTACK_SECRET_KEY"]
        ):
            raise ValueError("Online payments are not configured.")

    @app.post("/api/gateway/initialize")
    def initialize():
        gateway_enabled()
        b = request.get_json()
        o = controlled_order(b)
        email = str(b.get("email", ""))
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
            raise ValueError("Enter a valid email.")
        if getorder(o["id"])["paid_products"]:
            raise ValueError("This order already has a payment. Contact the store.")
        reference = "gw_" + secrets.token_hex(20)
        db().execute(
            "INSERT INTO gateway_payments(reference,order_id,amount) VALUES(?,?,?)",
            (reference, o["id"], o["total"]),
        )
        db().commit()
        result = paystack(
            app.config["PAYSTACK_SECRET_KEY"],
            "transaction/initialize",
            {
                "reference": reference,
                "amount": o["total"],
                "currency": "NGN",
                "email": email,
                "callback_url": app.config["SITE_URL"].rstrip("/") + "/payment-return",
            },
        )
        url = result.get("authorization_url", "")
        if (
            urlparse(url).scheme != "https"
            or urlparse(url).hostname != "checkout.paystack.com"
        ):
            raise ValueError("Unexpected payment provider response.")
        return jsonify(url=url, reference=reference)

    def verify_reference(reference):
        if not re.fullmatch(r"gw_[0-9a-f]{40}", str(reference)):
            raise ValueError("Invalid payment reference.")
        data = paystack(
            app.config["PAYSTACK_SECRET_KEY"],
            "transaction/verify/" + quote(reference, safe=""),
        )
        with db():
            db().execute("BEGIN IMMEDIATE")
            row = (
                db()
                .execute(
                    "SELECT * FROM gateway_payments WHERE reference=?", (reference,)
                )
                .fetchone()
            )
            if (
                not row
                or data.get("reference") != reference
                or data.get("status") != "success"
                or data.get("currency") != "NGN"
                or type(data.get("amount")) is not int
                or data["amount"] != row["amount"]
            ):
                raise ValueError(
                    "Payment is not verified. Contact the store if you were debited."
                )
            if not row["paid"]:
                o = getorder(row["order_id"])
                if o["status"] == "Dismissed" or o["paid_products"]:
                    raise ValueError(
                        "Payment needs owner reconciliation; no automatic duplicate credit was applied."
                    )
                db().execute(
                    "INSERT INTO payments VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        secrets.token_hex(16),
                        row["order_id"],
                        reference,
                        row["amount"],
                        0,
                        datetime.now(timezone.utc).date().isoformat(),
                        "Verified Paystack receipt",
                        "gateway",
                        now(),
                        None,
                        None,
                    ),
                )
                recalc(row["order_id"])
                db().execute(
                    "UPDATE gateway_payments SET paid=1 WHERE reference=?", (reference,)
                )
        return {"ok": True, "status": "Verified"}

    @app.post("/api/gateway/verify")
    def verify():
        gateway_enabled()
        return jsonify(verify_reference(request.get_json().get("reference")))

    @app.post("/api/gateway/webhook")
    def webhook():
        secret = app.config["PAYSTACK_SECRET_KEY"]
        if not secret:
            return jsonify(error="Not configured"), 403
        signature = hmac.new(
            secret.encode(), request.get_data(), hashlib.sha512
        ).hexdigest()
        if not hmac.compare_digest(
            signature, request.headers.get("x-paystack-signature", "")
        ):
            return jsonify(error="Invalid signature"), 403
        data = request.get_json(silent=True) or {}
        if data.get("event") == "charge.success":
            verify_reference(data.get("data", {}).get("reference"))
        return jsonify(ok=True)
