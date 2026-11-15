import io
import secrets
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
import pytest
from werkzeug.security import generate_password_hash
import app as application
import persistence


def test_vercel_refuses_ephemeral_database(monkeypatch, tmp_path):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SITE_URL", "https://test.example")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        application.create_app(
            {
                "TESTING": True,
                "DATA_DIR": str(tmp_path / "no-files"),
                "DATABASE_URL": "",
                "SECRET_KEY": None,
            }
        )
    assert not (tmp_path / "no-files").exists()


def test_remote_photos_and_database_survive_cold_start(
    monkeypatch, tmp_path, postgres_url
):
    # Real local PostgreSQL stands in for the hosted DB; HTTP transport is stubbed.
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SITE_URL", "https://test.example")
    monkeypatch.setattr(
        application,
        "connect_database",
        lambda url, path: persistence.PostgresDatabase(postgres_url),
    )
    uploads = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b"{}"

    def upload(request, timeout):
        uploads.append(request)
        return Response()

    monkeypatch.setattr(persistence, "urlopen", upload)
    config = {
        "TESTING": True,
        "STORE": {"categories": ["Bags"]},
        "DATABASE_URL": "postgresql://test-only",
        "SUPABASE_URL": "https://test-project.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": secrets.token_urlsafe(32),
        "SECRET_KEY": secrets.token_urlsafe(48),
        "DATA_DIR": str(tmp_path / "no-files"),
        "SESSION_COOKIE_SECURE": False,
    }
    app = application.create_app(config)
    with app.app_context():
        app.db().execute(
            "INSERT INTO owner VALUES(1,?,?)",
            ("owner", generate_password_hash("test-password")),
        )
    client = app.test_client()

    def post(url, body):
        return client.post(
            "/api/" + url,
            json=body,
            headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]},
        )

    assert (
        post("login", {"username": "owner", "password": "test-password"}).status_code
        == 200
    )
    photo = io.BytesIO()
    Image.new("RGB", (2000, 1200), "pink").save(photo, "JPEG")
    photo.seek(0)
    response = client.post(
        "/api/upload",
        data={"photo": (photo, "phone.jpg")},
        headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]},
    )
    assert response.status_code == 200
    url = response.json["url"]
    assert url.startswith(
        config["SUPABASE_URL"] + "/storage/v1/object/public/product-images/"
    )
    assert len(uploads) == 1
    assert (
        uploads[0].get_header("Authorization")
        == "Bearer " + config["SUPABASE_SERVICE_ROLE_KEY"]
    )
    assert Image.open(io.BytesIO(uploads[0].data)).width == 1600
    assert config["SUPABASE_SERVICE_ROLE_KEY"] not in response.get_data(as_text=True)
    product = {
        "name": "Persistent bag",
        "category": "Bags",
        "price": 1200000,
        "description": "A real piece",
        "images": [url],
        "variants": [{"id": "one", "stock": 2, "size": "One size", "colour": "Brown"}],
        "published": True,
    }
    assert post("products", product).status_code == 200
    restarted = application.create_app(config)
    newclient = restarted.test_client()
    assert newclient.get("/api/products").json[0]["images"] == [url]
    cookie = client.get_cookie(app.config["SESSION_COOKIE_NAME"])
    newclient.set_cookie(app.config["SESSION_COOKIE_NAME"], cookie.value)
    assert newclient.get("/api/orders").status_code == 200  # stable signing key
    assert (
        config["SUPABASE_URL"] in newclient.get("/").headers["Content-Security-Policy"]
    )
    assert not (tmp_path / "no-files").exists()  # no reliance on Vercel local files
    product["images"] = ["https://untrusted.invalid/image.webp"]
    assert post("products", product).status_code == 400


def test_remote_storage_errors_do_not_expose_credentials(monkeypatch):
    from urllib.error import HTTPError

    def fail(request, timeout):
        raise HTTPError(request.full_url, 403, "secret-provider-detail", None, None)

    monkeypatch.setattr(persistence, "urlopen", fail)
    photos = persistence.SupabasePhotos(
        "https://test-project.supabase.co", "private-test-key"
    )
    with pytest.raises(ValueError, match="Photo storage is unavailable") as error:
        photos.upload("a" * 32 + ".webp", b"contents")
    assert "private-test-key" not in str(error.value)


