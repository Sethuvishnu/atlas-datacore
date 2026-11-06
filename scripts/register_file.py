"""Register a downloaded/manual file.   python ../scripts/register_file.py SOURCE_NAME PATH [--date YYYY-MM-DD]
SOURCE_NAME e.g. NSE_CM_UDIFF_BHAVCOPY or MANUAL_UPLOAD. The original file is never modified or deleted."""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config.logging import configure_logging  # noqa: E402
from app.config.settings import get_settings  # noqa: E402
from app.ingestion.raw_files import register_file  # noqa: E402
from app.sources.registry import get_source  # noqa: E402
from app.storage.database import session_scope  # noqa: E402
from app.storage.raw_store import RawFileStore  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("path", type=Path)
    ap.add_argument("--date", type=date.fromisoformat, default=None, help="file date, if known")
    a = ap.parse_args()
    configure_logging()
    st = get_settings()
    store = RawFileStore(st.data_dir, st.max_upload_bytes)
    with session_scope() as s, open(a.path, "rb") as fh:
        r = register_file(s, store, get_source(s, a.source), fh, a.path.name, file_date=a.date)
        print(f"id={r.file.id} created={r.created} duplicate={r.duplicate} usable={r.usable} "
              f"status={r.file.import_status.value} sha256={r.file.checksum}")
        for p in r.problems:
            print("  PROBLEM:", p)
