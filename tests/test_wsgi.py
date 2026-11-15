"""Check the real Gunicorn entrypoint, not only Flask's in-process client."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError


def test_wsgi_entrypoint(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(
        os.environ,
        DATA_DIR=str(tmp_path / "data"),
        APP_ENV="development",
        VERCEL="0",
        DATABASE_URL="",
        STORE_CONFIG_PATH=str(
            Path(__file__).resolve().parents[1] / "profiles/default.json"
        ),
        SECRET_KEY="isolated-wsgi-test-key-not-a-production-secret",
        CLOUDINARY_CLOUD_NAME="",
        CLOUDINARY_API_KEY="",
        CLOUDINARY_API_SECRET="",
        SUPABASE_URL="",
        SUPABASE_SERVICE_ROLE_KEY="",
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "gunicorn",
            "app:app",
            "--bind",
            f"127.0.0.1:{port}",
            "--workers",
            "1",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                with urlopen(
                    f"http://127.0.0.1:{port}/api/store", timeout=2
                ) as response:
                    config = json.load(response)
                break
            except URLError:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise AssertionError("Gunicorn failed to start")
                time.sleep(0.1)
        assert config["currency"] == "NGN"
        assert "SECRET_KEY" not in config
        for route in ["/", "/shop", "/static/app.js", "/store-theme.css"]:
            with urlopen(f"http://127.0.0.1:{port}" + route, timeout=2) as response:
                assert response.status == 200
    finally:
        process.terminate()
        process.communicate(timeout=10)
