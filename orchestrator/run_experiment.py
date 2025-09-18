"""Experiment runner that coordinates orchestrator executions and captures provenance artifacts."""
from __future__ import annotations

import argparse
import json
import logging
import os
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
    if not (guard.fs.base_dir / events_path if hasattr(guard.fs, "base_dir") else events_path).exists():
        rows: list[dict[str, Any]] = []
        for run in agent_runs:
            event = {
                "t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "agent": run["agent_id"],
                "act": "write",
                "targets": [run["output"], run["summary"]],
                "policy_refs": [],
                "scopes": [],
                "dsse_ref": run["attestation"],
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
    base_dir = guard.fs.base_dir if hasattr(guard.fs, "base_dir") else Path(".").resolve()
    artifact = root / "metadata.json"
    if not artifact.exists():
        LOGGER.info("metadata.json not found under %s; skipping attestation", root)
        return

    relative_artifact = artifact.relative_to(base_dir)
    sidecar_relative = relative_artifact.with_suffix(".prov.md")
    provider = os.environ.get("ACCORD_LLM_PROVIDER", "mock")
    model = os.environ.get("ACCORD_OPENAI_MODEL", "mock")
    temperature = os.environ.get("ACCORD_OPENAI_TEMPERATURE", "0")

    sidecar_content = (
        "<!--\n"
        f"provenance:\n"
        f"  _type: \"https://in-toto.io/Statement/v0.1\"\n"
        f"  subject:\n"
        f"    - name: \"{relative_artifact.as_posix()}\"\n"
        f"      digest: {{}}\n"
        f"  predicateType: \"https://accord.ai/schemas/artifact@v1\"\n"
        f"  predicate:\n"
        f"    produced_by:\n"
        f"      agent_id: \"AGENT-EXPRUNNER\"\n"
        f"      agent_role: \"Experiment Runner\"\n"
        f"    process:\n"
        f"      toolchain:\n"
        f"        - name: \"orchestrator\"\n"
        f"          version: \"0.4.0-dev0\"\n"
        f"        - name: \"llm\"\n"
        f"          provider: \"{provider}\"\n"
        f"          model: \"{model}\"\n"
        f"          temperature: \"{temperature}\"\n"
        f"    materials:\n"
        f"      - name: \"docs/index.jsonl\"\n"
        f"        digest: {{}}\n"
        f"      - name: \"experiments/run.yaml\"\n"
        f"        digest: {{}}\n"
        "-->\n"
    )

    try:
        guard.fs.write_text(sidecar_relative, sidecar_content)
    except FileNotFoundError:
        LOGGER.warning("Unable to write provenance sidecar %s", sidecar_relative)
        return

    attestation_relative = relative_artifact.with_suffix(".json.dsse")
    try:
        run_pipeline(
            artifact=sidecar_relative,
            private_key=private_key,
            attestation=attestation_relative,
            key_id="AGENT-ENG01-experiments",
            base_dir=base_dir,
        )
        LOGGER.info(
            "Generated metadata attestation at %s using sidecar %s",
            attestation_relative,
            sidecar_relative,
        )
    except FileNotFoundError:
        # Keys absent locally; skip silently for developer convenience
        LOGGER.debug("Provenance key missing; skipping metadata attestation")
    except PipelineError as exc:
        LOGGER.warning("Metadata attestation failed: %s", exc)


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

    output_root = base_dir / spec.outputs.get("root", "experiments/results/bootstrap")
    events_path = output_root / "events.jsonl"
    if events_path.exists():
        events_path.unlink()
    events_path.parent.mkdir(parents=True, exist_ok=True)
    results = run_all(spec.agents or None, base_dir=base_dir, events_path=events_path)
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
