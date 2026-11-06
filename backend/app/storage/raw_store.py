"""Write-once, content-addressed raw file store (M2).

Layout:  <data_dir>/raw/<source>/<sha[:2]>/<sha256>__<safe_filename>
Rules:
  * Bytes are streamed to <data_dir>/staging first (hashing + size limit on the way), then moved
    into place atomically. A crash leaves at most a staging temp file, never a half-written raw file.
  * Existing content is NEVER overwritten. Same hash -> reuse; different bytes at an existing
    path (impossible barring corruption) -> hard error.
  * Stored files are made read-only. Originals are never deleted by DataCore.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

CHUNK = 1024 * 1024
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class RawStoreError(Exception):
    pass


class EmptyFileError(RawStoreError):
    pass


class FileTooLargeError(RawStoreError):
    pass


def safe_filename(name: str) -> str:
    """Basename only, restricted charset - blocks path traversal and odd characters."""
    base = re.split(r"[\\/]", name or "")[-1].strip().strip(".")
    base = _SAFE.sub("_", base)[:150]
    return base or "unnamed"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class StoredFile:
    sha256: str
    size_bytes: int
    relative_path: str  # posix-style, relative to data_dir (portable Windows <-> Linux)
    absolute_path: Path
    newly_written: bool


class RawFileStore:
    def __init__(self, data_dir: Path, max_bytes: int):
        self.data_dir = Path(data_dir)
        self.raw_root = self.data_dir / "raw"
        self.staging = self.data_dir / "staging"
        self.max_bytes = max_bytes
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: str) -> Path:
        p = (self.data_dir / relative_path).resolve()
        if not p.is_relative_to(self.data_dir.resolve()):
            raise RawStoreError(f"Path escapes data directory: {relative_path}")
        return p

    def put(self, stream: BinaryIO, filename: str, source_key: str) -> StoredFile:
        tmp_fd, tmp_name = tempfile.mkstemp(dir=self.staging, prefix="incoming_", suffix=".part")
        tmp = Path(tmp_name)
        h = hashlib.sha256()
        size = 0
        try:
            with os.fdopen(tmp_fd, "wb") as out:
                for chunk in iter(lambda: stream.read(CHUNK), b""):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise FileTooLargeError(f"File exceeds limit of {self.max_bytes} bytes")
                    h.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if size == 0:
                raise EmptyFileError("File is empty")
            digest = h.hexdigest()
            rel = f"raw/{safe_filename(source_key)}/{digest[:2]}/{digest}__{safe_filename(filename)}"
            target = self.resolve(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Content address is the hash: reuse any existing copy regardless of its filename.
            for existing in sorted(target.parent.glob(f"{digest}__*")):
                if sha256_file(existing) != digest:
                    raise RawStoreError(f"Existing stored file does not match its name hash: {existing.name}")
                rel_existing = existing.resolve().relative_to(self.data_dir.resolve()).as_posix()
                return StoredFile(digest, size, rel_existing, existing, newly_written=False)
            os.replace(tmp, target)  # atomic on the same volume; target did not exist
            os.chmod(target, stat.S_IREAD)
            return StoredFile(digest, size, rel, target, newly_written=True)
        finally:
            if tmp.exists():
                tmp.unlink()
