"""Agent onboarding helpers for autonomous recruitment pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jsonschema import Draft202012Validator

from scripts.validate_alou import SCHEMA, extra_checks, extract_frontmatter


class AgentOnboardingError(RuntimeError):
    """Raised when an agent candidate document fails onboarding checks."""


@dataclass(frozen=True)
class AgentMaterialization:
    """Result of converting a candidate ALOU into runtime assets."""

    agent_id: str
    alou_path: Path
    prompt_path: Path
    output_path: Path
    summary_path: Path
    context_roots: tuple[Path, ...]
    prompt_created: bool
    output_created: bool
    summary_created: bool


def _ensure_relative(path_str: str, *, field: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        raise AgentOnboardingError(f"{field} must be a repository-relative path: {path_str}")
    return path


def _write_if_missing(path: Path, *, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _placeholder(agent_id: str, purpose: str) -> str:
    return (
        f"<!-- Auto-generated placeholder for {agent_id} ({purpose}). "
        "You may replace this content once the agent is active. -->\n"
    )


def materialize_agent(base_dir: Path, candidate: Path | str) -> AgentMaterialization:
    """Materialise a recruited agent from a candidate ALOU document.

    Parameters
    ----------
    base_dir:
        Repository root acting as canonical base for relative paths.
    candidate:
        Path to the drafted ALOU (relative or absolute). The document must
        satisfy ``scripts.validate_alou`` schema requirements and include a
        ``runtime`` section enumerating prompt/output locations.

    Returns
    -------
    AgentMaterialization
        Metadata describing the generated artefacts.

    Raises
    ------
    AgentOnboardingError
        If validation fails or required runtime metadata is missing.
    """

    base_dir = base_dir.resolve()
    candidate_path = Path(candidate)
    if not candidate_path.is_absolute():
        candidate_path = (base_dir / candidate_path).resolve()
    if not candidate_path.exists():
        raise AgentOnboardingError(f"Candidate ALOU not found: {candidate_path}")

    text = candidate_path.read_text(encoding="utf-8")
    try:
        frontmatter = extract_frontmatter(text)
    except ValueError as exc:
        raise AgentOnboardingError(str(exc)) from exc

    validator = Draft202012Validator(SCHEMA)
    schema_errors = [
        f"{error.message} @ {'/'.join(map(str, error.path))}"
        for error in validator.iter_errors(frontmatter)
    ]
    guardrail_errors = extra_checks(frontmatter)
    if schema_errors or guardrail_errors:
        combined = ", ".join(schema_errors + guardrail_errors)
        raise AgentOnboardingError(f"Candidate ALOU validation failed: {combined}")

    agent_id = str(frontmatter.get("agent_id"))
    if not agent_id:
        raise AgentOnboardingError("agent_id missing from candidate ALOU")

    runtime = frontmatter.get("runtime") or {}
    if not isinstance(runtime, dict):
        raise AgentOnboardingError("runtime block missing or not a mapping")

    try:
        prompt_path_rel = _ensure_relative(runtime["prompt_path"], field="runtime.prompt_path")
        output_path_rel = _ensure_relative(runtime["output_path"], field="runtime.output_path")
        summary_path_rel = _ensure_relative(runtime["summary_path"], field="runtime.summary_path")
    except KeyError as exc:  # pragma: no cover - safeguarded by schema
        raise AgentOnboardingError(f"runtime field missing: {exc.args[0]}") from exc

    context_roots_raw: Iterable[str] = runtime.get("context_roots") or []
    context_roots = tuple(_ensure_relative(item, field="runtime.context_roots") for item in context_roots_raw)

    prompt_template = runtime.get("prompt_template")

    prompt_path_abs = (base_dir / prompt_path_rel).resolve()
    output_path_abs = (base_dir / output_path_rel).resolve()
    summary_path_abs = (base_dir / summary_path_rel).resolve()

    prompt_created = False
    if prompt_template is not None:
        prompt_created = _write_if_missing(prompt_path_abs, content=prompt_template.rstrip("\n") + "\n")
    elif not prompt_path_abs.exists():
        raise AgentOnboardingError(
            f"Prompt file {prompt_path_rel} does not exist and no prompt_template provided"
        )

    output_created = _write_if_missing(output_path_abs, content=_placeholder(agent_id, "primary output"))
    summary_created = _write_if_missing(summary_path_abs, content=_placeholder(agent_id, "summary"))

    registry_path = base_dir / "org/_registry" / f"{agent_id}.alou.md"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(text, encoding="utf-8")

    return AgentMaterialization(
        agent_id=agent_id,
        alou_path=registry_path.relative_to(base_dir),
        prompt_path=prompt_path_rel,
        output_path=output_path_rel,
        summary_path=summary_path_rel,
        context_roots=context_roots,
        prompt_created=prompt_created,
        output_created=output_created,
        summary_created=summary_created,
    )
