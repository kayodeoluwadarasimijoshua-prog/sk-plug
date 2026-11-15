import os, json, secrets, hashlib, io
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from functools import wraps
from flask import (
    Flask,
    request,
    jsonify,
    session,
    send_from_directory,
    render_template,
    g,
)
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageOps, UnidentifiedImageError
from persistence import (
    connect_database,
    SupabasePhotos,
    CloudinaryPhotos,
    PRODUCT_COLUMNS,
)

from store_config import load_config, read_settings
from migrations import migrate, BASELINE
from extensions import register

ROOT = Path(__file__).parent


def now():
    return datetime.now(timezone.utc).isoformat()


def money(n):
    return "₦" + format(n / 100, ",.2f")


def fail(message, status=400, **extra):
    return jsonify(error=message, **extra), status


def integer(v, minimum=0, maximum=10**12):
    if type(v) is not int or not minimum <= v <= maximum:
        raise ValueError("Enter a valid whole number in the allowed range.")
    return v


def owner_snapshot(database):
    row = database.execute("SELECT username,password FROM owner WHERE id=1").fetchone()
    return hashlib.sha256(
        json.dumps([row["username"], row["password"]] if row else None).encode()
    ).hexdigest()


def issue_owner_invitation(app, username):
    """Privileged provisioning only: never exposed as a public creation endpoint."""
    username = str(username).strip().lower()
    if not 3 <= len(username) <= 60 or not all(
        c.isascii() and (c.isalnum() or c in "._-") for c in username
    ):
        raise ValueError("Use 3–60 letters, numbers, dots, underscores or hyphens.")
    token = secrets.token_urlsafe(32)
    with app.app_context():
        database = app.db()
        with database:
            database.execute("BEGIN IMMEDIATE")
            if database.execute(
                "SELECT 1 FROM staff WHERE username=?", (username,)
            ).fetchone():
                raise ValueError("This username belongs to a staff account.")
            current = database.execute(
                "SELECT username FROM owner WHERE id=1"
            ).fetchone()
            if current and current["username"] != username:
                raise ValueError(
                    "An owner already exists. Use the existing owner username for recovery."
                )
            database.execute(
                "INSERT INTO owner_invitation(id,username,token_hash,expires,snapshot) VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,token_hash=excluded.token_hash,expires=excluded.expires,snapshot=excluded.snapshot",
                (
                    username,
                    hashlib.sha256(token.encode()).hexdigest(),
                    (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                    owner_snapshot(database),
                ),
            )
    return token


def create_app(config=None):
    app = Flask(__name__)
    vercel = os.getenv("VERCEL") == "1" or os.getenv("APP_ENV") == "production"
    app.config.update(
        DATA_DIR=os.getenv(
            "DATA_DIR", str(ROOT / "data" / os.getenv("STORE_ID", "local"))
        ),
        PREVIEW=os.getenv("PREVIEW", "0" if vercel else "1") == "1",
        DATABASE_URL=os.getenv("DATABASE_URL", ""),
        SUPABASE_URL=os.getenv("SUPABASE_URL", ""),
        SUPABASE_SERVICE_ROLE_KEY=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
        SUPABASE_STORAGE_BUCKET=os.getenv("SUPABASE_STORAGE_BUCKET", "product-images"),
        CLOUDINARY_CLOUD_NAME=os.getenv("CLOUDINARY_CLOUD_NAME", ""),
        CLOUDINARY_API_KEY=os.getenv("CLOUDINARY_API_KEY", ""),
        CLOUDINARY_API_SECRET=os.getenv("CLOUDINARY_API_SECRET", ""),
        SECRET_KEY=os.getenv("SECRET_KEY"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "1" if vercel else "0") == "1",
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    if config:
        app.config.update(config)
    app.config["STORE"] = load_config(app.config.get("STORE"))
    app.config["PAYSTACK_SECRET_KEY"] = app.config.get(
        "PAYSTACK_SECRET_KEY", os.getenv("PAYSTACK_SECRET_KEY", "")
    )
    app.config["SITE_URL"] = app.config.get(
        "SITE_URL", os.getenv("SITE_URL", "http://localhost:3000")
    )
    app.config["SESSION_COOKIE_NAME"] = "growthly_" + app.config["STORE"]["storeId"]
    if vercel and not app.config["SITE_URL"].startswith("https://"):
        raise RuntimeError("Set SITE_URL to the live HTTPS origin.")
    if vercel and not app.config.get("TESTING"):
        if app.config["PREVIEW"]:
            raise RuntimeError("Disable PREVIEW before production deployment.")
        if app.config["STORE"]["storeId"] == "demo":
            raise RuntimeError(
                "Set a unique client storeId before production deployment."
            )
    cloudinary_fields = (
        "CLOUDINARY_CLOUD_NAME",
        "CLOUDINARY_API_KEY",
        "CLOUDINARY_API_SECRET",
    )
    has_cloudinary = all(app.config.get(name) for name in cloudinary_fields)
    has_supabase = bool(
        app.config["SUPABASE_URL"] and app.config["SUPABASE_SERVICE_ROLE_KEY"]
    )
    if any(app.config.get(name) for name in cloudinary_fields) and not has_cloudinary:
        raise RuntimeError("Set all three Cloudinary environment variables.")
    if vercel:
        missing = [
            name for name in ("DATABASE_URL", "SECRET_KEY") if not app.config.get(name)
        ]
        if not has_cloudinary and not has_supabase:
            missing.extend(cloudinary_fields)
        if missing:
            raise RuntimeError(
                "Configure Vercel environment variables: " + ", ".join(missing)
            )
        if not app.config["DATABASE_URL"].startswith(("postgres://", "postgresql://")):
            raise RuntimeError("Vercel requires a persistent PostgreSQL DATABASE_URL.")
        if len(app.config["SECRET_KEY"]) < 32:
            raise RuntimeError("SECRET_KEY must contain at least 32 characters.")
    data = Path(app.config["DATA_DIR"])
    remote_photos = None
    if has_cloudinary:
        remote_photos = CloudinaryPhotos(
            *(app.config[name] for name in cloudinary_fields)
        )
    elif has_supabase:
        remote_photos = SupabasePhotos(
            app.config["SUPABASE_URL"],
            app.config["SUPABASE_SERVICE_ROLE_KEY"],
            app.config["SUPABASE_STORAGE_BUCKET"],
        )
    if (
        not remote_photos
        or not app.config["DATABASE_URL"]
        or not app.config["SECRET_KEY"]
    ):
        data.mkdir(parents=True, exist_ok=True)
    if not remote_photos:
        (data / "uploads").mkdir(exist_ok=True)
    if not app.config["SECRET_KEY"]:
        key = data / "session.key"
        try:
            with key.open("x") as f:
                f.write(secrets.token_hex(32))
            key.chmod(0o600)
        except FileExistsError:
            pass
        app.secret_key = key.read_text()

    def db():
        if "db" not in g:
            g.db = connect_database(app.config["DATABASE_URL"], data / "store.db")
        return g.db

    app.db = db

    @app.teardown_appcontext
    def close(_):
        if "db" in g:
            g.db.close()

    with app.app_context():
        db().executescript(BASELINE)
        migrate(db(), now())
        for c in app.config["STORE"]["categories"]:
            db().execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (c,))
        db().commit()

    def identity():
        if session.get("staff_id"):
            row = (
                db()
                .execute("SELECT * FROM staff WHERE id=?", (session["staff_id"],))
                .fetchone()
            )
            if (
                row
                and row["active"]
                and row["password"]
                and row["version"] == session.get("staff_version")
            ):
                return row["username"], "product_admin"
            return None, None
        username = session.get("owner")
        row = (
            db()
            .execute("SELECT password FROM owner WHERE username=?", (username,))
            .fetchone()
            if username
            else None
        )
        if (
            row
            and session.get("owner_version")
            == hashlib.sha256(row["password"].encode()).hexdigest()
        ):
            return username, "superadmin"
        return None, None

    def access(superadmin=False):
        def decorate(fn):
            @wraps(fn)
            def inner(*a, **kw):
                username, role = identity()
                if not role:
                    return fail("Admin sign-in required.", 401)
                if superadmin and role != "superadmin":
                    return fail("Super Admin access required.", 403)
                return fn(*a, **kw)

            return inner

        return decorate

    owner = access(superadmin=True)
    product_admin = access()

    @app.before_request
    def security():
        if request.path == "/api/gateway/webhook":
            return None  # authenticated by HMAC over the raw body in its handler
        if request.path.startswith("/api/") and request.method == "POST":
            # Database-backed rolling limits survive serverless restarts.
            from datetime import timedelta

            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
            bucket = hashlib.sha256(
                (str(request.remote_addr) + ":" + request.path).encode()
            ).hexdigest()
            limit = (
                8
                if request.path == "/api/login"
                else (
                    20
                    if request.path
                    in ["/api/enquiries", "/api/checkout", "/api/gateway/initialize"]
                    else 120
                )
            )
            with db():
                db().execute("BEGIN IMMEDIATE")
                db().execute("DELETE FROM request_limits WHERE created<?", (cutoff,))
                if (
                    db()
                    .execute(
                        "SELECT COUNT(*) FROM request_limits WHERE bucket=?", (bucket,)
                    )
                    .fetchone()[0]
                    >= limit
                ):
                    return fail("Too many requests. Try again later.", 429)
                db().execute("INSERT INTO request_limits VALUES(?,?)", (bucket, now()))
        if request.path.startswith("/api/") and request.method not in [
            "GET",
            "HEAD",
            "OPTIONS",
        ]:
            if not secrets.compare_digest(
                request.headers.get("X-CSRF-Token", ""), session.get("csrf", "!")
            ):
                return fail("Refresh the page and try again.", 403)
            if request.path != "/api/upload" and not isinstance(
                request.get_json(silent=True), dict
            ):
                return fail("Send a valid request object.")
            if request.path != "/api/upload":
                body = request.get_json()
                for field in [
                    "username",
                    "password",
                    "id",
                    "category",
                    "reference",
                    "token",
                    "key",
                ]:
                    if field in body and not isinstance(body[field], str):
                        return fail("Invalid text field: " + field)
                for field in [
                    "product_id",
                    "variant_id",
                    "corrects",
                    "received",
                    "due",
                    "review",
                ]:
                    if (
                        field in body
                        and body[field] is not None
                        and not isinstance(body[field], str)
                    ):
                        return fail("Invalid text field: " + field)
                if "rider_direct" in body and type(body["rider_direct"]) is not bool:
                    return fail("Rider direct must be true or false.")
                if "published" in body and type(body["published"]) is not bool:
                    return fail("Published must be true or false.")

    @app.after_request
    def headers(res):
        res.headers["X-Content-Type-Options"] = "nosniff"
        res.headers["X-Frame-Options"] = "DENY"
        res.headers["Referrer-Policy"] = "same-origin"
        image_origin = remote_photos.url if remote_photos else ""
        res.headers["Content-Security-Policy"] = (
            f"default-src 'self'; img-src 'self' blob: data: {image_origin}; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        if request.path.startswith("/api/"):
            res.headers["Cache-Control"] = "no-store"
        return res

    @app.errorhandler(ValueError)
    def invalid(e):
        return fail(str(e))

    @app.errorhandler(413)
    def large(e):
        return fail("Photo must be smaller than 12 MB.", 413)

    def product(row):
        p = dict(row)
        if not hasattr(g, "product_metadata"):
            g.product_metadata = {
                r["product_id"]: r for r in db().execute("SELECT * FROM product_meta")
            }
        meta = g.product_metadata.get(p["id"])
        p["archived"] = bool(meta["archived"]) if meta else False
        p["featured"] = bool(meta["featured"]) if meta else False
        p["specifications"] = json.loads(meta["specifications"]) if meta else {}
        p["images"] = json.loads(p["images"])
        p["variants"] = json.loads(p["variants"])
        p["published"] = bool(p["published"])
        if not hasattr(g, "reserved_totals"):
            g.reserved_totals = {
                (r["product_id"], r["variant"]): int(r["qty"])
                for r in db().execute(
                    "SELECT product_id,variant,SUM(qty) qty FROM reservations GROUP BY product_id,variant"
                )
            }
        for v in p["variants"]:
            held = g.reserved_totals.get((p["id"], v["id"]), 0)
            v["available"] = max(0, v["stock"] - held)
            v["reserved"] = held
        return p

    def getorder(ref):
        r = db().execute("SELECT * FROM orders WHERE id=?", (ref,)).fetchone()
        if not r:
            raise ValueError("Order not found.")
        o = dict(r)
        o["items"] = json.loads(o["items"])
        o["payments"] = [
            dict(x)
            for x in db().execute(
                "SELECT * FROM payments WHERE order_id=? ORDER BY created,id", (ref,)
            )
        ]
        replaced = {x["corrects"] for x in o["payments"] if x["corrects"]}
        effective = [x for x in o["payments"] if x["id"] not in replaced]
        o["paid_products"] = sum(x["products"] for x in effective)
        o["paid_delivery"] = sum(x["delivery"] for x in effective)
        o["balance"] = max(0, o["total"] - o["paid_products"])
        o["excess"] = max(0, o["paid_products"] - o["total"])
        o["delivery_balance"] = (
            0 if o["rider_direct"] else max(0, o["delivery_fee"] - o["paid_delivery"])
        )
        o["delivery_excess"] = max(
            0, o["paid_delivery"] - (0 if o["rider_direct"] else o["delivery_fee"])
        )
        o["overdue"] = bool(
            o["due"]
            and o["balance"]
            and o["due"] < datetime.now(ZoneInfo("Africa/Lagos")).date().isoformat()
        )
        o["follow_up"] = (
            read_settings(app, db())["features"]["instalments"]
            and len(effective) >= 3
            and o["balance"] > 0
        )
        o["payment_count"] = len(effective)
        o["reservations"] = [
            dict(x)
            for x in db().execute("SELECT * FROM reservations WHERE order_id=?", (ref,))
        ]
        o["inventory_conflicts"] = []
        for item in o["items"]:
            row = (
                db()
                .execute(
                    "SELECT variants FROM products WHERE id=?", (item["product_id"],)
                )
                .fetchone()
            )
            variant = (
                next(
                    (v for v in json.loads(row[0]) if v["id"] == item["variant_id"]),
                    None,
                )
                if row
                else None
            )
            if variant:
                held = int(
                    db()
                    .execute(
                        "SELECT COALESCE(SUM(qty),0) FROM reservations WHERE product_id=? AND variant=?",
                        (item["product_id"], item["variant_id"]),
                    )
                    .fetchone()[0]
                )
                if variant["stock"] < held:
                    o["inventory_conflicts"].append(
                        item["name"]
                        + ": stock does not cover existing reservations. Review before fulfilment."
                    )
            elif o["status"] not in ("Paid", "Dismissed"):
                o["inventory_conflicts"].append(
                    item["name"]
                    + ": the original size/colour is no longer in the catalogue."
                )
        return o

    def recalc(ref):
        o = getorder(ref)
        status = (
            "Paid"
            if o["paid_products"] >= o["total"]
            else "Part-paid" if o["paid_products"] else "Awaiting payment"
        )
        paid = status == "Paid"
        applied = bool(o["stock_applied"])
        if paid != applied:
            for item in o["items"]:
                row = (
                    db()
                    .execute(
                        "SELECT variants FROM products WHERE id=?",
                        (item["product_id"],),
                    )
                    .fetchone()
                )
                if not row:
                    continue
                variants = json.loads(row[0])
                for v in variants:
                    if v["id"] == item["variant_id"]:
                        v["stock"] = (
                            v["stock"] - item["qty"]
                            if paid
                            else v["stock"] + item["qty"]
                        )
                db().execute(
                    "UPDATE products SET variants=? WHERE id=?",
                    (json.dumps(variants), item["product_id"]),
                )
            if paid:
                db().execute("DELETE FROM reservations WHERE order_id=?", (ref,))
        db().execute(
            "UPDATE orders SET status=?,completed=?,stock_applied=? WHERE id=?",
            (status, (o["completed"] or now()) if paid else None, int(paid), ref),
        )

    @app.get("/api/session")
    def current():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(24)
        return jsonify(
            csrf=session["csrf"],
            owner=identity()[0],
            role=identity()[1],
            preview=app.config["PREVIEW"],
        )

    @app.post("/api/login")
    def login():
        body = request.get_json()
        ip = request.remote_addr
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        if (
            db()
            .execute(
                "SELECT COUNT(*) FROM login_attempts WHERE ip=? AND created>?",
                (ip, cutoff),
            )
            .fetchone()[0]
            >= 8
        ):
            return fail("Too many attempts. Try again in 15 minutes.", 429)
        row = (
            db()
            .execute("SELECT * FROM owner WHERE username=?", (body.get("username"),))
            .fetchone()
        )
        staff_row = None
        if not row:
            staff_row = (
                db()
                .execute(
                    "SELECT * FROM staff WHERE username=? AND active=1",
                    (body.get("username"),),
                )
                .fetchone()
            )
            row = staff_row
        if (
            not row
            or body.get("username") != row["username"]
            or not row["password"]
            or not check_password_hash(row["password"], str(body.get("password", "")))
        ):
            db().execute("INSERT INTO login_attempts VALUES(?,?)", (ip, now()))
            db().commit()
            return fail("Sign-in details are incorrect.", 401)
        session.clear()
        session["owner"] = row["username"]
        if not staff_row:
            session["owner_version"] = hashlib.sha256(
                row["password"].encode()
            ).hexdigest()
        if staff_row:
            session["staff_id"] = row["id"]
            session["staff_version"] = row["version"]
        session["csrf"] = secrets.token_hex(24)
        session.permanent = True
        return jsonify(ok=True, csrf=session["csrf"])

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/staff")
    @owner
    def staff_list():
        rows = db().execute(
            "SELECT id,username,active,password FROM staff ORDER BY username"
        )
        return jsonify(
            [
                {
                    "id": r["id"],
                    "username": r["username"],
                    "active": bool(r["active"]),
                    "status": "Active" if r["password"] else "Invitation pending",
                }
                for r in rows
            ]
        )

    @app.post("/api/staff")
    @owner
    def staff_manage():
        b = request.get_json()
        action = b.get("action", "invite")
        with db():
            db().execute("BEGIN IMMEDIATE")
            if action == "revoke":
                db().execute(
                    "UPDATE staff SET active=0,version=version+1,invite_hash=NULL WHERE id=?",
                    (b.get("id"),),
                )
                return jsonify(ok=True)
            if action not in ["invite", "reset"]:
                raise ValueError("Choose a valid staff action.")
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            if action == "reset":
                row = (
                    db()
                    .execute("SELECT id FROM staff WHERE id=?", (b.get("id"),))
                    .fetchone()
                )
                if not row:
                    return fail("Staff member not found.", 404)
                db().execute(
                    "UPDATE staff SET password=NULL,active=1,version=version+1,invite_hash=?,expires=? WHERE id=?",
                    (digest, expires, row["id"]),
                )
            else:
                username = str(b.get("username", "")).strip().lower()
                if not 3 <= len(username) <= 60 or not all(
                    c.isascii() and (c.isalnum() or c in "._-") for c in username
                ):
                    raise ValueError(
                        "Use 3–60 letters, numbers, dots, underscores or hyphens."
                    )
                if (
                    db()
                    .execute("SELECT 1 FROM owner WHERE lower(username)=?", (username,))
                    .fetchone()
                    or db()
                    .execute("SELECT 1 FROM staff WHERE username=?", (username,))
                    .fetchone()
                ):
                    raise ValueError("That username is already in use.")
                db().execute(
                    "INSERT INTO staff(id,username,invite_hash,expires) VALUES(?,?,?,?)",
                    (secrets.token_hex(16), username, digest, expires),
                )
        return jsonify(token=token)

    @app.post("/api/owner-invitation")
    def owner_activation():
        b = request.get_json()
        digest = hashlib.sha256(str(b.get("token", "")).encode()).hexdigest()
        with db():
            db().execute("BEGIN IMMEDIATE")
            invitation = (
                db()
                .execute(
                    "SELECT * FROM owner_invitation WHERE token_hash=? AND expires>?",
                    (digest, now()),
                )
                .fetchone()
            )
            if not invitation or invitation["snapshot"] != owner_snapshot(db()):
                return fail(
                    "This setup link has expired or was already used. Ask your website administrator for a new one.",
                    400,
                )
            if "password" not in b:
                return jsonify(username=invitation["username"])
            password = str(b["password"])
            if not 12 <= len(password) <= 200:
                raise ValueError("Choose a password of 12–200 characters.")
            if (
                db()
                .execute(
                    "SELECT 1 FROM staff WHERE username=?", (invitation["username"],)
                )
                .fetchone()
            ):
                return fail(
                    "This username is no longer available. Ask for a new setup link."
                )
            db().execute(
                "INSERT INTO owner(id,username,password) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,password=excluded.password",
                (invitation["username"], generate_password_hash(password)),
            )
            db().execute("DELETE FROM owner_invitation WHERE id=1")
        session.clear()
        return jsonify(ok=True, username=invitation["username"])

    @app.post("/api/staff/activate")
    def staff_activate():
        b = request.get_json()
        password = str(b.get("password", ""))
        if not 12 <= len(password) <= 200:
            raise ValueError("Choose a password of 12–200 characters.")
        digest = hashlib.sha256(str(b.get("token", "")).encode()).hexdigest()
        with db():
            db().execute("BEGIN IMMEDIATE")
            row = (
                db()
                .execute(
                    "SELECT id FROM staff WHERE invite_hash=? AND active=1 AND expires>?",
                    (digest, now()),
                )
                .fetchone()
            )
            if not row:
                return fail(
                    "This invitation has expired or was already used. Ask the Super Admin for a new one.",
                    400,
                )
            db().execute(
                "UPDATE staff SET password=?,invite_hash=NULL,expires=NULL WHERE id=?",
                (generate_password_hash(password), row["id"]),
            )
        return jsonify(ok=True)

    @app.get("/api/product-activity")
    @owner
    def product_activity():
        return jsonify(
            [
                dict(r)
                for r in db().execute(
                    "SELECT a.*,p.name AS product_name FROM product_audit a LEFT JOIN products p ON p.id=a.product_id ORDER BY a.created DESC LIMIT 100"
                )
            ]
        )

    @app.get("/api/products")
    def products():
        admin = request.args.get("admin") == "1" and identity()[1]
        rows = db().execute(
            "SELECT * FROM products"
            + (
                ""
                if admin
                else " WHERE published=1"
                + ("" if app.config["PREVIEW"] else " AND sample=0")
            )
            + " ORDER BY rowid DESC"
        )
        result = [product(r) for r in rows]
        return jsonify([p for p in result if admin or not p["archived"]])

    @app.get("/api/categories")
    def categories():
        return jsonify(
            [r[0] for r in db().execute("SELECT name FROM categories ORDER BY rowid")]
        )

    @app.post("/api/categories")
    @product_admin
    def category():
        name = str(request.get_json().get("name", "")).strip()
        if not 1 <= len(name) <= 40:
            raise ValueError("Category must have 1–40 characters.")
        db().execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (name,))
        db().commit()
        return jsonify(ok=True)

    @app.post("/api/products")
    @product_admin
    def save_product():
        b = request.get_json()
        pid = b.get("id") or secrets.token_hex(8)
        specifications = b.get("specifications", {})
        if (
            not isinstance(specifications, dict)
            or len(specifications) > 50
            or any(
                not isinstance(k, str)
                or not isinstance(v, str)
                or len(k) > 80
                or len(v) > 500
                for k, v in specifications.items()
            )
        ):
            raise ValueError("Specifications must be up to 50 short text pairs.")
        if type(b.get("featured", False)) is not bool:
            raise ValueError("Featured must be true or false.")
        name = str(b.get("name", "")).strip()
        price = integer(b.get("price"), 1)
        variants = b.get("variants")
        images = b.get("images", [])
        if (
            not name
            or len(name) > 150
            or not db()
            .execute("SELECT 1 FROM categories WHERE name=?", (b.get("category"),))
            .fetchone()
        ):
            raise ValueError("Name and a valid category are required.")
        if not isinstance(variants, list) or not 1 <= len(variants) <= 100:
            raise ValueError("Add 1–100 variant combinations.")
        ids = set()
        combos = set()
        for v in variants:
            if not isinstance(v, dict):
                raise ValueError("Each combination must be an object.")
            v["id"] = str(v.get("id") or secrets.token_hex(6))
            v["size"] = str(v.get("size", ""))[:40]
            v["colour"] = str(v.get("colour", ""))[:40]
            integer(v.get("stock"), 0, 100000)
            if v["id"] in ids or (v["size"], v["colour"]) in combos:
                raise ValueError("Each size and colour combination must be unique.")
            ids.add(v["id"])
            combos.add((v["size"], v["colour"]))
        if (
            not isinstance(images, list)
            or not 1 <= len(images) <= 8
            or any(
                not isinstance(i, str)
                or not (
                    i in ["/static/demo-object.svg", "/static/demo-gadget.svg"]
                    or (not remote_photos and i.startswith("/uploads/"))
                    or (remote_photos and remote_photos.valid_url(i))
                )
                or ".." in i
                for i in images
            )
        ):
            raise ValueError("Upload 1–8 product photos.")
        with db():
            db().execute("BEGIN IMMEDIATE")
            if identity()[1] == "product_admin":
                existing = (
                    db()
                    .execute("SELECT published FROM products WHERE id=?", (pid,))
                    .fetchone()
                )
                if b.get("published") or (existing and existing["published"]):
                    return fail(
                        "Product Admins can save drafts only. Ask the Super Admin to edit or publish live products.",
                        403,
                    )
            old_row = (
                db()
                .execute("SELECT variants FROM products WHERE id=?", (pid,))
                .fetchone()
            )
            old_variants = (
                {v["id"]: v for v in json.loads(old_row[0])} if old_row else {}
            )
            for v in variants:
                old = old_variants.get(v["id"])
                if old and (old.get("size", ""), old.get("colour", "")) != (
                    v["size"],
                    v["colour"],
                ):
                    ids.discard(v["id"])
                    v["id"] = secrets.token_hex(6)
                    ids.add(v["id"])
            for r in db().execute(
                "SELECT variant,SUM(qty) qty FROM reservations WHERE product_id=? GROUP BY variant",
                (pid,),
            ):
                if (
                    r["variant"] not in ids
                    or next(v["stock"] for v in variants if v["id"] == r["variant"])
                    < r["qty"]
                ):
                    raise ValueError(
                        "Release reservations before removing or reducing this combination."
                    )
            db().execute(
                f"INSERT INTO products({PRODUCT_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET name=excluded.name,category=excluded.category,price=excluded.price,description=excluded.description,images=excluded.images,variants=excluded.variants,published=excluded.published",
                (
                    pid,
                    name,
                    b["category"],
                    price,
                    str(b.get("description", ""))[:5000],
                    json.dumps(images),
                    json.dumps(variants),
                    int(bool(b.get("published"))),
                ),
            )
            db().execute(
                "INSERT INTO product_meta(product_id,featured,specifications) VALUES(?,?,?) ON CONFLICT(product_id) DO UPDATE SET featured=excluded.featured,specifications=excluded.specifications",
                (pid, int(b.get("featured", False)), json.dumps(specifications)),
            )
            db().execute(
                "INSERT INTO product_audit VALUES(?,?,?,?,?)",
                (
                    secrets.token_hex(16),
                    pid,
                    identity()[0],
                    "Published" if b.get("published") else "Saved draft",
                    now(),
                ),
            )
        return jsonify(id=pid)

    @app.post("/api/upload")
    @product_admin
    def upload():
        f = request.files.get("photo")
        if not f:
            raise ValueError("Choose a photo.")
        try:
            im = Image.open(f.stream)
            if im.width * im.height > 24000000:
                raise ValueError(
                    "Photo is too large. Choose a photo under 24 megapixels."
                )
            im.load()
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((1600, 1600))
            name = secrets.token_hex(16) + ".webp"
            if remote_photos:
                output = io.BytesIO()
                im.save(output, "WEBP", quality=84)
                url = remote_photos.upload(name, output.getvalue())
            else:
                im.save(data / "uploads" / name, "WEBP", quality=84)
                url = "/uploads/" + name
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValueError("Choose a valid JPG, PNG or WebP photo.")
        return jsonify(url=url)

    @app.get("/uploads/<path:name>")
    def uploaded(name):
        if remote_photos:
            return fail("Photo not found.", 404)
        return send_from_directory(data / "uploads", name)

    @app.post("/api/checkout")
    def checkout():
        b = request.get_json()
        key = str(b.get("key", ""))
        items = b.get("items")
        fulfilment = b.get("fulfilment")
        store = read_settings(app, db())
        methods = []
        if store["features"]["whatsappCheckout"] and store["whatsapp"]:
            methods.append("whatsapp")
        if store["features"]["bankTransfer"]:
            methods.append("bank")
        if store["features"]["onlinePayment"] and app.config["PAYSTACK_SECRET_KEY"]:
            methods.append("online")
        if not methods:
            raise ValueError("Checkout is not configured. Contact the store.")
        if (
            fulfilment == "Pickup"
            and not store["features"]["pickup"]
            or fulfilment == "Request delivery"
            and not store["features"]["delivery"]
        ):
            raise ValueError("This fulfilment option is unavailable.")
        fingerprint = hashlib.sha256(
            json.dumps(
                {"items": items, "fulfilment": fulfilment}, sort_keys=True
            ).encode()
        ).hexdigest()
        if (
            not 16 <= len(key) <= 100
            or not isinstance(items, list)
            or not 1 <= len(items) <= 100
            or fulfilment not in ["Pickup", "Request delivery"]
        ):
            raise ValueError("Please check your cart and fulfilment choice.")
        with db():
            db().execute("BEGIN IMMEDIATE")
            existing = (
                db()
                .execute("SELECT * FROM orders WHERE checkout_key=?", (key,))
                .fetchone()
            )
            if existing:
                if existing["fingerprint"] != fingerprint:
                    return fail(
                        "This checkout has already been saved. Start a new cart.", 409
                    )
                return jsonify(handoff(dict(existing)))
            snapshots = []
            issues = []
            seen = set()
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("Each cart line must be an object.")
                qty = integer(item.get("qty"), 1, 99)
                pid = item.get("product_id")
                vid = item.get("variant_id")
                row = (
                    db()
                    .execute(
                        "SELECT * FROM products WHERE id=? AND published=1", (pid,)
                    )
                    .fetchone()
                )
                p = product(row) if row else None
                v = (
                    next((v for v in p["variants"] if v["id"] == vid), None)
                    if p
                    else None
                )
                if (pid, vid) in seen:
                    raise ValueError("Duplicate cart line.")
                seen.add((pid, vid))
                if (
                    not p
                    or p["archived"]
                    or (p["sample"] and not app.config["PREVIEW"])
                    or not v
                    or v["available"] < qty
                    or p["price"] != item.get("price")
                ):
                    issues.append(
                        {
                            "product_id": pid,
                            "variant_id": vid,
                            "name": p["name"] if p else "Removed product",
                            "price": p["price"] if p else None,
                            "available": v["available"] if v and p["published"] else 0,
                        }
                    )
                    continue
                snapshots.append(
                    {
                        "product_id": pid,
                        "variant_id": vid,
                        "name": p["name"],
                        "size": v["size"],
                        "colour": v["colour"],
                        "qty": qty,
                        "price": p["price"],
                        "image": p["images"][0],
                    }
                )
            if issues:
                return fail(
                    "Some items changed. Review your cart before continuing.",
                    409,
                    issues=issues,
                )
            ref = store["orderPrefix"] + "-" + secrets.token_hex(6).upper()
            total = sum(i["qty"] * i["price"] for i in snapshots)
            db().execute(
                "INSERT INTO orders(id,checkout_key,fingerprint,items,total,fulfilment,status,created) VALUES(?,?,?,?,?,?,?,?)",
                (
                    ref,
                    key,
                    fingerprint,
                    json.dumps(snapshots),
                    total,
                    fulfilment,
                    "Awaiting payment",
                    now(),
                ),
            )
            return jsonify(
                handoff(
                    dict(
                        db()
                        .execute("SELECT * FROM orders WHERE id=?", (ref,))
                        .fetchone()
                    )
                )
            )

    def handoff(o):
        items = json.loads(o["items"])
        store = read_settings(app, db())
        message = (
            f"Hello {store['businessName']}! I’d like to place an order.\nReference: {o['id']}\n"
            + "\n".join(
                f"• {i['name']} ({i['size'] or 'One size'}, {i['colour']}) × {i['qty']} — {money(i['price']*i['qty'])}"
                for i in items
            )
            + f"\nProduct subtotal: {money(o['total'])}\nFulfilment: {o['fulfilment']}\nAny delivery fee is agreed separately. Please confirm availability and payment details."
        )
        from urllib.parse import quote

        return {
            "reference": o["id"],
            "message": message,
            "url": (
                "https://wa.me/" + store["whatsapp"] + "?text=" + quote(message)
                if store["features"]["whatsappCheckout"] and store["whatsapp"]
                else None
            ),
        }

    @app.get("/api/orders")
    @owner
    def orders():
        return jsonify(
            [
                getorder(r[0])
                for r in db().execute("SELECT id FROM orders ORDER BY created DESC")
            ]
        )

    @app.post("/api/orders/<ref>/agreement")
    @owner
    def agreement(ref):
        getorder(ref)
        b = request.get_json()
        due = b.get("due") or None
        if due:
            datetime.strptime(due, "%Y-%m-%d")
        db().execute(
            "UPDATE orders SET due=?,note=?,delivery_fee=?,rider_direct=? WHERE id=?",
            (
                due,
                str(b.get("note", ""))[:2000],
                integer(b.get("delivery_fee", 0)),
                int(bool(b.get("rider_direct"))),
                ref,
            ),
        )
        db().commit()
        return jsonify(getorder(ref))

    @app.post("/api/orders/<ref>/payments")
    @owner
    def payment(ref):
        b = request.get_json()
        key = str(b.get("key", ""))
        p = integer(b.get("products"))
        d = integer(b.get("delivery"))
        reason = str(b.get("reason", "")).strip()
        corrects = b.get("corrects")
        note = str(b.get("note", "")).strip()
        received = b.get("received")
        if not 16 <= len(key) <= 100:
            raise ValueError("Refresh and retry the payment.")
        datetime.strptime(received, "%Y-%m-%d")
        if not corrects and p + d == 0:
            raise ValueError("Enter the amount received.")
        with db():
            db().execute("BEGIN IMMEDIATE")
            o = getorder(ref)
            existing = (
                db()
                .execute("SELECT * FROM payments WHERE submission_key=?", (key,))
                .fetchone()
            )
            if existing:
                expected = (ref, p, d, received, note, corrects, reason)
                actual = tuple(
                    existing[k]
                    for k in (
                        "order_id",
                        "products",
                        "delivery",
                        "received",
                        "note",
                        "corrects",
                        "reason",
                    )
                )
                if actual != expected:
                    return fail(
                        "This submission already recorded a different payment. Review its history before starting another entry.",
                        409,
                    )
                return jsonify(getorder(ref))
            if o["status"] == "Dismissed":
                raise ValueError("Dismissed orders cannot receive payments.")
            original = None
            if corrects:
                original = (
                    db()
                    .execute(
                        "SELECT * FROM payments WHERE id=? AND order_id=?",
                        (corrects, ref),
                    )
                    .fetchone()
                )
                if (
                    not original
                    or not reason
                    or db()
                    .execute("SELECT 1 FROM payments WHERE corrects=?", (corrects,))
                    .fetchone()
                ):
                    raise ValueError(
                        "Select an uncorrected payment and enter the correction reason."
                    )
            projected_products = (
                o["paid_products"] - (original["products"] if original else 0) + p
            )
            projected_delivery = (
                o["paid_delivery"] - (original["delivery"] if original else 0) + d
            )
            delivery_target = 0 if o["rider_direct"] else o["delivery_fee"]
            if (
                (not corrects and o["payment_count"] >= 3)
                or (o["due"] and received > o["due"])
                or projected_products > o["total"]
                or projected_delivery > delivery_target
            ) and not note:
                raise ValueError(
                    "Add an exception note for a payment outside the agreement or an excess."
                )
            db().execute(
                "INSERT INTO payments VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    secrets.token_hex(12),
                    ref,
                    key,
                    p,
                    d,
                    received,
                    note,
                    session["owner"],
                    now(),
                    corrects,
                    reason,
                ),
            )
            recalc(ref)
        return jsonify(getorder(ref))

    @app.post("/api/orders/<ref>/dismiss")
    @owner
    def dismiss(ref):
        b = request.get_json()
        with db():
            db().execute("BEGIN IMMEDIATE")
            o = getorder(ref)
            if o["payments"] and (b.get("review") != ref or not b.get("reason")):
                return fail(
                    "Review the payment history, type the reference and give a closing reason.",
                    409,
                )
            if o["status"] == "Paid":
                raise ValueError(
                    "Paid sales remain accounted for. Correct payments first if needed."
                )
            db().execute(
                "UPDATE orders SET status=?,note=? WHERE id=?",
                (
                    "Dismissed",
                    o["note"]
                    + "\nClosing review: "
                    + str(b.get("reason", "Abandoned request")),
                    ref,
                ),
            )
            db().execute("DELETE FROM reservations WHERE order_id=?", (ref,))
        return jsonify(ok=True)

    @app.post("/api/orders/<ref>/reserve")
    @owner
    def reserve(ref):
        b = request.get_json()
        pid = b.get("product_id")
        vid = b.get("variant_id")
        qty = integer(b.get("qty"), 0, 99)
        with db():
            db().execute("BEGIN IMMEDIATE")
            o = getorder(ref)
            if o["status"] in ["Paid", "Dismissed"]:
                raise ValueError("Only open orders can hold items.")
            item = next(
                (
                    i
                    for i in o["items"]
                    if i["product_id"] == pid and i["variant_id"] == vid
                ),
                None,
            )
            if not item or qty > item["qty"]:
                raise ValueError("Reserve only items in this order.")
            db().execute(
                "DELETE FROM reservations WHERE order_id=? AND product_id=? AND variant=?",
                (ref, pid, vid),
            )
            row = db().execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            p = product(row) if row else None
            v = next((v for v in p["variants"] if v["id"] == vid), None) if p else None
            if not v and qty:
                return fail(
                    "The original size/colour is no longer available. Review the order before reserving another selection.",
                    409,
                )
            if v and qty > v["available"]:
                raise ValueError("Not enough unreserved stock.")
            if qty:
                db().execute(
                    "INSERT INTO reservations VALUES(?,?,?,?)", (ref, pid, vid, qty)
                )
        return jsonify(getorder(ref))

    @app.get("/api/dashboard")
    @owner
    def dashboard():
        start = request.args.get("start")
        end = request.args.get("end")
        orders = [getorder(r[0]) for r in db().execute("SELECT id FROM orders")]
        paid = []
        for o in orders:
            if o["status"] != "Paid":
                continue
            date = (
                datetime.fromisoformat(o["completed"])
                .astimezone(ZoneInfo("Africa/Lagos"))
                .date()
                .isoformat()
            )
            if (not start or date >= start) and (not end or date <= end):
                paid.append(o)
        best = {}
        for o in paid:
            for i in o["items"]:
                entry = best.setdefault(
                    i["product_id"], {"name": i["name"], "units": 0}
                )
                entry["units"] += i["qty"]
        return jsonify(
            paid_orders=len(paid),
            product_sales=sum(o["total"] for o in paid),
            items_sold=sum(i["qty"] for o in paid for i in o["items"]),
            bestseller=max(best.values(), key=lambda x: x["units"]) if best else None,
            published=db()
            .execute(
                "SELECT COUNT(*) FROM products WHERE published=1"
                + ("" if app.config["PREVIEW"] else " AND sample=0")
            )
            .fetchone()[0],
            open_payments=sum(
                o["paid_products"]
                for o in orders
                if o["status"] not in ["Paid", "Dismissed"]
            ),
            closed_receipts=sum(
                o["paid_products"] + o["paid_delivery"]
                for o in orders
                if o["status"] == "Dismissed"
            ),
            open_delivery=sum(
                o["paid_delivery"] for o in orders if o["status"] != "Paid"
            ),
        )

    @app.get("/")
    @app.get("/<path:path>")
    def index(path=""):
        return render_template("index.html")

    register(app, db, owner, product_admin, identity, product, recalc, getorder)
    return app


