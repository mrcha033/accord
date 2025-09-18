"""Multi-agent orchestrator skeleton wiring runtime guard, MCP stubs, and DSSE provenance.

The goal is to provide a minimal-yet-operational entry point for running
multiple LLM-backed agents in parallel on a single machine.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence

import yaml
from mcp import MCPClient, MCPError
from orchestrator.llm import GenerateRequest, LLMClient, LLMConfigurationError
from scripts.policy_synth_pipeline import PipelineError, run_pipeline
from scripts.runtime_guard import RuntimeGuard, ScopeError

LOGGER = logging.getLogger(__name__)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


@dataclass(frozen=True)
class AgentConfig:
    agent_id: str
    prompt_path: Path
    output_path: Path
    summary_path: Path
    context_roots: Sequence[Path]


BASE_AGENT_CONFIGS: dict[str, AgentConfig] = {
    "AGENT-OPS01": AgentConfig(
        agent_id="AGENT-OPS01",
        prompt_path=Path("agents/AGENT-OPS01/prompt.md"),
        output_path=Path("org/ops/bootstrap-ops-report.md"),
        summary_path=Path("bus/daily/ops-status.md"),
        context_roots=(Path("org/ops"), Path("bus/alerts")),
    ),
    "AGENT-PM01": AgentConfig(
        agent_id="AGENT-PM01",
        prompt_path=Path("agents/AGENT-PM01/prompt.md"),
        output_path=Path("org/policy/briefs/gedi-bootstrap.md"),
        summary_path=Path("bus/daily/gedi.md"),
        context_roots=(Path("org/policy"), Path("bus/policy")),
    ),
    "AGENT-ENG01": AgentConfig(
        agent_id="AGENT-ENG01",
        prompt_path=Path("agents/AGENT-ENG01/prompt.md"),
        output_path=Path("org/eng/orchestrator/bootstrap-notes.md"),
        summary_path=Path("bus/daily/engineering.md"),
        context_roots=(Path("org/eng"), Path("experiments")),
    ),
}


def collect_context(base_dir: Path, roots: Iterable[Path], limit: int = 5) -> List[str]:
    resolved_roots = [((base_dir / root) if not root.is_absolute() else root).resolve() for root in roots]
    documents: list[tuple[float, Path]] = []
    for root in resolved_roots:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else list(root.glob("**/*.md"))
        for candidate in candidates:
            try:
                mtime = candidate.stat().st_mtime
            except FileNotFoundError:
                continue
            documents.append((mtime, candidate))
    documents.sort(reverse=True)
    snippets: List[str] = []
    for _, path in documents[:limit]:
        try:
            snippets.append(f"# {path.relative_to(base_dir)}\n{path.read_text(encoding='utf-8')}")
        except UnicodeDecodeError:
            continue
    return snippets


def summarize_stub(agent_id: str, draft: str) -> str:
    lines = draft.splitlines()
    headline = lines[0] if lines else f"Summary for {agent_id}"
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return "\n".join(
        [
            headline,
            "",
            f"- Generated: {timestamp}",
            f"- Agent: {agent_id}",
            f"- Preview: {' '.join(lines[1:5])[:200] if len(lines) > 1 else 'n/a'}",
            "",
            "_DSSE attestation pending. Run policy_synth_pipeline when ready._",
        ]
    )


def load_alou_data(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"ALOU front-matter missing for {path}")
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise ValueError("ALOU front-matter must be a mapping")
    return data


def compose_document(
    *,
    artifact_path: Path,
    agent_id: str,
    agent_role: str,
    coach_agent: str,
    predicate_type: str,
    body: str,
    materials: Sequence[str],
) -> str:
    materials_unique = []
    seen = set()
    for material in materials:
        if not material or material in seen:
            continue
        materials_unique.append({"name": material, "digest": {}})
        seen.add(material)

    provenance = {
        "_type": "https://in-toto.io/Statement/v0.1",
        "subject": [{"name": str(artifact_path), "digest": {}}],
        "predicateType": predicate_type,
        "predicate": {
            "produced_by": {
                "agent_id": agent_id,
                "agent_role": agent_role,
                "coach_id": coach_agent,
            },
            "process": {
                "toolchain": [
                    {
                        "name": "accord.orchestrator",
                        "version": "0.4.0-dev0",
                    }
                ],
                "mcp_sessions": [],
            },
            "materials": materials_unique,
        },
        "signers": [
            {
                "id": agent_id,
                "signature_ref": f"attestations/{agent_id}/{artifact_path.name}.dsse",
            }
        ],
    }
    header_yaml = yaml.safe_dump({"provenance": provenance}, sort_keys=False, allow_unicode=True)
    return f"<!--\n{header_yaml}-->\n\n{body.strip()}\n"


def run_agent(config: AgentConfig, base_dir: Path) -> dict[str, str]:
    alou_path = base_dir / "org/_registry" / f"{config.agent_id}.alou.md"
    guard = RuntimeGuard.from_alou(alou_path, base_dir=base_dir)
    mcp_client = MCPClient(guard, base_dir=base_dir)
    alou_data = load_alou_data(alou_path)

    prompt = mcp_client.call("file", "read_text", path=str(config.prompt_path)).data
    context_docs = collect_context(base_dir, config.context_roots)
    knowledge_refs = mcp_client.call(
        "knowledge",
        "retrieve",
        topic=config.agent_id.lower(),
        notes_dir="docs",
    ).data

    llm = LLMClient()
    try:
        draft = llm.generate(
            GenerateRequest(
                agent_id=config.agent_id,
                prompt=prompt,
                context=context_docs,
                knowledge_refs=knowledge_refs,
            )
        )
    except LLMConfigurationError as exc:
        raise RuntimeError(f"LLM misconfiguration for {config.agent_id}: {exc}") from exc
    except Exception as exc:  # pragma: no cover - surface provider failures
        raise RuntimeError(f"LLM invocation failed for {config.agent_id}: {exc}") from exc

    output_path = config.output_path
    artifact_body = compose_document(
        artifact_path=output_path,
        agent_id=config.agent_id,
        agent_role=alou_data.get("role_title", ""),
        coach_agent=alou_data.get("coach_agent", "NONE"),
        predicate_type="https://accord.ai/schemas/agent-report@v1",
        body=draft,
        materials=[str(config.prompt_path), *[str(ref) for ref in knowledge_refs]],
    )
    guard.fs.write_text(output_path, artifact_body)

    summary = summarize_stub(config.agent_id, draft)
    summary_body = compose_document(
        artifact_path=config.summary_path,
        agent_id=config.agent_id,
        agent_role=alou_data.get("role_title", ""),
        coach_agent=alou_data.get("coach_agent", "NONE"),
        predicate_type="https://accord.ai/schemas/bus-summary@v1",
        body=summary,
        materials=[],
    )
    guard.fs.write_text(config.summary_path, summary_body)

    attestation_path = Path("attestations") / config.agent_id / f"{output_path.name}.dsse"
    private_key = Path("keys/ed25519.key")
    try:
        run_pipeline(
            artifact=output_path,
            private_key=private_key,
            attestation=attestation_path,
            key_id=f"{config.agent_id}-bootstrap",
            base_dir=base_dir,
        )
    except FileNotFoundError:
        LOGGER.warning(
            "Skipping DSSE for %s because private key %s is missing",
            config.agent_id,
            private_key,
        )
    except PipelineError as exc:
        LOGGER.warning("DSSE pipeline failed for %s: %s", config.agent_id, exc)

    return {
        "agent_id": config.agent_id,
        "output": str(output_path),
        "summary": str(config.summary_path),
        "attestation": str(attestation_path),
    }


def run_all(agent_ids: Sequence[str] | None = None, *, base_dir: Path | None = None) -> List[dict[str, str]]:
    base_dir = (base_dir or Path(".")).resolve()
    ids = list(agent_ids or BASE_AGENT_CONFIGS.keys())
    configs = [BASE_AGENT_CONFIGS[agent_id] for agent_id in ids]
    results: List[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=len(configs) or 1) as executor:
        futures = {executor.submit(run_agent, cfg, base_dir): cfg.agent_id for cfg in configs}
        for future in as_completed(futures):
            agent_id = futures[future]
            try:
                results.append(future.result())
            except ScopeError as exc:
                LOGGER.error("Scope violation for %s: %s", agent_id, exc)
                raise
            except MCPError as exc:
                LOGGER.error("MCP failure for %s: %s", agent_id, exc)
                raise
    return results


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent",
        action="append",
        dest="agents",
        help="Agent ID to run (can be supplied multiple times). Defaults to all registered agents.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit results as JSON for pipeline consumption.",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(".").resolve(),
        help="Project root when running from another directory.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    results = run_all(args.agents, base_dir=args.base_dir)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            LOGGER.info(
                "Agent %s wrote %s, summary %s, attestation %s",
                result["agent_id"],
                result["output"],
                result["summary"],
                result["attestation"],
            )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
