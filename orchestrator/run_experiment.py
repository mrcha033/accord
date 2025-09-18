"""Experiment runner coordinating multi-round orchestrator executions."""
from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from orchestrator.experiment_loop import (
    ExperimentLoop,
    LifecycleSpec,
    TimelineSpec,
)
from scripts.policy_synth_pipeline import PipelineError, run_pipeline
from scripts.runtime_guard import RuntimeGuard, ScopeError

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ExperimentSpec:
    seed: int
    tasks: list[str]
    agents: list[str]
    governance: dict[str, Any]
    context: dict[str, Any]
    bus: dict[str, Any]
    outputs: dict[str, Any]
    timeline: TimelineSpec
    lifecycle: LifecycleSpec


DEFAULT_SPEC_PATH = Path("experiments/run.yaml")
DEFAULT_ALOU = Path("org/_registry/AGENT-ENG01.alou.md")
DEFAULT_PRIVATE_KEY = Path("keys/ed25519.key")


def load_spec(path: Path) -> ExperimentSpec:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    timeline = TimelineSpec.from_mapping(data.get("timeline"))
    lifecycle = LifecycleSpec.from_mapping(data.get("lifecycle"))
    return ExperimentSpec(
        seed=int(data.get("seed", 0)),
        tasks=list(data.get("tasks", [])),
        agents=list(data.get("agents", [])),
        governance=dict(data.get("governance", {})),
        context=dict(data.get("context", {})),
        bus=dict(data.get("bus", {})),
        outputs=dict(data.get("outputs", {})),
        timeline=timeline,
        lifecycle=lifecycle,
    )


def _build_metadata(spec: ExperimentSpec) -> dict[str, Any]:
    return {
        "tasks": spec.tasks,
        "agents": spec.agents,
        "governance": spec.governance,
        "context": spec.context,
        "bus": spec.bus,
    }


def _attest_artifact(
    *,
    guard: RuntimeGuard,
    private_key: Path,
    artifact: Path,
    base_dir: Path,
    key_id: str,
    spec_path: Path,
) -> None:
    if not artifact.exists():
        LOGGER.info("Artifact %s not found; skipping attestation", artifact)
        return

    provider = os.environ.get("ACCORD_LLM_PROVIDER", "mock")
    model = os.environ.get("ACCORD_OPENAI_MODEL", "mock")
    temperature = os.environ.get("ACCORD_OPENAI_TEMPERATURE", "0")

    try:
        relative_artifact = artifact.relative_to(base_dir)
    except ValueError:
        LOGGER.warning("Artifact %s is outside base_dir; skipping attestation", artifact)
        return
    sidecar_relative = relative_artifact.with_suffix(".prov.md")
    try:
        spec_relative = spec_path.relative_to(base_dir)
    except ValueError:
        spec_relative = spec_path
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
        f"      - name: \"{spec_relative.as_posix()}\"\n"
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
            key_id=key_id,
            base_dir=base_dir,
        )
        LOGGER.info(
            "Generated attestation for %s using sidecar %s",
            relative_artifact,
            sidecar_relative,
        )
    except FileNotFoundError:
        LOGGER.debug("Provenance key missing; skipping attestation")
    except PipelineError as exc:
        LOGGER.warning("Attestation failed for %s: %s", relative_artifact, exc)


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
    spec_metadata = _build_metadata(spec)

    loop = ExperimentLoop(
        base_dir=base_dir,
        guard=guard,
        output_root=output_root,
        timeline=spec.timeline,
        lifecycle=spec.lifecycle,
        seed=spec.seed,
        spec_metadata=spec_metadata,
    )
    loop_result = loop.run()

    if attest:
        _attest_artifact(
            guard=guard,
            private_key=private_key,
            artifact=Path(loop_result["state_path"]),
            base_dir=base_dir,
            key_id="AGENT-ENG01-experiment-state",
            spec_path=spec_path,
        )
        _attest_artifact(
            guard=guard,
            private_key=private_key,
            artifact=Path(loop_result["timeline_path"]),
            base_dir=base_dir,
            key_id="AGENT-ENG01-experiment-timeline",
            spec_path=spec_path,
        )
        _attest_artifact(
            guard=guard,
            private_key=private_key,
            artifact=Path(loop_result["manifest_path"]),
            base_dir=base_dir,
            key_id="AGENT-ENG01-experiment-manifest",
            spec_path=spec_path,
        )

    return loop_result


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC_PATH, help="Experiment YAML spec path")
    parser.add_argument("--alou", type=Path, default=DEFAULT_ALOU, help="ALOU file for guard configuration")
    parser.add_argument("--base-dir", type=Path, default=Path(".").resolve(), help="Project root")
    parser.add_argument("--attest", action="store_true", help="Run DSSE attestations if keys exist")
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
