"""Utilities for deriving agent lifecycle events from governance records."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableSet, Sequence

import yaml

LOGGER = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

SUSPEND_KEYS = (
    "suspend_agents",
    "suspensions",
    "suspended_agents",
    "removed_agents",
    "retired_agents",
    "sanction_agents",
)

REINSTATE_KEYS = (
    "reinstate_agents",
    "restored_agents",
    "reinstated_agents",
    "return_to_service",
    "reactivated_agents",
)


def collect_ballot_lifecycle_events(
    base_dir: Path, processed: MutableSet[str]
) -> tuple[list[dict[str, Any]], MutableSet[str]]:
    """Inspect GEDI tally results for roster changes.

    Returns newly derived lifecycle events and an updated processed set.
    """

    events: list[dict[str, Any]] = []
    logs_dir = base_dir / "logs/gedi"
    if not logs_dir.exists():
        return events, processed

    updated = set(processed)
    for tally_path in sorted(logs_dir.glob("*-tally.json")):
        ballot_id = tally_path.stem.replace("-tally", "")
        if ballot_id in updated:
            continue
        try:
            payload = json.loads(tally_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Unable to parse tally %s: %s", tally_path, exc)
            updated.add(ballot_id)
            continue
        winner = payload.get("winner")
        if not winner:
            updated.add(ballot_id)
            continue
        option_value = _resolve_ballot_option(base_dir, ballot_id, winner)
        if option_value is None:
            updated.add(ballot_id)
            continue
        derived = _interpret_option_value(base_dir, option_value)
        if not derived:
            updated.add(ballot_id)
            continue
        timestamp = _iso_from_mtime(tally_path)
        source = _relpath(base_dir, tally_path)
        for record in derived:
            record.setdefault("t", timestamp)
            record.setdefault("ballot", ballot_id)
            record.setdefault("act_origin", "governance.ballot")
            record.setdefault("source", source)
            events.append(record)
        updated.add(ballot_id)
    return events, updated


def collect_incident_lifecycle_events(
    base_dir: Path, processed: MutableSet[str]
) -> tuple[list[dict[str, Any]], MutableSet[str]]:
    """Derive lifecycle events from incident reports."""

    incidents_dir = base_dir / "org/ops/incident-reports"
    if not incidents_dir.exists():
        return [], processed

    updated = set(processed)
    events: list[dict[str, Any]] = []
    for report_path in sorted(incidents_dir.glob("**/*.md")):
        key = _relpath(base_dir, report_path)
        if key in updated:
            continue
        try:
            text = report_path.read_text(encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("Unable to read incident report %s: %s", report_path, exc)
            updated.add(key)
            continue
        frontmatter = _extract_frontmatter(text)
        incident_events = _interpret_incident(frontmatter, text)
        if incident_events:
            timestamp = _iso_from_mtime(report_path)
            for record in incident_events:
                record.setdefault("t", timestamp)
                record.setdefault("incident", key)
                record.setdefault("act_origin", "ops.incident")
                record.setdefault("source", key)
                events.append(record)
        updated.add(key)
    return events, updated


def _resolve_ballot_option(base_dir: Path, ballot_id: str, winner: str) -> Any:
    """Load the option payload corresponding to the winning outcome."""

    ballot_dir = base_dir / "org/policy/_ballots"
    candidates = [
        ballot_dir / f"{ballot_id}.yaml",
        ballot_dir / f"{ballot_id}.yml",
        ballot_dir / f"{ballot_id}.json",
    ]
    ballot_data: Mapping[str, Any] | None = None
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            if candidate.suffix.lower() == ".json":
                ballot_data = json.loads(candidate.read_text(encoding="utf-8"))
            else:
                ballot_data = yaml.safe_load(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
            LOGGER.warning("Failed to parse ballot spec %s: %s", candidate, exc)
            return None
        break

    if not ballot_data:
        LOGGER.debug("Ballot spec for %s not found", ballot_id)
        return None

    options = ballot_data.get("options")
    if isinstance(options, Mapping):
        return options.get(winner)
    if isinstance(options, Sequence) and not isinstance(options, (str, bytes)):
        # Winner is the option text itself when using list style options.
        return winner
    return None


def _interpret_option_value(base_dir: Path, value: Any) -> list[dict[str, Any]]:
    """Convert a ballot option payload into lifecycle events."""

    events: list[dict[str, Any]] = []

    if value is None:
        return events
    if isinstance(value, Mapping):
        explicit_events = _interpret_structured_option(value)
        if explicit_events:
            return explicit_events
        plural_paths = value.get("paths")
        if plural_paths:
            for item in plural_paths if isinstance(plural_paths, Sequence) else [plural_paths]:
                events.extend(_interpret_option_value(base_dir, item))
            return events
        path_value = value.get("path") or value.get("artifact")
        if path_value:
            return _interpret_option_value(base_dir, path_value)
    if isinstance(value, (list, tuple, set)):
        for item in value:
            events.extend(_interpret_option_value(base_dir, item))
        return events
    if isinstance(value, Path):
        return _interpret_option_value(base_dir, str(value))
    if isinstance(value, str):
        text = value.strip()
        directive = _interpret_directive(text)
        if directive:
            return [directive]
        path = _coerce_path(base_dir, text)
        if path and path.exists():
            if path.suffix.lower() in {".md", ".markdown"}:
                return _interpret_markdown(path, base_dir)
            if path.suffix.lower() in {".yaml", ".yml", ".json"}:
                try:
                    data = yaml.safe_load(path.read_text(encoding="utf-8"))
                except (OSError, yaml.YAMLError):
                    return events
                return _interpret_option_value(base_dir, data)
        if _looks_like_agent(text):
            return [
                {
                    "act": "governance.add_agent",
                    "agent": text,
                    "reason": "ballot",
                }
            ]
    return events


def _interpret_structured_option(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    action = str(data.get("action", "")).lower()
    agent = data.get("agent") or data.get("agent_id")
    if action and agent and _looks_like_agent(str(agent)):
        if action in {"add_agent", "recruit", "reinstate", "activate"}:
            return [
                {
                    "act": "governance.add_agent",
                    "agent": str(agent),
                    "reason": data.get("reason", "ballot"),
                    "details": data,
                }
            ]
        if action in {"remove_agent", "fire", "retire", "suspend"}:
            return [
                {
                    "act": "governance.remove_agent",
                    "agent": str(agent),
                    "reason": data.get("reason", "ballot"),
                    "details": data,
                }
            ]
    return []


def _interpret_directive(text: str) -> dict[str, Any] | None:
    match = re.match(r"(?i)agent:(add|remove|reinstate|suspend):(?P<agent>AGENT-[A-Za-z0-9_-]+)", text)
    if not match:
        return None
    action = match.group(1).lower()
    agent = match.group("agent")
    if action in {"add", "reinstate"}:
        return {
            "act": "governance.add_agent",
            "agent": agent,
            "reason": "ballot",
        }
    if action in {"remove", "suspend"}:
        return {
            "act": "governance.remove_agent",
            "agent": agent,
            "reason": "ballot",
        }
    return None


def _interpret_markdown(path: Path, base_dir: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    frontmatter = _extract_frontmatter(text)
    agent_id = frontmatter.get("agent_id") or _agent_from_filename(path)
    if not agent_id:
        return []
    status = str(frontmatter.get("status", "active")).lower()
    act = "governance.add_agent"
    if status in {"retired", "inactive", "removed", "terminated"}:
        act = "governance.remove_agent"
    reason = frontmatter.get("status_reason") or frontmatter.get("note") or "ballot"
    return [
        {
            "act": act,
            "agent": agent_id,
            "reason": reason,
            "artifact": _relpath(base_dir, path),
        }
    ]


def _interpret_incident(frontmatter: Mapping[str, Any], text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    for key in SUSPEND_KEYS:
        events.extend(
            _render_lifecycle_events(frontmatter.get(key), "governance.remove_agent", f"incident:{key}")
        )
    for key in REINSTATE_KEYS:
        events.extend(
            _render_lifecycle_events(frontmatter.get(key), "governance.add_agent", f"incident:{key}")
        )

    pattern = re.compile(r"@lifecycle\s+(add|remove|suspend|reinstate)\s+(AGENT-[A-Za-z0-9_-]+)", re.IGNORECASE)
    for match in pattern.finditer(text):
        action = match.group(1).lower()
        agent = match.group(2)
        if action in {"add", "reinstate"}:
            events.append({"act": "governance.add_agent", "agent": agent, "reason": "incident:marker"})
        else:
            events.append({"act": "governance.remove_agent", "agent": agent, "reason": "incident:marker"})
    return events


def _render_lifecycle_events(value: Any, act: str, reason: str) -> list[dict[str, Any]]:
    agents = _normalise_agent_list(value)
    return [
        {
            "act": act,
            "agent": agent,
            "reason": reason,
        }
        for agent in agents
    ]


def _normalise_agent_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r"[,\n]", value) if part.strip()]
        return [part for part in parts if _looks_like_agent(part)]
    if isinstance(value, Mapping):
        return _normalise_agent_list(value.get("agents") or value.get("ids"))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        agents: list[str] = []
        for item in value:
            agents.extend(_normalise_agent_list(item))
        return agents
    return []


def _extract_frontmatter(text: str) -> Mapping[str, Any]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, Mapping) else {}


def _agent_from_filename(path: Path) -> str | None:
    match = re.search(r"(AGENT-[A-Za-z0-9_-]+)", path.name)
    return match.group(1) if match else None


def _looks_like_agent(value: str) -> bool:
    return bool(re.fullmatch(r"AGENT-[A-Za-z0-9_-]+", value or ""))


def _iso_from_mtime(path: Path) -> str:
    ts = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return ts.isoformat().replace("+00:00", "Z")


def _coerce_path(base_dir: Path, value: str) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = (base_dir / candidate).resolve()
    return candidate


def _relpath(base_dir: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(base_dir.resolve()))
    except ValueError:
        return str(path.resolve())
