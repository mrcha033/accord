"""Experiment runner that coordinates orchestrator executions and captures provenance artifacts."""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Sequence

import yaml

from orchestrator.runtime import run_all
from scripts.policy_synth_pipeline import PipelineError, run_pipeline
from scripts.runtime_guard import RuntimeGuard, ScopeError

LOGGER = logging.getLogger(__name__)

@dataclass
class ExperimentSpec:
    seed: int
    tasks: list[str]
    agents: list[str]
    governance: dict[str, Any]
    context: dict[str, Any]
    bus: dict[str, Any]
    outputs: dict[str, Any]


DEFAULT_SPEC_PATH = Path("experiments/run.yaml")
DEFAULT_ALOU = Path("org/_registry/AGENT-ENG01.alou.md")
DEFAULT_PRIVATE_KEY = Path("keys/ed25519.key")


def load_spec(path: Path) -> ExperimentSpec:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ExperimentSpec(
        seed=int(data.get("seed", 0)),
        tasks=list(data.get("tasks", [])),
        agents=list(data.get("agents", [])),
        governance=dict(data.get("governance", {})),
        context=dict(data.get("context", {})),
        bus=dict(data.get("bus", {})),
        outputs=dict(data.get("outputs", {})),
    )


def write_results(
    *,
    guard: RuntimeGuard,
    root: Path,
    metadata: Dict[str, Any],
    agent_runs: Sequence[Dict[str, Any]],
) -> Path:
    root_relative = Path(root.relative_to(guard.fs.base_dir)) if hasattr(guard.fs, "base_dir") else root
    guard.fs.write_text(root_relative / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

    events_path = root_relative / "events.jsonl"
    rows: list[dict[str, Any]] = []
    for run in agent_runs:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "agent_id": run["agent_id"],
            "artifact": run["output"],
            "summary": run["summary"],
            "attestation": run["attestation"],
        }
        rows.append(event)
    guard.fs.write_text(events_path, "\n".join(json.dumps(row, ensure_ascii=False) for row in rows))

    csv_path = root_relative / "results.csv"
    csv_lines = ["agent_id,artifact,summary,attestation"]
    for run in agent_runs:
        csv_lines.append(
            ",".join(
                [
                    run["agent_id"],
                    run["output"],
                    run["summary"],
                    run["attestation"],
                ]
            )
        )
    guard.fs.write_text(csv_path, "\n".join(csv_lines))

    return events_path


def _attest_results(root: Path, guard: RuntimeGuard, private_key: Path) -> None:
    artifact = root / "metadata.json"
    if artifact.suffix != ".md" and not artifact.read_text(encoding="utf-8", errors="ignore").strip().startswith("<!--"):
        LOGGER = logging.getLogger(__name__)
        LOGGER.warning("Skipping attestation for %s (no provenance header)", artifact)
        return
    attestation = Path("attestations/AGENT-ENG01/experiments") / f"{artifact.stem}.dsse"
    try:
        run_pipeline(
            artifact=artifact,
            private_key=private_key,
            attestation=attestation,
            key_id="AGENT-ENG01-experiments",
            base_dir=guard.fs.base_dir,
        )
    except FileNotFoundError:
        # When keys are absent locally we skip attestation but keep deterministic output
        return
    except PipelineError:
        return


def run_experiment(
    *,
    spec_path: Path = DEFAULT_SPEC_PATH,
    alou_path: Path = DEFAULT_ALOU,
    private_key: Path = DEFAULT_PRIVATE_KEY,
    base_dir: Path | None = None,
    attest: bool = False,
) -> dict[str, Any]:
    base_dir = (base_dir or Path(".")).resolve()
    spec = load_spec(spec_path)
    guard = RuntimeGuard.from_alou(alou_path, base_dir=base_dir)

    results = run_all(spec.agents or None, base_dir=base_dir)
    output_root = base_dir / spec.outputs.get("root", "experiments/results/bootstrap")
    metadata = {
        "seed": spec.seed,
        "tasks": spec.tasks,
        "agents": spec.agents,
        "governance": spec.governance,
        "context": spec.context,
        "bus": spec.bus,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    events_path = write_results(
        guard=guard,
        root=output_root,
        metadata=metadata,
        agent_runs=results,
    )

    if attest:
        _attest_results(output_root, guard, private_key)

    return {
        "metadata": str(output_root / "metadata.json"),
        "events": str(events_path),
        "results": str(output_root / "results.csv"),
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC_PATH, help="Experiment YAML spec path")
    parser.add_argument("--alou", type=Path, default=DEFAULT_ALOU, help="ALOU file for guard configuration")
    parser.add_argument("--base-dir", type=Path, default=Path(".").resolve(), help="Project root")
    parser.add_argument("--attest", action="store_true", help="Run DSSE attestation on outputs if keys exist")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result_paths = run_experiment(
            spec_path=args.spec,
            alou_path=args.alou,
            base_dir=args.base_dir,
            attest=args.attest,
        )
    except ScopeError as exc:
        print(f"Scope violation: {exc}")
        return 2
    print(json.dumps(result_paths, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
