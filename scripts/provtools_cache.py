"""Lightweight SHA-256 cache to avoid recomputing digests for unchanged files."""
from __future__ import annotations

import json
import hashlib
import os
import uuid
from pathlib import Path
from typing import Dict

_CACHE_PATH = Path(".prov_cache.json")
_CACHE_DATA: Dict[str, Dict[str, str]] = {}
_CACHE_LOADED = False


def _load_cache() -> None:
    global _CACHE_LOADED, _CACHE_DATA
    if _CACHE_LOADED:
        return
    if _CACHE_PATH.exists():
        try:
            _CACHE_DATA = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _CACHE_DATA = {}
    _CACHE_LOADED = True


def _persist_cache() -> None:
    if not _CACHE_LOADED:
        return
    tmp_name = f"{_CACHE_PATH.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    tmp_path = _CACHE_PATH.with_name(tmp_name)
    tmp_path.write_text(json.dumps(_CACHE_DATA, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(_CACHE_PATH)


def _meta(path: Path) -> str:
    stat = path.stat()
    mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
    return f"{stat.st_size}:{mtime_ns}"


def sha256_cached(path: Path) -> str:
    """Return the SHA-256 digest for *path*, caching results between invocations."""

    resolved = path.resolve()
    _load_cache()

    key = str(resolved)
    try:
        meta = _meta(resolved)
    except FileNotFoundError:
        raise

    record = _CACHE_DATA.get(key)
    if record and record.get("meta") == meta:
        return record["sha256"]

    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    hexdigest = digest.hexdigest()

    _CACHE_DATA[key] = {"meta": meta, "sha256": hexdigest}
    _persist_cache()
    return hexdigest
