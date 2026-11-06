"""File integrity validation (no parsing of market data - that is M3)."""
from __future__ import annotations

import posixpath
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IntegrityResult:
    ok: bool
    detected_type: str  # "zip" | "csv" | "unknown"
    problems: list[str] = field(default_factory=list)


def _bad_member_name(name: str) -> bool:
    norm = posixpath.normpath(name.replace("\\", "/"))
    return norm.startswith("/") or norm.startswith("..") or "/../" in f"/{norm}/" or (len(name) > 1 and name[1] == ":")


def validate_file(path: Path, *, max_zip_uncompressed: int, max_zip_ratio: int, max_zip_members: int) -> IntegrityResult:
    suffix = path.suffix.lower()
    with open(path, "rb") as f:
        head = f.read(8192)

    if zipfile.is_zipfile(path) or suffix == ".zip":
        res = IntegrityResult(ok=True, detected_type="zip")
        if not zipfile.is_zipfile(path):
            res.ok = False
            res.problems.append("Not a valid ZIP archive (bad or truncated structure)")
            return res
        try:
            with zipfile.ZipFile(path) as zf:
                infos = zf.infolist()
                if not infos:
                    res.problems.append("ZIP archive contains no files")
                if len(infos) > max_zip_members:
                    res.problems.append(f"ZIP has {len(infos)} members (limit {max_zip_members})")
                total = sum(i.file_size for i in infos)
                if total > max_zip_uncompressed:
                    res.problems.append(f"ZIP expands to {total} bytes (limit {max_zip_uncompressed})")
                compressed = max(path.stat().st_size, 1)
                if total / compressed > max_zip_ratio:
                    res.problems.append(f"ZIP compression ratio {total // compressed}x exceeds {max_zip_ratio}x (possible zip bomb)")
                bad = [i.filename for i in infos if _bad_member_name(i.filename)]
                if bad:
                    res.problems.append(f"ZIP contains unsafe member paths: {bad[:3]}")
                if not res.problems:  # only CRC-test when the archive is otherwise safe to read
                    broken = zf.testzip()
                    if broken:
                        res.problems.append(f"ZIP member failed CRC check: {broken}")
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            res.problems.append(f"ZIP could not be read: {exc}")
        res.ok = not res.problems
        return res

    if b"\x00" in head:
        return IntegrityResult(False, "unknown", ["Binary content (NUL bytes) in a file that is not a ZIP"])
    if suffix in {".csv", ".txt"}:
        try:
            head.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                head.decode("latin-1")
            except UnicodeDecodeError:
                return IntegrityResult(False, "csv", ["Text is not decodable"])
        return IntegrityResult(True, "csv")
    return IntegrityResult(True, "unknown", [])
