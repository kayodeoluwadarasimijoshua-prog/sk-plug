"""SQLite locally; PostgreSQL and Supabase Storage on Vercel.

The small PostgreSQL adapter retains SQLite-style parameter/row access so both
backends exercise the same accounting code. A transaction-scoped advisory lock
serializes commerce writes, matching SQLite's BEGIN IMMEDIATE semantics.
"""

import os
import re
import sqlite3
from migrations import TABLES
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

PRODUCT_COLUMNS = "id,name,category,price,description,images,variants,published,sample"


class Record(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        row = self.cursor.fetchone()
        return Record(row) if row is not None else None

    def fetchall(self):
        return [Record(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return (Record(row) for row in self.cursor)


class PostgresDatabase:
    def __init__(self, url):
        import psycopg
        from psycopg.rows import dict_row

        self.schema = os.getenv("DATABASE_SCHEMA", "growthly_private")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", self.schema):
            raise RuntimeError("DATABASE_SCHEMA must be a simple lowercase identifier.")
        # Disable prepared statements for Supabase's transaction pooler.
        self.connection = psycopg.connect(
            url,
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=10,
            prepare_threshold=None,
        )

    def execute(self, sql, params=()):
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            self.connection.execute("BEGIN")
            return Cursor(
                self.connection.execute("SELECT pg_advisory_xact_lock(74182051)")
            )
        ignore = "INSERT OR IGNORE" in sql.upper()
        sql = re.sub(r"INSERT OR IGNORE", "INSERT", sql, flags=re.I)
        if ignore:
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        # Fully qualify table names: transaction poolers must not rely on SET search_path.
        sql = re.sub(
            r"\b(FROM|JOIN|UPDATE|INTO|REFERENCES|TABLE IF NOT EXISTS|ON)\s+(owner|owner_invitation|staff|product_audit|categories|products|orders|payments|reservations|login_attempts|schema_migrations|store_settings|product_meta|category_meta|enquiries|transfer_claims|gateway_payments|request_limits)\b",
            lambda m: m[1] + " " + self.schema + "." + m[2],
            sql,
            flags=re.I,
        )
        sql = sql.replace("?", "%s")
        return Cursor(self.connection.execute(sql, params))

    def executescript(self, script):
        # Schema creation is guarded across simultaneous cold starts.
        with self:
            self.execute("BEGIN IMMEDIATE")
            self.connection.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            self.connection.execute(f"REVOKE ALL ON SCHEMA {self.schema} FROM PUBLIC")
            for role in ("anon", "authenticated"):
                if self.connection.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
                ).fetchone():
                    self.connection.execute(
                        f"REVOKE ALL ON SCHEMA {self.schema} FROM {role}"
                    )
            for statement in script.split(";"):
                if not statement.strip():
                    continue
                statement = re.sub(r"\bINTEGER\b", "BIGINT", statement)
                for table in ("products", "categories"):
                    statement = statement.replace(
                        f"CREATE TABLE IF NOT EXISTS {table}(",
                        f"CREATE TABLE IF NOT EXISTS {table}(rowid BIGSERIAL UNIQUE,",
                    )
                self.execute(statement)
            for table in (
                *TABLES,
                "owner",
                "owner_invitation",
                "staff",
                "product_audit",
                "categories",
                "products",
                "orders",
                "payments",
                "reservations",
                "login_attempts",
            ):
                if self.connection.execute(
                    "SELECT to_regclass(%s)", (self.schema + "." + table,)
                ).fetchone()["to_regclass"]:
                    self.connection.execute(
                        f"ALTER TABLE {self.schema}.{table} ENABLE ROW LEVEL SECURITY"
                    )

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.connection.commit()
        else:
            self.connection.rollback()


def connect_database(url, path):
    if url:
        return PostgresDatabase(url)
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


class SupabasePhotos:
    def __init__(self, url, key, bucket="product-images"):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("SUPABASE_URL must be the HTTPS project URL.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", bucket):
            raise RuntimeError("Use a valid Supabase storage bucket name.")
        self.url, self.key, self.bucket = url.rstrip("/"), key, bucket

    def upload(self, name, content):
        if not re.fullmatch(r"[a-f0-9]{32}\.webp", name):
            raise ValueError("Invalid photo name.")
        request = Request(
            f"{self.url}/storage/v1/object/{self.bucket}/{quote(name)}",
            data=content,
            method="POST",
            headers={
                "Authorization": "Bearer " + self.key,
                "apikey": self.key,
                "Content-Type": "image/webp",
                "x-upsert": "false",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                response.read()
        except (HTTPError, URLError, TimeoutError):
            # Do not expose provider error bodies, tokens or database URLs.
            raise ValueError(
                "Photo storage is unavailable. Please try again."
            ) from None
        return f"{self.url}/storage/v1/object/public/{self.bucket}/{name}"

    def valid_url(self, url):
        prefix = f"{self.url}/storage/v1/object/public/{self.bucket}/"
        return url.startswith(prefix) and bool(
            re.fullmatch(r"[a-f0-9]{32}\.webp", url[len(prefix) :])
        )


class CloudinaryPhotos:
    """Signed server-side image uploads; secrets never enter storefront code."""

    url = "https://res.cloudinary.com"

    def __init__(self, cloud_name, api_key, api_secret):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cloud_name):
            raise RuntimeError("Use the Cloudinary cloud name from your dashboard.")
        self.cloud_name, self.api_key, self.api_secret = cloud_name, api_key, api_secret

    def valid_url(self, url):
        prefix = f"{self.url}/{self.cloud_name}/image/upload/"
        return url.startswith(prefix) and bool(
            re.fullmatch(
                r"(?:v[0-9]+/)?growthly/products/[a-f0-9]{32}\.webp", url[len(prefix) :]
            )
        )

    def upload(self, name, content):
        import io
        import cloudinary.uploader
        from cloudinary.exceptions import Error
        from urllib3.exceptions import HTTPError as TransportError

        if not re.fullmatch(r"[a-f0-9]{32}\.webp", name):
            raise ValueError("Invalid photo name.")
        try:
            result = cloudinary.uploader.upload(
                io.BytesIO(content),
                cloud_name=self.cloud_name,
                api_key=self.api_key,
                api_secret=self.api_secret,
                secure=True,
                folder="growthly/products",
                public_id=name[:-5],
                resource_type="image",
                format="webp",
                overwrite=False,
                timeout=20,
            )
            url = result.get("secure_url", "")
            if not self.valid_url(url):
                raise ValueError("Unexpected image URL.")
            return url
        except (Error, TransportError, OSError, ValueError):
            raise ValueError(
                "Photo storage is unavailable. Please try again."
            ) from None
