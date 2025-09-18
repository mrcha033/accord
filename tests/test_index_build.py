from pathlib import Path

from scripts import index_build, provtools


def _write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _ensure_keys(base: Path) -> Path:
    priv = base / "keys/ed25519.key"
    pub = base / "keys/ed25519.pub"
    priv.parent.mkdir(parents=True, exist_ok=True)
    if not priv.exists():
        provtools.keygen_ed25519(priv, pub)
    return priv


def test_index_build_all(tmp_path: Path) -> None:
    base = tmp_path
    _write_markdown(base / "docs/foo.md", "# Foo Document\nContent")
    _write_markdown(base / "docs/bar.md", "# Bar Doc\nMore content")
    priv = _ensure_keys(base)

    entries = index_build.update_index(base, [p for p in base.rglob("*.md")])
    assert "docs/foo.md" in entries

    content = (base / "docs/index.jsonl").read_text(encoding="utf-8")
    assert "Foo Document" in content

    index_build._create_snapshot(base, content, "20250101", priv)
    snapshot = base / "indexes/20250101/index.jsonl"
    assert snapshot.exists()
    latest = base / "indexes/latest.json"
    assert "20250101" in latest.read_text(encoding="utf-8")


def test_index_build_since(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path
    file_a = base / "docs/a.md"
    file_b = base / "docs/b.md"
    _write_markdown(file_a, "# A heading\n")
    _write_markdown(file_b, "# B heading\n")

    def fake_git(base_path: Path, since: str):
        return [file_a]

    monkeypatch.setattr(index_build, "_git_changed", fake_git)
    entries = index_build.update_index(base, index_build._git_changed(base, "HEAD~1"))
    assert "docs/a.md" in entries
    assert "docs/b.md" not in entries