@pytest.mark.parametrize("photo_provider", ["supabase", "cloudinary"])
def test_serverless_provider_selection(
    monkeypatch, tmp_path, postgres_url, photo_provider
):
    import cloudinary.uploader

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SITE_URL", "https://test.example")
    monkeypatch.setattr(
        application,
        "connect_database",
        lambda url, path: persistence.PostgresDatabase(postgres_url),
    )
    config = {
        "TESTING": True,
        "STORE": {"categories": ["Bags"]},
        "DATABASE_URL": "postgresql://test-only",
        "SECRET_KEY": secrets.token_urlsafe(48),
        "DATA_DIR": str(tmp_path / "no-files"),
        "SUPABASE_URL": "",
        "SUPABASE_SERVICE_ROLE_KEY": "",
        "CLOUDINARY_CLOUD_NAME": "",
        "CLOUDINARY_API_KEY": "",
        "CLOUDINARY_API_SECRET": "",
        "SESSION_COOKIE_SECURE": False,
    }
    if photo_provider == "cloudinary":
        config.update(
            CLOUDINARY_CLOUD_NAME="test-cloud",
            CLOUDINARY_API_KEY="test-key",
            CLOUDINARY_API_SECRET="test-secret",
        )
        requests = []

        def upload(content, **options):
            requests.append(options)
            assert Image.open(content).format == "WEBP"
            return {
                "secure_url": f"https://res.cloudinary.com/test-cloud/image/upload/v123/growthly/products/{options['public_id']}.webp"
            }

        monkeypatch.setattr(cloudinary.uploader, "upload", upload)
    else:
        config.update(
            SUPABASE_URL="https://test-project.supabase.co",
            SUPABASE_SERVICE_ROLE_KEY="test-key",
        )

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return b"{}"

        monkeypatch.setattr(persistence, "urlopen", lambda *args, **kw: Response())
    app = application.create_app(config)
    with app.app_context():
        app.db().execute(
            "INSERT INTO owner VALUES(1,?,?)",
            ("owner", generate_password_hash("test-password")),
        )
    client = app.test_client()

    def post(url, body):
        return client.post(
            "/api/" + url,
            json=body,
            headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]},
        )

    assert (
        post("login", {"username": "owner", "password": "test-password"}).status_code
        == 200
    )
    photo = io.BytesIO()
    Image.new("RGB", (100, 100), "pink").save(photo, "PNG")
    photo.seek(0)
    response = client.post(
        "/api/upload",
        data={"photo": (photo, "photo.png")},
        headers={"X-CSRF-Token": client.get("/api/session").json["csrf"]},
    )
    assert response.status_code == 200
    url = response.json["url"]
    product = {
        "name": "Persistent piece",
        "category": "Bags",
        "price": 1200000,
        "images": [url],
        "variants": [{"id": "one", "stock": 1}],
        "published": True,
    }
    assert post("products", product).status_code == 200
    restarted = application.create_app(config)
    assert restarted.test_client().get("/api/products").json[0]["images"] == [url]
    assert not (tmp_path / "no-files").exists()
    if photo_provider == "cloudinary":
        assert requests[0]["api_secret"] == "test-secret"
        assert "test-secret" not in response.get_data(as_text=True)
        assert requests[0]["overwrite"] is False
        assert (
            "https://res.cloudinary.com"
            in client.get("/").headers["Content-Security-Policy"]
        )


def test_cloudinary_rejects_untrusted_urls_and_hides_errors(monkeypatch):
    import cloudinary.uploader
    from cloudinary.exceptions import Error

    photos = persistence.CloudinaryPhotos("test-cloud", "test-key", "test-secret")
    assert not photos.valid_url(
        "https://res.cloudinary.com/another-cloud/image/upload/v1/growthly/products/"
        + "a" * 32
        + ".webp"
    )
    assert not photos.valid_url("https://untrusted.invalid/a.webp")

    def fail(*args, **kw):
        raise Error("provider response with test-secret")

    monkeypatch.setattr(cloudinary.uploader, "upload", fail)
    with pytest.raises(ValueError, match="Photo storage is unavailable") as error:
        photos.upload("a" * 32 + ".webp", b"image")
    assert "test-secret" not in str(error.value)
