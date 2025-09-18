"""Behavior metrics and schema checks for agent events."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List


REQUIRED_FIELDS = {"t", "agent", "act", "targets", "policy_refs", "scopes", "dsse_ref"}


@dataclass
class Metrics:
    total_events: int
    per_agent: Counter
    policy_refs: Counter


def iter_event_files(paths: Iterable[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_dir():
            yield from path.rglob("events.jsonl")
        else:
            yield path


def load_events(files: Iterable[Path]) -> List[dict]:
    records: List[dict] = []
    for file_path in files:
        if not file_path.exists():
            continue
        for line in file_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
    return records


def validate_events(events: Iterable[dict]) -> List[str]:
    issues: List[str] = []
    for idx, event in enumerate(events):
        missing = REQUIRED_FIELDS - event.keys()
        if missing:
            issues.append(f"event #{idx}: missing fields {sorted(missing)}")
        if not event.get("targets"):
            issues.append(f"event #{idx}: targets empty")
        if not event.get("dsse_ref"):
            issues.append(f"event #{idx}: dsse_ref empty")
    return issues


def compute_metrics(events: Iterable[dict]) -> Metrics:
    per_agent = Counter()
    policy_refs = Counter()
    for event in events:
        per_agent[event.get("agent", "unknown")] += 1
        for ref in event.get("policy_refs", []):
            policy_refs[ref] += 1
    return Metrics(total_events=sum(per_agent.values()), per_agent=per_agent, policy_refs=policy_refs)


def print_metrics(metrics: Metrics) -> None:
    print(f"Total events: {metrics.total_events}")
    print("Events per agent:")
    for agent, count in metrics.per_agent.most_common():
        print(f"  {agent}: {count}")
    if metrics.policy_refs:
        print("Policy references:")
        for ref, count in metrics.policy_refs.most_common():
            print(f"  {ref}: {count}")


def default_event_paths(base: Path) -> List[Path]:
    results_dir = base / "experiments/results"
    if results_dir.exists():
        return list(results_dir.rglob("events.jsonl"))
    return []


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="*", type=Path, help="Event files or directories")
    parser.add_argument("--base", default=".", help="Project base directory")
    parser.add_argument("--check", action="store_true", help="Fail on schema errors")
    args = parser.parse_args(argv)

    base = Path(args.base).resolve()
    paths = args.path or default_event_paths(base)
    if not paths:
        print("No event files found.")
        return 1 if args.check else 0

    events = load_events(iter_event_files(paths))
    if args.check:
        issues = validate_events(events)
        if issues:
            for issue in issues:
                print(issue)
            return 1
        print("behavior check: ok")
        return 0

    metrics = compute_metrics(events)
    print_metrics(metrics)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
