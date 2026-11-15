"""Versioned additive schema extensions. Baseline commerce schema remains in app.py."""

EXTENSIONS = """
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,applied TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS store_settings(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS product_meta(product_id TEXT PRIMARY KEY REFERENCES products(id),archived INTEGER NOT NULL DEFAULT 0,featured INTEGER NOT NULL DEFAULT 0,specifications TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS category_meta(name TEXT PRIMARY KEY REFERENCES categories(name),parent TEXT REFERENCES categories(name));
CREATE TABLE IF NOT EXISTS enquiries(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL,message TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS transfer_claims(order_id TEXT PRIMARY KEY REFERENCES orders(id),reference TEXT NOT NULL,created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS gateway_payments(reference TEXT PRIMARY KEY,order_id TEXT NOT NULL REFERENCES orders(id),amount INTEGER NOT NULL,paid INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS request_limits(bucket TEXT NOT NULL,created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS request_limits_bucket_idx ON request_limits(bucket,created);
CREATE INDEX IF NOT EXISTS request_limits_created_idx ON request_limits(created);
CREATE INDEX IF NOT EXISTS reservations_product_idx ON reservations(product_id,variant);
CREATE INDEX IF NOT EXISTS payments_order_idx ON payments(order_id);
"""
TABLES = [
    "schema_migrations",
    "store_settings",
    "product_meta",
    "category_meta",
    "enquiries",
    "transfer_claims",
    "gateway_payments",
    "request_limits",
]


def migrate(database, timestamp):
    database.executescript(EXTENSIONS)
    database.execute(
        "INSERT OR IGNORE INTO schema_migrations(version,applied) VALUES(?,?)",
        (1, timestamp),
    )
    database.commit()


BASELINE = "\n        CREATE TABLE IF NOT EXISTS owner_invitation(id INTEGER PRIMARY KEY CHECK(id=1),username TEXT NOT NULL,token_hash TEXT NOT NULL,expires TEXT NOT NULL,snapshot TEXT NOT NULL);\n        CREATE TABLE IF NOT EXISTS staff(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,password TEXT,active INTEGER NOT NULL DEFAULT 1,version INTEGER NOT NULL DEFAULT 1,invite_hash TEXT,expires TEXT);\n        CREATE TABLE IF NOT EXISTS product_audit(id TEXT PRIMARY KEY,product_id TEXT,actor TEXT,action TEXT,created TEXT);\n        CREATE TABLE IF NOT EXISTS owner(id INTEGER PRIMARY KEY CHECK(id=1),username TEXT UNIQUE,password TEXT);\n        CREATE TABLE IF NOT EXISTS categories(name TEXT PRIMARY KEY);\n        CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL,price INTEGER NOT NULL CHECK(price>=0),description TEXT,images TEXT,variants TEXT,published INTEGER NOT NULL,sample INTEGER DEFAULT 0);\n        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,checkout_key TEXT UNIQUE NOT NULL,fingerprint TEXT NOT NULL,items TEXT NOT NULL,total INTEGER NOT NULL,fulfilment TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL,completed TEXT,due TEXT,note TEXT DEFAULT '',delivery_fee INTEGER DEFAULT 0,rider_direct INTEGER DEFAULT 0,stock_applied INTEGER DEFAULT 0);\n        CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY,order_id TEXT REFERENCES orders(id),submission_key TEXT UNIQUE,products INTEGER NOT NULL,delivery INTEGER NOT NULL,received TEXT NOT NULL,note TEXT,actor TEXT,created TEXT NOT NULL,corrects TEXT UNIQUE REFERENCES payments(id),reason TEXT);\n        CREATE TABLE IF NOT EXISTS reservations(order_id TEXT REFERENCES orders(id),product_id TEXT REFERENCES products(id),variant TEXT,qty INTEGER NOT NULL,PRIMARY KEY(order_id,product_id,variant));\n        CREATE TABLE IF NOT EXISTS login_attempts(ip TEXT,created TEXT);\n        "
