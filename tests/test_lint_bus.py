from pathlib import Path

from scripts import lint_bus


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_lint_bus_passes_on_valid_docs(tmp_path: Path) -> None:
    base = tmp_path
    _write(
        base / "bus/alerts/alert-test.md",
        """# ALERT – Example\n\nImpact: systems down\nActions: restart\nOwner: AGENT-OPS01\n""",
    )
    _write(
        base / "bus/daily/sample.md",
        """# Draft generated\n\n- Generated: 2025-01-01\n- Agent: AGENT-OPS01\n\n_DSSE note_\n""",
    )
    _write(
        base / "bus/inbox/request.md",
        """# Request: Help\n\n**Raised by**: AGENT-PM01\n**Owner**: AGENT-OPS01\n**Status**: open\n""",
    )
    _write(
        base / "bus/policy/summary.md",
        """# Policy Summary\n\nDetails...\n""",
    )

    issues = lint_bus.lint_bus(base)
    assert issues == []


def test_lint_bus_flags_bad_alert(tmp_path: Path) -> None:
    base = tmp_path
    _write(base / "bus/alerts/bad.md", "Missing everything")
    issues = lint_bus.lint_bus(base)
    assert any("bad.md" in issue for issue in issues)
