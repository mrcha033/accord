"""Incremental documentation index builder with snapshot support."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

from scripts import provtools


UTC = dt.timezone.utc


def _git_changed(base: Path, since: str) -> List[Path]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{since}..HEAD"],
            cwd=base,
            capture_output=True,
            text=True,
            check=True,
        )
        paths = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]
        return [base / p for p in paths if p.suffix.lower() == ".md" and (base / p).exists()]
    except Exception:
        return []


def _all_markdown(base: Path) -> List[Path]:
    ignored = {".git", "venv", "indexes", "__pycache__"}
    files: List[Path] = []
    for path in base.rglob("*.md"):
        if any(part in ignored for part in path.parts):
            continue
        files.append(path)
    return files


def _first_heading(lines: Iterable[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    for line in lines:
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _entry_for(path: Path, base: Path) -> Dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    heading = _first_heading(lines)
    summary = heading or path.stem.replace("-", " ")
    tokens = {token.lower().strip(".,!?") for token in summary.split() if len(token) > 3}
    topics = sorted(tokens)[:5]
    return {
        "path": str(path.relative_to(base).as_posix()),
        "text": summary,
        "topics": topics,
    }


def _load_index(index_path: Path) -> Dict[str, Dict[str, object]]:
    entries: Dict[str, Dict[str, object]] = {}
    if not index_path.exists():
        return entries
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        entries[str(data["path"])] = data
    return entries


def _write_index(index_path: Path, entries: Dict[str, Dict[str, object]]) -> str:
    lines = [json.dumps(entries[key], ensure_ascii=False) for key in sorted(entries.keys())]
    content = "\n".join(lines) + ("\n" if lines else "")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(content, encoding="utf-8")
    return content


def _provenance_markdown(rel_snapshot: str) -> str:
    date = dt.datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    header = (
        "<!--\n"
        "provenance:\n"
        "  _type: \"https://in-toto.io/Statement/v0.1\"\n"
        "  subject:\n"
        f"    - name: \"{rel_snapshot}\"\n"
        "      digest: {}\n"
        "  predicateType: \"https://accord.ai/schemas/index@v1\"\n"
        "  predicate:\n"
        "    produced_by:\n"
        "      agent_id: \"AGENT-ENG01\"\n"
        "      agent_role: \"Index Builder\"\n"
        "    process:\n"
        "      toolchain:\n"
        "        - name: \"index_build\"\n"
        "          version: \"0.1\"\n"
        f"    materials:\n      - name: \"docs/index.jsonl\"\n        digest: {{}}\n"
        "-->\n"
    )
    body = f"# Index Snapshot\n\n- Generated: {date}\n\n"
    return header + body


def _dsse_build(markdown: Path, priv: Path, dsse: Path, base: Path) -> None:
    namespace = argparse.Namespace(
        file=str(markdown),
        priv=str(priv),
        out=str(dsse),
        base=str(base),
        keyid="",
    )
    rc = provtools.cmd_build(namespace)
    if rc != 0:
        raise SystemExit(f"DSSE build failed for {markdown}")


def _create_snapshot(base: Path, content: str, snapshot: str, priv_key: Path) -> None:
    snapshot_dir = base / "indexes" / snapshot
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file = snapshot_dir / "index.jsonl"
    snapshot_file.write_text(content, encoding="utf-8")
    prov_markdown = snapshot_dir / "index.prov.md"
    rel_snapshot = f"indexes/{snapshot}/index.jsonl"
    prov_markdown.write_text(_provenance_markdown(rel_snapshot), encoding="utf-8")
    dsse_path = snapshot_dir / "index.dsse"
    _dsse_build(prov_markdown, priv_key, dsse_path, base)
    latest = base / "indexes/latest.json"
    latest.write_text(json.dumps({"snapshot": rel_snapshot}, ensure_ascii=False, indent=2), encoding="utf-8")


def update_index(
    base: Path,
    changed_files: Iterable[Path],
    *,
    remove_missing: bool = True,
) -> Dict[str, Dict[str, object]]:
    index_path = base / "docs/index.jsonl"
    entries = _load_index(index_path)
    for file_path in changed_files:
        rel = str(file_path.relative_to(base).as_posix())
        if file_path.exists():
            entries[rel] = _entry_for(file_path, base)
        elif remove_missing and rel in entries:
            entries.pop(rel)
    _write_index(index_path, entries)
    return entries


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=".", help="Project base directory")
    parser.add_argument("--since", help="Git commit-ish to diff against", default=None)
    parser.add_argument("--all", action="store_true", help="Rebuild index for all Markdown")
    parser.add_argument("--snapshot", nargs="?", const="auto", help="Create snapshot (optional YYYYMMDD override)")
    parser.add_argument("--priv", default="keys/ed25519.key", help="Private key for DSSE signing")
    args = parser.parse_args(argv)

    base = Path(args.base).resolve()

    if args.all:
        changed = _all_markdown(base)
    elif args.since:
        changed = _git_changed(base, args.since)
    else:
        changed = _git_changed(base, "HEAD~1") or _all_markdown(base)

    entries = update_index(base, changed)

    content = (base / "docs/index.jsonl").read_text(encoding="utf-8")

    if args.snapshot:
        date = (
            dt.datetime.now(tz=UTC).strftime("%Y%m%d")
            if args.snapshot == "auto"
            else args.snapshot
        )
        _create_snapshot(base, content, date, Path(args.priv))
        print(f"Snapshot created at indexes/{date}")

    print(f"Updated {len(changed)} markdown entries.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
