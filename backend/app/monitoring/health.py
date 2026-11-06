"""Database / migration health checks (no data-quality claims are made here)."""
from sqlalchemy import Engine, inspect, text

from app.storage.database import Base
from app.storage import models  # noqa: F401


def check_database(engine: Engine) -> dict:
    result: dict = {"connected": False, "migration_revision": None,
                    "expected_tables_present": False, "missing_tables": [], "error": None}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            result["connected"] = True
            tables = set(inspect(conn).get_table_names())
            expected = set(Base.metadata.tables)
            result["missing_tables"] = sorted(expected - tables)
            result["expected_tables_present"] = not result["missing_tables"]
            if "alembic_version" in tables:
                result["migration_revision"] = conn.execute(
                    text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:  # report, never hide
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result
