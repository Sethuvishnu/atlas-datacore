"""Audit the raw store against the database.   python ../scripts/verify_raw_store.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config.settings import get_settings  # noqa: E402
from app.ingestion.raw_files import verify_store  # noqa: E402
from app.storage.database import session_scope  # noqa: E402
from app.storage.raw_store import RawFileStore  # noqa: E402

if __name__ == "__main__":
    st = get_settings()
    with session_scope() as s:
        rep = verify_store(s, RawFileStore(st.data_dir, st.max_upload_bytes))
    print(f"checked={rep.checked} missing={rep.missing} corrupt={rep.corrupt} orphans={rep.orphans}")
    sys.exit(0 if rep.ok else 1)
