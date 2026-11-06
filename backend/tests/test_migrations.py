from alembic import command
from sqlalchemy import create_engine, inspect

from tests.conftest import TEST_DB_URL, alembic_cfg, reset_schema


def test_downgrade_then_upgrade_roundtrip():
    """Migrations are reversible and re-appliable on a clean schema."""
    reset_schema(TEST_DB_URL)
    cfg = alembic_cfg(TEST_DB_URL)
    command.upgrade(cfg, "head")
    eng = create_engine(TEST_DB_URL)
    assert "daily_prices" in inspect(eng).get_table_names()
    command.downgrade(cfg, "base")
    assert "daily_prices" not in set(inspect(eng).get_table_names())
    command.upgrade(cfg, "head")
    assert "daily_prices" in inspect(eng).get_table_names()
    eng.dispose()
