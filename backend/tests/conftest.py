"""Tests run against a REAL PostgreSQL database (datacore_test), migrated via Alembic."""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

TEST_DB_URL = os.environ.get(
    "DATACORE_TEST_DATABASE_URL",
    "postgresql+psycopg://datacore:datacore@localhost:5432/datacore_test",
)
BACKEND = Path(__file__).resolve().parents[1]


def alembic_cfg(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def reset_schema(url: str) -> None:
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    eng.dispose()


@pytest.fixture(scope="session")
def engine():
    reset_schema(TEST_DB_URL)
    command.upgrade(alembic_cfg(TEST_DB_URL), "head")
    eng = create_engine(TEST_DB_URL)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    """Each test runs in a transaction that is rolled back (no cross-test leakage)."""
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint")
    yield s
    s.close()
    trans.rollback()
    conn.close()


@pytest.fixture()
def source(session):
    from app.storage.models import DataSource
    src = DataSource(name="test-source", source_type="MANUAL_UPLOAD")
    session.add(src)
    session.flush()
    return src


@pytest.fixture()
def security(session):
    from app.storage.models import Security
    sec = Security(canonical_security_id="SEC-TEST-1", isin="INE000A01010",
                   company_name="Test Ltd", exchange="NSE", segment="EQUITY")
    session.add(sec)
    session.flush()
    return sec


@pytest.fixture()
def store(tmp_path):
    from app.storage.raw_store import RawFileStore
    return RawFileStore(tmp_path / "data", max_bytes=1024 * 1024)
