"""File hashes used by the Nexus API.

- oshash: OpenSubtitles-style hash (legacy /v1/subtitle/search/ file_hash).
- sha256_endpoints: SHA256 over first+last 64KB + file size. Used as file_hash_sha256
  on /v1/ai/subtitle-request/ for stable cross-run identification.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 65536


def _read_endpoints(path: Path) -> tuple[bytes, bytes, int]:
    size = path.stat().st_size
    with path.open("rb") as f:
        head = f.read(CHUNK)
        if size > CHUNK:
            f.seek(max(size - CHUNK, 0))
            tail = f.read(CHUNK)
        else:
            tail = b""
    return head, tail, size


def oshash(path: str | Path) -> str:
    """OpenSubtitles hash: 64-bit sum of size + 8-byte words from first/last 64KB."""
    p = Path(path)
    head, tail, size = _read_endpoints(p)
    h = size
    mask = (1 << 64) - 1
    for buf in (head, tail):
        for i in range(0, len(buf) - 7, 8):
            h = (h + int.from_bytes(buf[i:i + 8], "little")) & mask
    return f"{h:016x}"


def sha256_endpoints(path: str | Path) -> str:
    """SHA256 of head+tail+size, matching nexus_utils.get_file_hash_sha256."""
    p = Path(path)
    head, tail, size = _read_endpoints(p)
    digest = hashlib.sha256()
    digest.update(head)
    digest.update(tail)
    digest.update(str(size).encode("utf-8"))
    return digest.hexdigest()
