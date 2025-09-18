import os
from pathlib import Path

import pytest

from scripts.runtime_guard import RuntimeGuard, ScopeError

ALOU = """---
agent_id: AGENT-PO01
role_title: "Policy Orchestrator"
version: 1.1
cluster_path: {chapter: "Gov", squad: "Core"}
revision: 2025-09-18
coach_agent: NONE
status: active
effective_from: 2025-09-18
capabilities: ["policy_draft"]
mcp_allow: ["file", "git", "search"]
fs_write_scopes: ["org/policy/**", "bus/gedi/**"]
gedi: {roles:["voter"], vote_weight: 0.6, quorum: 0.6}
provenance: {attestation_path: "a", hash_algo: "sha256", key_id: "k"}
security: {threat_model: "t", forbidden_ops: ["x"]}
---
"""


def _guard(tmp_path: Path) -> RuntimeGuard:
    reg = tmp_path / "org/_registry/AGENT-PO01.alou.md"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(ALOU, encoding="utf-8")
    return RuntimeGuard.from_alou(reg, base_dir=tmp_path)


def test_fs_write_allows_scoped(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    out = guard.fs.write_text(Path("org/policy/p1.md"), "hello")
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "hello"


def test_fs_write_blocks_escape(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    with pytest.raises(ScopeError):
        guard.fs.write_text(Path("../evil.md"), "nope")


def test_fs_write_blocks_absolute(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    abs_target = Path(os.path.abspath("/tmp/abs.md"))
    with pytest.raises(ScopeError):
        guard.fs.write_text(abs_target, "nope")


def test_fs_write_blocks_symlink(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    allowed_dir = tmp_path / "org/policy"
    allowed_dir.mkdir(parents=True)
    real = allowed_dir / "real.md"
    real.write_text("data", encoding="utf-8")
    link = allowed_dir / "link.md"
    link.symlink_to(real)
    with pytest.raises(ScopeError):
        guard.fs.write_text(Path("org/policy/link.md"), "nope")


def test_mcp_allow_gate(tmp_path: Path) -> None:
    guard = _guard(tmp_path)

    def raw(endpoint: str, action: str, **kwargs):
        return {"ok": True, "endpoint": endpoint, "action": action}

    wrapped = guard.wrap_tool_call(raw)
    assert wrapped("file", "stat")["ok"] is True
    with pytest.raises(ScopeError):
        wrapped("browser", "get", url="https://example.com")
