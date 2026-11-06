"""Seed the data source registry (idempotent).  Run from backend/:  python ../scripts/seed_sources.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config.logging import configure_logging  # noqa: E402
from app.sources.registry import seed_sources  # noqa: E402
from app.storage.database import session_scope  # noqa: E402

if __name__ == "__main__":
    configure_logging()
    with session_scope() as s:
        for src in seed_sources(s):
            print(f"{src.id:>3}  {src.name:<28} coverage={src.historical_coverage}")