app = create_app()
if __name__ == "__main__":
    import argparse, getpass

    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", default="run")
    parser.add_argument("--username", default="owner")
    parser.add_argument("--site-url", default="")
    args = parser.parse_args()
    if args.command == "owner-invite":
        if not app.config["DATABASE_URL"]:
            raise SystemExit(
                "Set DATABASE_URL securely to the production database before generating the live owner invitation."
            )
        from urllib.parse import urlparse

        parsed = urlparse(args.site_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ["", "/"]
        ):
            raise SystemExit(
                "Supply the live HTTPS origin using --site-url, for example https://your-store.example"
            )
        token = issue_owner_invitation(app, args.username)
        print(
            "Private owner setup link (expires in 24 hours; share only with the owner):"
        )
        print(args.site_url.rstrip("/") + "/admin/owner-setup#" + token)
    elif args.command == "owner":
        password = getpass.getpass("New owner password (at least 12 characters): ")
        if len(password) < 12:
            raise SystemExit("Use at least 12 characters.")
        with app.app_context():
            app.db().execute(
                "INSERT INTO owner(id,username,password) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET username=excluded.username,password=excluded.password",
                (args.username, generate_password_hash(password)),
            )
            app.db().commit()
    elif args.command == "seed":
        if not app.config["PREVIEW"]:
            raise SystemExit("Demo seeding is disabled in production.")
        from demo import seed

        seed(app)
    else:
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", "3000")), debug=False)
