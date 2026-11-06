import io
import os
import stat
import zipfile

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.ingestion.raw_files import register_file, verify_store
from app.sources.registry import get_source, seed_sources
from app.storage.models import ImportJob, ImportStatus, RawDataFile
from app.storage.raw_store import EmptyFileError, FileTooLargeError

LIMITS = dict(max_zip_uncompressed=10_000_000, max_zip_ratio=100, max_zip_members=50)


@pytest.fixture()
def src(session):
    seed_sources(session)
    return get_source(session, "MANUAL_UPLOAD")


def make_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in members.items():
            z.writestr(n, b)
    return buf.getvalue()


def reg(session, store, src, data, name="f.csv", **kw):
    return register_file(session, store, src, io.BytesIO(data), name, limits=LIMITS, **kw)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_register_valid_csv(session, store, src):
    r = reg(session, store, src, b"SYMBOL,CLOSE\nABC,10\n")
    assert r.created and not r.duplicate and r.usable
    assert r.file.import_status == ImportStatus.PENDING
    assert r.file.file_type == "csv" and r.file.size_bytes == 20
    assert len(r.file.checksum) == 64
    assert store.resolve(r.file.storage_path).exists()
    assert r.job.status == ImportStatus.SUCCEEDED and r.job.rows_processed == 0


def test_reimport_same_file_is_idempotent(session, store, src):
    a = reg(session, store, src, b"SYMBOL,CLOSE\nABC,10\n")
    b = reg(session, store, src, b"SYMBOL,CLOSE\nABC,10\n")
    assert b.duplicate and not b.created and b.file.id == a.file.id
    assert count(session, RawDataFile) == 1
    assert count(session, ImportJob) == 1  # no phantom job for a no-op


def test_same_bytes_different_filename_still_duplicate(session, store, src):
    a = reg(session, store, src, b"x,y\n1,2\n", name="one.csv")
    b = reg(session, store, src, b"x,y\n1,2\n", name="two.csv")
    assert b.duplicate and b.file.id == a.file.id and count(session, RawDataFile) == 1


def test_same_bytes_from_different_sources_are_separate_records(session, store, src):
    other = get_source(session, "NSE_CM_SECURITY_FILE")
    a = reg(session, store, src, b"x,y\n1,2\n")
    b = reg(session, store, other, b"x,y\n1,2\n")
    assert a.file.id != b.file.id


def test_empty_and_oversize_rejected_and_nothing_recorded(session, store, src):
    with pytest.raises(EmptyFileError):
        reg(session, store, src, b"")
    with pytest.raises(FileTooLargeError):
        reg(session, store, src, b"x" * (1024 * 1024 + 1))
    assert count(session, RawDataFile) == 0 and count(session, ImportJob) == 0


def test_valid_zip_accepted(session, store, src):
    r = reg(session, store, src, make_zip({"bhav.csv": b"a,b\n1,2\n"}), name="bhav.zip")
    assert r.usable and r.file.file_type == "zip"


