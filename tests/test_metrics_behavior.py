from pathlib import Path

from scripts import metrics_behavior


def test_metrics_behavior_check(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(
        "\n".join(
            [
                '{"t": "2025-01-01T00:00:00Z", "agent": "AGENT-OPS01", "act": "write", "targets": ["a.md"], "policy_refs": ["org/policy/x.md"], "scopes": ["org/ops/**"], "dsse_ref": "attestations/a.dsse"}',
                '{"t": "2025-01-01T00:00:01Z", "agent": "AGENT-OPS01", "act": "write", "targets": ["b.md"], "policy_refs": [], "scopes": ["org/ops/**"], "dsse_ref": "attestations/b.dsse"}',
            ]
        ),
        encoding="utf-8",
    )
    records = metrics_behavior.load_events([events])
    assert not metrics_behavior.validate_events(records)
    metrics = metrics_behavior.compute_metrics(records)
    assert metrics.total_events == 2
    assert metrics.per_agent["AGENT-OPS01"] == 2


def test_metrics_behavior_missing_fields(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text('{"agent": "A"}', encoding="utf-8")
    records = metrics_behavior.load_events([events])
    issues = metrics_behavior.validate_events(records)
    assert issues
