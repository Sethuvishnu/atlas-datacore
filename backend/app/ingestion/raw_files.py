"""Register incoming files: preserve -> checksum -> validate -> record (M2).

No market data is parsed here. A registered file has import_status PENDING (ready for a parser),
or FAILED (preserved as evidence but unusable). Registration is idempotent per (source, SHA-256).
"""
from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.logging import get_logger
from app.ingestion.integrity import validate_file
from app.storage.models import DataSource, ImportJob, ImportStatus, RawDataFile
from app.storage.raw_store import RawFileStore, sha256_file


@dataclass
class RegisterResult:
    file: RawDataFile
    created: bool            # a new raw_data_files row was inserted
    duplicate: bool          # identical bytes already registered for this source
    restored_on_disk: bool   # DB row existed but the stored file was missing/corrupt and was re-stored
    problems: list[str] = field(default_factory=list)
    job: ImportJob | None = None

    @property
    def usable(self) -> bool:
        return self.file.import_status != ImportStatus.FAILED


def register_file(
    session: Session, store: RawFileStore, source: DataSource, stream: BinaryIO, filename: str, *,
    source_url: str | None = None, file_date: date | None = None, file_type: str | None = None,
    limits: dict | None = None,
) -> RegisterResult:
    log = get_logger("ingestion.raw_files")
    from app.config.settings import get_settings
    s = get_settings()
    limits = limits or dict(max_zip_uncompressed=s.max_zip_uncompressed_bytes,
                            max_zip_ratio=s.max_zip_ratio, max_zip_members=s.max_zip_members)

    stored = store.put(stream, filename, source.name)  # raises on empty / oversize; nothing recorded
    existing = session.scalar(select(RawDataFile).where(
        RawDataFile.source_id == source.id, RawDataFile.checksum == stored.sha256))

    if existing is not None:
        # Idempotent re-registration. Heal the disk copy if the registered file went missing.
        path = store.resolve(existing.storage_path)
        # newly_written means store.put had to create the file again, i.e. the registered copy was gone.
        restored = stored.newly_written or not path.exists()
        if restored:
            log.warning("raw_file_restored", file_id=existing.id, path=existing.storage_path)
            _restore_to(store, stored, existing.storage_path)
        elif sha256_file(path) != existing.checksum:
            raise RuntimeError(f"Stored file {existing.storage_path} is corrupt; refusing to overwrite. "
                               "Investigate manually.")
        log.info("raw_file_duplicate", file_id=existing.id, checksum=existing.checksum)
        return RegisterResult(existing, created=False, duplicate=True, restored_on_disk=restored)

    result = validate_file(stored.absolute_path, **limits)
    row = RawDataFile(
        filename=filename, source_id=source.id, source_url=source_url, file_date=file_date,
        file_type=file_type or result.detected_type, checksum=stored.sha256,
        storage_path=stored.relative_path, size_bytes=stored.size_bytes,
        import_status=ImportStatus.PENDING if result.ok else ImportStatus.FAILED,
    )
    session.add(row)
    session.flush()
    now = datetime.now(timezone.utc)
    job = ImportJob(
        source_id=source.id, file_id=row.id, completed_at=now,
        status=ImportStatus.SUCCEEDED if result.ok else ImportStatus.FAILED,
        error_summary=None if result.ok else "; ".join(result.problems),
    )
    session.add(job)
    session.flush()
    log.info("raw_file_registered", file_id=row.id, usable=result.ok, problems=result.problems,
             checksum=stored.sha256, size=stored.size_bytes)
    return RegisterResult(row, created=True, duplicate=False, restored_on_disk=False,
                          problems=result.problems, job=job)


def _restore_to(store: RawFileStore, stored, relative_path: str) -> None:
    """Put the just-verified bytes at the path the database already records."""
    target = store.resolve(relative_path)
    if target == stored.absolute_path:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if stored.newly_written:  # our own fresh copy under a different filename: move, leave no orphan
        os.replace(stored.absolute_path, target)
    else:
        shutil.copyfile(stored.absolute_path, target)
        os.chmod(target, stat.S_IREAD)


@dataclass
class VerifyReport:
    checked: int
    missing: list[str]
    corrupt: list[str]
    orphans: list[str]

    @property
    def ok(self) -> bool:
        return not (self.missing or self.corrupt)


def verify_store(session: Session, store: RawFileStore) -> VerifyReport:
    """Audit: every DB row has an intact file; report files on disk that no row references."""
    rows = session.scalars(select(RawDataFile)).all()
    missing, corrupt, known = [], [], set()
    for r in rows:
        p = store.resolve(r.storage_path)
        known.add(p)
        if not p.exists():
            missing.append(r.storage_path)
        elif sha256_file(p) != r.checksum:
            corrupt.append(r.storage_path)
    orphans = [str(p.relative_to(store.data_dir.resolve()).as_posix())
               for p in store.raw_root.resolve().rglob("*") if p.is_file() and p not in known]
    return VerifyReport(len(rows), sorted(missing), sorted(corrupt), sorted(orphans))
