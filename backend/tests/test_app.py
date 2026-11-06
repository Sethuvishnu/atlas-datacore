import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.api.deps import get_db_engine
from app.config.settings import Settings
from app.main import create_app
from tests.conftest import TEST_DB_URL


@pytest.fixture()
def client(engine):
    app = create_app()
    app.dependency_overrides[get_db_engine] = lambda: engine
    with TestClient(app) as c:
        yield c


def test_health_ok_with_migrated_db(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"]["connected"] is True
    assert body["database"]["migration_revision"] == "0001"
    assert body["database"]["missing_tables"] == []


def test_health_degraded_when_database_unreachable():
    bad = create_engine("postgresql+psycopg://nobody:nope@localhost:1/none", connect_args={"connect_timeout": 1})
    app = create_app()
    app.dependency_overrides[get_db_engine] = lambda: bad
    with TestClient(app) as c:
        r = c.get("/api/v1/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"
    assert r.json()["database"]["connected"] is False
    assert r.json()["database"]["error"]


def test_health_degraded_when_unmigrated(engine):
    # A fresh empty database must be reported as degraded, not healthy.
    import subprocess
    from sqlalchemy import text
    admin = create_engine(TEST_DB_URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS datacore_empty"))
        c.execute(text("CREATE DATABASE datacore_empty"))
    empty = create_engine(TEST_DB_URL.rsplit("/", 1)[0] + "/datacore_empty")
    app = create_app()
    app.dependency_overrides[get_db_engine] = lambda: empty
    with TestClient(app) as c:
        r = c.get("/api/v1/health")
    empty.dispose()
    assert r.status_code == 503
    assert "securities" in r.json()["database"]["missing_tables"]


def test_settings_read_environment(monkeypatch):
    monkeypatch.setenv("DATACORE_DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("DATACORE_ENVIRONMENT", "production")
    s = Settings()
    assert s.database_url.endswith("@h:5432/d")
    assert s.is_local is False