def test_corrupt_zip_preserved_but_marked_failed(session, store, src):
    good = make_zip({"bhav.csv": b"a,b\n" * 1000})
    r = reg(session, store, src, good[: len(good) // 2], name="bhav.zip")
    assert not r.usable and r.file.import_status == ImportStatus.FAILED
    assert r.job.status == ImportStatus.FAILED and r.job.error_summary
    assert store.resolve(r.file.storage_path).exists()  # evidence kept


def test_zip_bomb_flagged(session, store, src):
    bomb = make_zip({"zeros.csv": b"0" * 5_000_000})
    r = reg(session, store, src, bomb, name="bomb.zip")
    assert not r.usable and any("zip bomb" in p for p in r.problems)


def test_zip_slip_member_flagged(session, store, src):
    r = reg(session, store, src, make_zip({"../../evil.csv": b"a,b\n1,2\n"}), name="slip.zip")
    assert not r.usable and any("unsafe member paths" in p for p in r.problems)


def test_binary_garbage_named_csv_flagged(session, store, src):
    r = reg(session, store, src, b"\x00\x01\x02binary", name="fake.csv")
    assert not r.usable


def test_failed_file_reupload_is_still_idempotent(session, store, src):
    data = make_zip({"a.csv": b"x"})[:20]
    a = reg(session, store, src, data, name="c.zip")
    b = reg(session, store, src, data, name="c.zip")
    assert b.duplicate and b.file.id == a.file.id and count(session, ImportJob) == 1


def test_recovery_file_on_disk_but_no_db_row(session, store, src):
    """Crash after the file was stored but before the DB commit: re-registration just works."""
    store.put(io.BytesIO(b"x,y\n1,2\n"), "f.csv", src.name)
    r = reg(session, store, src, b"x,y\n1,2\n")
    assert r.created and r.usable


def test_recovery_db_row_but_file_missing_is_restored(session, store, src):
    a = reg(session, store, src, b"x,y\n1,2\n")
    p = store.resolve(a.file.storage_path)
    os.chmod(p, stat.S_IWUSR | stat.S_IREAD)
    p.unlink()
    assert verify_store(session, store).missing == [a.file.storage_path]
    b = reg(session, store, src, b"x,y\n1,2\n")
    assert b.duplicate and b.restored_on_disk and p.exists()
    assert verify_store(session, store).ok


def test_verify_store_detects_corruption_and_orphans(session, store, src):
    a = reg(session, store, src, b"x,y\n1,2\n")
    p = store.resolve(a.file.storage_path)
    os.chmod(p, stat.S_IWUSR | stat.S_IREAD)
    p.write_bytes(b"tampered")
    store.put(io.BytesIO(b"not registered"), "orphan.csv", "OTHER")
    rep = verify_store(session, store)
    assert rep.corrupt == [a.file.storage_path] and len(rep.orphans) == 1 and not rep.ok


def test_corrupt_disk_copy_is_not_silently_overwritten(session, store, src):
    a = reg(session, store, src, b"x,y\n1,2\n")
    p = store.resolve(a.file.storage_path)
    os.chmod(p, stat.S_IWUSR | stat.S_IREAD)
    p.write_bytes(b"tampered")
    with pytest.raises(Exception):
        reg(session, store, src, b"x,y\n1,2\n")
    assert p.read_bytes() == b"tampered"


def test_db_blocks_delete_and_identity_changes_but_allows_status(session, store, src):
    r = reg(session, store, src, b"x,y\n1,2\n").file
    with pytest.raises(DBAPIError):
        with session.begin_nested():
            session.query(RawDataFile).filter_by(id=r.id).delete()
    with pytest.raises(DBAPIError):
        with session.begin_nested():
            r.checksum = "b" * 64
            session.flush()
    session.expire_all()
    r = session.get(RawDataFile, r.id)
    r.import_status = ImportStatus.SUCCEEDED
    session.flush()
    assert session.get(RawDataFile, r.id).import_status == ImportStatus.SUCCEEDED


def test_different_filename_same_bytes_leaves_one_file_on_disk(session, store, src):
    reg(session, store, src, b"x,y\n1,2\n", name="one.csv")
    reg(session, store, src, b"x,y\n1,2\n", name="two.csv")
    assert len([p for p in store.raw_root.rglob("*") if p.is_file()]) == 1


def test_restore_under_different_filename_leaves_no_orphan(session, store, src):
    a = reg(session, store, src, b"x,y\n1,2\n", name="one.csv")
    p = store.resolve(a.file.storage_path)
    os.chmod(p, stat.S_IWUSR | stat.S_IREAD)
    p.unlink()
    b = reg(session, store, src, b"x,y\n1,2\n", name="renamed.csv")
    assert b.restored_on_disk and p.exists()
    rep = verify_store(session, store)
    assert rep.ok and rep.orphans == []
