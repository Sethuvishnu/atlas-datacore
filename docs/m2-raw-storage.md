# M2 - Source registry and raw file storage

**Registry** (`data_source_registry`): seeded by `scripts/seed_sources.py`. Coverage is `UNVERIFIED` and
reliability `UNASSESSED` until an operator checks a source and edits the row. Re-seeding never overwrites edits.

**Raw store**: `data/raw/<source>/<sha256[:2]>/<sha256>__<filename>`. Files are streamed to `data/staging`,
hashed, then moved into place atomically; stored files are read-only and never overwritten or deleted by DataCore.
The database blocks deleting `raw_data_files` rows and changing checksum/path/filename/size (migration 0002).

**Registration** (`scripts/register_file.py SOURCE PATH [--date]`): idempotent per (source, SHA-256).
Outcomes: new + usable (PENDING) | new + corrupt (kept as evidence, FAILED, import job records why) |
duplicate (no new row/job; heals the disk copy if it went missing) | rejected before storing (empty / over limit).
Integrity checks: ZIP structure + CRC, zip-bomb ratio/size/member limits, zip-slip member names, binary-in-CSV.

**Audit**: `scripts/verify_raw_store.py` reports DB rows with missing/corrupt files and files on disk with no row.

**Not in M2**: parsing any market data (M3).  Limits are configurable via `DATACORE_MAX_UPLOAD_BYTES` etc.
