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
from typing import Iterable, List, Mapping, Sequence

import yaml
from mcp import MCPClient, MCPError
from orchestrator.llm import GenerateRequest, LLMClient, LLMConfigurationError
from scripts.policy_synth_pipeline import PipelineError, run_pipeline
from scripts.runtime_guard import RuntimeGuard, ScopeError

LOGGER = logging.getLogger(__name__)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _rel_to_base(path: Path, base_dir: Path) -> str:
    """Return ``path`` relative to ``base_dir`` with graceful fallback."""
    base_abs = base_dir.resolve()
    candidate = path if path.is_absolute() else base_abs / path
    candidate = candidate.resolve()
    try:
        return str(candidate.relative_to(base_abs))
    except ValueError:
        LOGGER.warning(
            "Path %s is not under base %s; using absolute path", candidate, base_abs
        )
        return str(candidate)


@dataclass(frozen=True)
class AgentConfig:
    agent_id: str
    prompt_path: Path
    output_path: Path
    summary_path: Path
    context_roots: Sequence[Path]


def load_registered_agent_configs(base_dir: Path) -> dict[str, AgentConfig]:
    """Read agent runtime configs from registered ALOU contracts."""

    registry_dir = base_dir / "org/_registry"
    if not registry_dir.exists():
        LOGGER.debug("Agent registry directory %s missing", registry_dir)
        return {}

    configs: dict[str, AgentConfig] = {}
    for alou_path in sorted(registry_dir.glob("*.alou.md")):
        try:
            data = load_alou_data(alou_path)
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("Unable to load ALOU %s: %s", alou_path, exc)
            continue

        agent_id = str(data.get("agent_id", "")).strip()
        runtime = data.get("runtime")
        if not agent_id:
            LOGGER.debug("Skipping %s: agent_id missing", alou_path)
            continue
        if not isinstance(runtime, Mapping):
            LOGGER.debug("Skipping %s: runtime block missing", alou_path)
            continue

        try:
            prompt_path = Path(str(runtime["prompt_path"]))
            output_path = Path(str(runtime["output_path"]))
            summary_path = Path(str(runtime["summary_path"]))
        except KeyError as exc:
            LOGGER.warning("Runtime config %s missing %s", alou_path, exc.args[0])
            continue

        context_raw = runtime.get("context_roots") or []
        if isinstance(context_raw, Sequence) and not isinstance(context_raw, (str, bytes)):
            context_roots = tuple(Path(str(item)) for item in context_raw if str(item).strip())
        else:
            context_roots = tuple([Path(str(context_raw))]) if context_raw else tuple()

        configs[agent_id] = AgentConfig(
            agent_id=agent_id,
            prompt_path=prompt_path,
            output_path=output_path,
            summary_path=summary_path,
            context_roots=context_roots,
        )

    return configs


def _latest_index_materials(base_dir: Path) -> List[str]:
    latest_file = base_dir / "indexes/latest.json"
    if not latest_file.exists():
        return []
    try:
        data = json.loads(latest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    snapshot = data.get("snapshot")
    if not snapshot:
        return []
    return [snapshot]


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


def _alou_revision(alou_path: Path) -> str:
    text = alou_path.read_text(encoding="utf-8", errors="ignore")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return "unknown"
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except Exception:
        return "unknown"
    return str(data.get("revision", "unknown"))


def _collect_policy_refs(*sources: Iterable[str] | str) -> List[str]:
    refs: List[str] = []
    seen = set()
    for source in sources:
        if not source:
            continue
        if isinstance(source, str):
            items = [source]
        else:
            items = list(source)
        for item in items:
            if not isinstance(item, str):
                continue
            if "org/policy" in item:
                ref = item.strip()
                if ref not in seen:
                    refs.append(ref)
                    seen.add(ref)
    return refs


def _log_event(
    events_path: Path,
    *,
    agent_id: str,
    action: str,
    targets: list[str],
    dsse_ref: str,
    alou_rev: str,
    scopes: list[str],
    policy_refs: list[str],
    start_time: datetime,
) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "t": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "agent": agent_id,
        "act": action,
        "targets": targets,
        "policy_refs": policy_refs,
        "scopes": scopes,
        "alou_rev": alou_rev,
        "dsse_ref": dsse_ref,
        "latency_ms": int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
    }
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


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


def _alou_get_str(data: Mapping[str, object], key: str, default: str = "") -> str:
    value = data.get(key, default)
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


