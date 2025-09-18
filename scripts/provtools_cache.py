"""Lightweight SHA-256 cache with TOCTOU protection for provenance hashing."""
from __future__ import annotations

import errno
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Dict

_CACHE_PATH = Path(".prov_cache.json")
_CACHE_DATA: Dict[str, Dict[str, str]] = {}
_CACHE_LOADED = False


class HashRaceError(RuntimeError):
    """Raised when a file changes while its digest is being computed."""


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


def _meta_from_stat(stat: os.stat_result) -> str:
    mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
    dev = getattr(stat, "st_dev", 0)
    ino = getattr(stat, "st_ino", 0)
    return f"{dev}:{ino}:{stat.st_size}:{mtime_ns}"


def sha256_cached(path: Path) -> str:
    """Return the SHA-256 digest for *path*, caching results between invocations."""

    resolved = path.resolve()
    _load_cache()

    key = str(resolved)
    try:
        stat_pre = os.stat(resolved, follow_symlinks=False)
    except FileNotFoundError:
        raise

    meta_pre = _meta_from_stat(stat_pre)
    record = _CACHE_DATA.get(key)
    if record and record.get("meta") == meta_pre:
        return record["sha256"]

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(resolved, flags)
    except OSError as exc:
        if exc.errno == getattr(errno, "ELOOP", None):
            raise
        fd = os.open(resolved, os.O_RDONLY)

    try:
        st_start = os.fstat(fd)
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            digest.update(chunk)
        st_end = os.fstat(fd)
    finally:
        os.close(fd)

    if _meta_from_stat(st_start) != _meta_from_stat(st_end):
        raise HashRaceError(str(resolved))
    if _meta_from_stat(st_start) != meta_pre:
        raise HashRaceError(str(resolved))

    hexdigest = digest.hexdigest()
    _CACHE_DATA[key] = {"meta": _meta_from_stat(st_start), "sha256": hexdigest}
    _persist_cache()
    return hexdigest
