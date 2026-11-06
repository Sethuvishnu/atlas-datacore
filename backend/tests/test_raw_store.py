import hashlib
import io
import os
import stat

import pytest

from app.storage.raw_store import (EmptyFileError, FileTooLargeError, RawStoreError, safe_filename)


def test_put_hashes_and_content_addresses(store):
    data = b"a,b\n1,2\n"
    sf = store.put(io.BytesIO(data), "x.csv", "SRC")
    assert sf.sha256 == hashlib.sha256(data).hexdigest()
    assert sf.size_bytes == len(data)
    assert sf.relative_path == f"raw/SRC/{sf.sha256[:2]}/{sf.sha256}__x.csv"
    assert sf.absolute_path.read_bytes() == data
    assert sf.newly_written


def test_stored_file_is_read_only(store):
    sf = store.put(io.BytesIO(b"abc"), "x.csv", "SRC")
    assert not (sf.absolute_path.stat().st_mode & stat.S_IWUSR)


def test_same_bytes_twice_is_single_file_not_rewritten(store):
    a = store.put(io.BytesIO(b"same"), "x.csv", "SRC")
    b = store.put(io.BytesIO(b"same"), "x.csv", "SRC")
    assert a.absolute_path == b.absolute_path and not b.newly_written
    assert len([p for p in store.raw_root.rglob("*") if p.is_file()]) == 1


def test_existing_file_with_wrong_content_is_never_overwritten(store):
    sf = store.put(io.BytesIO(b"original"), "x.csv", "SRC")
    os.chmod(sf.absolute_path, stat.S_IWUSR | stat.S_IREAD)
    sf.absolute_path.write_bytes(b"tampered")
    with pytest.raises(RawStoreError):
        store.put(io.BytesIO(b"original"), "x.csv", "SRC")
    assert sf.absolute_path.read_bytes() == b"tampered"  # untouched, error surfaced


@pytest.mark.parametrize("evil", ["../../evil.csv", "..\\..\\evil.csv", "/etc/passwd", "C:\\x\\y.csv", "a b$%.csv"])
def test_filename_cannot_escape_store(store, evil):
    sf = store.put(io.BytesIO(b"x"), evil, "SRC")
    assert sf.absolute_path.resolve().is_relative_to(store.raw_root.resolve())
    assert "/" not in safe_filename(evil) and "\\" not in safe_filename(evil)


def test_empty_file_rejected_and_staging_clean(store):
    with pytest.raises(EmptyFileError):
        store.put(io.BytesIO(b""), "x.csv", "SRC")
    assert list(store.staging.iterdir()) == []


def test_oversize_rejected_and_staging_clean(store):
    with pytest.raises(FileTooLargeError):
        store.put(io.BytesIO(b"x" * (1024 * 1024 + 1)), "big.csv", "SRC")
    assert list(store.staging.iterdir()) == []
    assert not [p for p in store.raw_root.rglob("*") if p.is_file()]


def test_interrupted_stream_leaves_no_partial_raw_file(store):
    class Boom(io.BytesIO):
        calls = 0
        def read(self, n=-1):
            Boom.calls += 1
            if Boom.calls == 2:
                raise IOError("connection dropped")
            return super().read(n)
    with pytest.raises(IOError):
        store.put(Boom(b"x" * (3 * 1024 * 1024)), "x.csv", "SRC")
    assert list(store.staging.iterdir()) == []
    assert not [p for p in store.raw_root.rglob("*") if p.is_file()]