def _alou_get_str_list(data: Mapping[str, object], key: str) -> list[str]:
    value = data.get(key)
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [str(item) for item in value if item]
    return [str(value)] if value else []


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


def run_agent(config: AgentConfig, base_dir: Path, *, events_path: Path) -> dict[str, str]:
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
    snapshot_refs = _latest_index_materials(base_dir)
    # Filter materials to only include existing files
    existing_knowledge_refs = []
    for ref in knowledge_refs:
        if isinstance(ref, (str, Path)):
            ref_path = base_dir / ref if not Path(ref).is_absolute() else Path(ref)
            if ref_path.exists():
                existing_knowledge_refs.append(str(ref))

    artifact_body = compose_document(
        artifact_path=output_path,
        agent_id=config.agent_id,
        agent_role=_alou_get_str(alou_data, "role_title"),
        coach_agent=_alou_get_str(alou_data, "coach_agent", "NONE"),
        predicate_type="https://accord.ai/schemas/agent-report@v1",
        body=draft,
        materials=[
            str(config.prompt_path),
            *existing_knowledge_refs,
            *snapshot_refs,
        ],
    )
    guard.fs.write_text(output_path, artifact_body)
    scopes = _alou_get_str_list(alou_data, "fs_write_scopes")
    alou_rev = _alou_revision(alou_path)
    policy_refs = _collect_policy_refs(knowledge_refs)
    start_time = datetime.now(timezone.utc)
    summary = summarize_stub(config.agent_id, draft)
    summary_body = compose_document(
        artifact_path=config.summary_path,
        agent_id=config.agent_id,
        agent_role=_alou_get_str(alou_data, "role_title"),
        coach_agent=_alou_get_str(alou_data, "coach_agent", "NONE"),
        predicate_type="https://accord.ai/schemas/bus-summary@v1",
        body=summary,
        materials=snapshot_refs,
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

    dsse_rel = _rel_to_base(attestation_path, base_dir)
    _log_event(
        events_path,
        agent_id=config.agent_id,
        action="write",
        targets=[_rel_to_base(output_path, base_dir)],
        dsse_ref=dsse_rel,
        alou_rev=alou_rev,
        scopes=scopes,
        policy_refs=policy_refs,
        start_time=start_time,
    )

    summary_attestation = Path("attestations") / config.agent_id / f"{config.summary_path.name}.dsse"
    try:
        run_pipeline(
            artifact=config.summary_path,
            private_key=private_key,
            attestation=summary_attestation,
            key_id=f"{config.agent_id}-bootstrap-summary",
            base_dir=base_dir,
        )
    except FileNotFoundError:
        LOGGER.warning(
            "Skipping summary DSSE for %s because private key %s is missing",
            config.agent_id,
            private_key,
        )
    except PipelineError as exc:
        LOGGER.warning("Summary DSSE pipeline failed for %s: %s", config.agent_id, exc)

    summary_dsse_rel = _rel_to_base(summary_attestation, base_dir)
    _log_event(
        events_path,
        agent_id=config.agent_id,
        action="write",
        targets=[_rel_to_base(config.summary_path, base_dir)],
        dsse_ref=summary_dsse_rel,
        alou_rev=alou_rev,
        scopes=scopes,
        policy_refs=policy_refs,
        start_time=datetime.now(timezone.utc),
    )

    return {
        "agent_id": config.agent_id,
        "output": str(output_path),
        "summary": str(config.summary_path),
        "attestation": str(attestation_path),
    }


def run_all(
    agent_ids: Sequence[str] | None = None,
    *,
    base_dir: Path | None = None,
    events_path: Path | None = None,
) -> List[dict[str, str]]:
    base_dir = (base_dir or Path(".")).resolve()
    events_path = events_path or base_dir / "experiments/results/events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    registry = load_registered_agent_configs(base_dir)
    if agent_ids:
        ids = list(agent_ids)
    else:
        ids = sorted(registry.keys())

    configs: list[AgentConfig] = []
    missing: list[str] = []
    for agent_id in ids:
        config = registry.get(agent_id)
        if config is None:
            missing.append(agent_id)
            continue
        configs.append(config)

    if missing:
        raise KeyError(f"Agent configs not registered: {', '.join(missing)}")

    if not configs:
        LOGGER.info("No registered agents to run.")
        return []
    results: List[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=len(configs) or 1) as executor:
        futures = {
            executor.submit(run_agent, cfg, base_dir, events_path=events_path): cfg.agent_id
            for cfg in configs
        }
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
