"""Optional real PostgreSQL integration fixture, isolated from live services."""

import pytest


@pytest.fixture(scope="session")
def postgres_server(tmp_path_factory):
    pgserver = pytest.importorskip(
        "pgserver", reason="Install requirements-postgres-test.txt for PostgreSQL tests"
    )
    server = pgserver.get_server(
        tmp_path_factory.mktemp("postgres"), cleanup_mode="delete"
    )
    yield server
    server.cleanup()


@pytest.fixture
def postgres_url(request, monkeypatch):
    import uuid
    import psycopg
    from psycopg.conninfo import make_conninfo

    server = request.getfixturevalue("postgres_server")
    uri = server.get_uri()
    schema = "test_" + uuid.uuid4().hex
    monkeypatch.setenv("DATABASE_SCHEMA", schema)
    with psycopg.connect(uri, autocommit=True) as connection:
        connection.execute("CREATE SCHEMA " + schema)
    yield make_conninfo(uri, options="-c search_path=" + schema)
    with psycopg.connect(uri, autocommit=True) as connection:
        connection.execute("DROP SCHEMA " + schema + " CASCADE")
