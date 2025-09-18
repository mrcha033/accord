"""Experiment loop primitives for long-running autonomous agent observations."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, MutableSet, Sequence

import yaml

from orchestrator.runtime import run_all
from orchestrator.governance import (
    collect_ballot_lifecycle_events,
    collect_incident_lifecycle_events,
)
from scripts.runtime_guard import RuntimeGuard

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TimelineSpec:
    """Execution cadence controls for looped experiments."""

    max_rounds: int = 1
    cadence_minutes: int | None = None
    resume: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "TimelineSpec":
        if not data:
            return cls()
        max_rounds = int(data.get("max_rounds", 1))
        cadence_raw = data.get("cadence_minutes")
        cadence_minutes = None if cadence_raw in (None, "", 0) else int(cadence_raw)
        resume = bool(data.get("resume", True))
        return cls(max_rounds=max_rounds, cadence_minutes=cadence_minutes, resume=resume)


@dataclass(slots=True)
class LifecycleSpec:
    """Configuration for automatic roster adjustments."""

    max_agents: int | None = None
    probation_rounds: int = 0
    evaluation_window: int = 3

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "LifecycleSpec":
        if not data:
            return cls()
        max_agents_raw = data.get("max_agents")
        max_agents = None if max_agents_raw in (None, "") else int(max_agents_raw)
        probation_rounds = int(data.get("probation_rounds", 0))
        evaluation_window = int(data.get("evaluation_window", 3))
        return cls(
            max_agents=max_agents,
            probation_rounds=probation_rounds,
            evaluation_window=evaluation_window,
        )


@dataclass(slots=True)
class AutoBallotConfig:
    enabled: bool = False
    cadence_rounds: int = 0
    electorate: list[str] = field(default_factory=list)
    options: Mapping[str, str] = field(default_factory=lambda: {"ADD": "agent:add:AGENT-RISK01", "NONE": "retain-current-roster"})
    title: str = "Autonomous governance adjustment"
    proposal_materials: list[str] = field(default_factory=list)
    vote_rankings: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "AutoBallotConfig":
        if not data:
            return cls()
        enabled = bool(data.get("enabled", False))
        cadence = int(data.get("cadence_rounds", 0) or 0)
        electorate_raw = data.get("electorate")
        electorate: list[str] = []
        if isinstance(electorate_raw, Sequence) and not isinstance(electorate_raw, (str, bytes)):
            electorate = [str(item) for item in electorate_raw]
        options_raw = data.get("options")
        if isinstance(options_raw, Mapping):
            options = {str(k): str(v) for k, v in options_raw.items()}
        else:
            options = {"ADD": "agent:add:AGENT-RISK01", "NONE": "retain-current-roster"}
        title = str(data.get("title", "Autonomous governance adjustment"))
        materials_raw = data.get("proposal_materials")
        proposal_materials: list[str] = []
        if isinstance(materials_raw, Sequence) and not isinstance(materials_raw, (str, bytes)):
            proposal_materials = [str(item) for item in materials_raw]
        votes_raw = data.get("vote_rankings")
        if isinstance(votes_raw, Mapping):
            vote_rankings = {str(k): str(v) for k, v in votes_raw.items()}
        else:
            vote_rankings = {}
        return cls(
            enabled=enabled,
            cadence_rounds=cadence,
            electorate=electorate,
            options=options,
            title=title,
            proposal_materials=proposal_materials,
            vote_rankings=vote_rankings,
        )


@dataclass(slots=True)
class ExperimentState:
    """Persisted state for multi-round experiment execution."""

    round: int = 0
    roster: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        initial_roster: Sequence[str],
        resume: bool,
    ) -> "ExperimentState":
        if resume and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                LOGGER.warning("State file %s is corrupted; starting fresh", path)
            else:
                return cls(
                    round=int(data.get("round", 0)),
                    roster=list(data.get("roster", list(initial_roster))),
                    retired=list(data.get("retired", [])),
                    created=list(data.get("created", [])),
                    metrics=dict(data.get("metrics", {})),
                    history=list(data.get("history", [])),
                )
        return cls(round=0, roster=list(initial_roster))


@dataclass(slots=True)
class RoundSummary:
    """Lightweight summary of a completed experiment round."""

    round: int
    started_at: str
    completed_at: str
    agents: list[str]
    event_count: int
    event_types: dict[str, int]
    communications: dict[str, int]
    outputs: list[dict[str, str]]
    events_path: str
    lifecycle_actions: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_round_results(
    *,
    guard: RuntimeGuard,
    root: Path,
    metadata: Dict[str, Any],
    agent_runs: Sequence[Dict[str, Any]],
) -> Path:
    """Store per-round metadata, results CSV, and fallback events."""

    root_relative = Path(root.relative_to(guard.fs.base_dir)) if hasattr(guard.fs, "base_dir") else root
    guard.fs.write_text(root_relative / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

    events_path = root_relative / "events.jsonl"
    events_target = guard.fs.base_dir / events_path if hasattr(guard.fs, "base_dir") else events_path
    if not events_target.exists():
        rows: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for run in agent_runs:
            event = {
                "t": now,
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

    return Path(events_path)


class ExperimentLoop:
    """Coordinator for multi-round autonomous experiments."""

    def __init__(
        self,
        *,
        base_dir: Path,
        guard: RuntimeGuard,
        output_root: Path,
        timeline: TimelineSpec,
        lifecycle: LifecycleSpec,
        auto_ballot: AutoBallotConfig,
        seed: int,
        spec_metadata: Mapping[str, Any],
    ) -> None:
        self.base_dir = base_dir
        self.guard = guard
        self.output_root = output_root
        self.timeline = timeline
        self.lifecycle = lifecycle
        self.auto_ballot = auto_ballot
        self.seed = seed
        self.spec_metadata = dict(spec_metadata)

        self.output_root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.output_root / "state.json"
        self.state = ExperimentState.load(
            self.state_path,
            initial_roster=self.spec_metadata.get("agents", []),
            resume=self.timeline.resume,
        )
        self.timeline_path = self.output_root / "timeline.jsonl"
        metrics = self.state.metrics or {}
        self._processed_ballots: MutableSet[str] = set(metrics.get("processed_ballots", []))
        self._processed_incidents: MutableSet[str] = set(metrics.get("processed_incidents", []))
        governance_cfg = self.spec_metadata.get("governance", {})
        self._governance_rule = str(governance_cfg.get("rule", "condorcet"))
        try:
            self._governance_quorum = float(governance_cfg.get("quorum", 0.0))
        except (TypeError, ValueError):
            self._governance_quorum = 0.0

    def run(self) -> dict[str, Any]:
        """Execute rounds until max_rounds reached or roster exhausted."""

        summaries: list[RoundSummary] = []
        while self._should_continue():
            round_number = self.state.round + 1
            round_dir = self.output_root / f"round-{round_number:04d}"
            round_dir.mkdir(parents=True, exist_ok=True)

            started_at = datetime.now(timezone.utc)
            results = run_all(self.state.roster or None, base_dir=self.base_dir, events_path=round_dir / "events.jsonl")

            metadata = {
                **self.spec_metadata,
                "round": round_number,
                "seed": self.seed,
                "started_at": started_at.isoformat(timespec="seconds"),
            }
            events_path = write_round_results(
                guard=self.guard,
                root=round_dir,
                metadata=metadata,
                agent_runs=results,
            )
            self._maybe_generate_ballot(round_number, results)
            self._append_governance_events(events_path)

            completed_at = datetime.now(timezone.utc)
            summary = self._build_summary(
                round_number=round_number,
                started_at=started_at,
                completed_at=completed_at,
                events_path=self.base_dir / events_path,
                results=results,
            )
            summaries.append(summary)
            self._append_timeline_entry(summary)
            self._update_state(summary)

            if self.timeline.cadence_minutes:
                self._sleep_until_next_round(started_at)

        manifest = {
            "rounds_completed": self.state.round,
            "roster": list(self.state.roster),
            "created": list(self.state.created),
            "retired": list(self.state.retired),
            "metrics": dict(self.state.metrics),
            "processed_ballots": sorted(self._processed_ballots),
            "processed_incidents": sorted(self._processed_incidents),
            "rounds": [summary.to_dict() for summary in summaries],
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        manifest_path = self.output_root / "experiment.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "state_path": str(self.state_path),
            "timeline_path": str(self.timeline_path),
            "manifest_path": str(manifest_path),
            "rounds": [summary.to_dict() for summary in summaries],
        }

    def _should_continue(self) -> bool:
        if not self.state.roster:
            LOGGER.info("Roster empty at round %s; stopping experiment", self.state.round)
            return False
        if self.state.round >= self.timeline.max_rounds:
            return False
        return True

    def _build_summary(
        self,
        *,
        round_number: int,
        started_at: datetime,
        completed_at: datetime,
        events_path: Path,
        results: Sequence[Dict[str, Any]],
    ) -> RoundSummary:
        events: list[dict[str, Any]] = []
        try:
            for line in events_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    LOGGER.debug("Skipping malformed event line in %s", events_path)
        except FileNotFoundError:
            LOGGER.warning("Events log %s missing; summary will be sparse", events_path)

        event_types: dict[str, int] = {}
        communications: dict[str, int] = {}
        lifecycle_actions: list[dict[str, Any]] = []
        for event in events:
            act = str(event.get("act", "unknown"))
            agent = str(event.get("agent", "")) or "unknown"
            event_types[act] = event_types.get(act, 0) + 1
            if act in {"message", "notify", "escalate"} and agent != "unknown":
                communications[agent] = communications.get(agent, 0) + 1
            if act in {"roster.add", "roster.remove", "governance.add_agent", "governance.remove_agent"}:
                lifecycle_actions.append(event)

        summary = RoundSummary(
            round=round_number,
            started_at=started_at.isoformat(timespec="seconds"),
            completed_at=completed_at.isoformat(timespec="seconds"),
            agents=[run["agent_id"] for run in results],
            event_count=len(events),
            event_types=event_types,
            communications=communications,
            outputs=[
                {
                    "agent_id": run["agent_id"],
                    "artifact": run["output"],
                    "summary": run["summary"],
                    "attestation": run["attestation"],
                }
                for run in results
            ],
            events_path=events_path.as_posix(),
            lifecycle_actions=lifecycle_actions,
        )
        return summary

    def _append_timeline_entry(self, summary: RoundSummary) -> None:
        line = json.dumps(summary.to_dict(), ensure_ascii=False)
        mode = "a" if self.timeline_path.exists() else "w"
        with self.timeline_path.open(mode, encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _update_state(self, summary: RoundSummary) -> None:
        self.state.round = summary.round
        self.state.history.append(
            {
                "round": summary.round,
                "event_count": summary.event_count,
                "event_types": summary.event_types,
                "communications": summary.communications,
                "lifecycle_actions": summary.lifecycle_actions,
            }
        )
        total_events = self.state.metrics.get("total_events", 0) + summary.event_count
        self.state.metrics["total_events"] = total_events
        self.state.metrics["last_completed_at"] = summary.completed_at
        self._apply_lifecycle(summary)
        self.state.metrics["processed_ballots"] = sorted(self._processed_ballots)
        self.state.metrics["processed_incidents"] = sorted(self._processed_incidents)
        self.state.save(self.state_path)

    def _sleep_until_next_round(self, started_at: datetime) -> None:
        cadence = self.timeline.cadence_minutes
        if not cadence:
            return
        wake_time = started_at + timedelta(minutes=cadence)
        now = datetime.now(timezone.utc)
        if wake_time <= now:
            return
        delay = (wake_time - now).total_seconds()
        LOGGER.debug("Sleeping %.1f seconds until next scheduled round", delay)
        try:
            import time

            time.sleep(delay)
        except Exception:  # pragma: no cover - sleep interruptions
            LOGGER.debug("Sleep interrupted; continuing immediately")

    def _maybe_generate_ballot(
        self, round_number: int, results: Sequence[Dict[str, Any]]
    ) -> None:
        if not self.auto_ballot.enabled:
            return
        cadence = self.auto_ballot.cadence_rounds
        if cadence <= 0 or round_number % cadence != 0:
            return
        pm_result = next((item for item in results if item.get("agent_id") == "AGENT-PM01"), None)
        if not pm_result:
            LOGGER.debug("Auto ballot skipped: AGENT-PM01 result not found for round %s", round_number)
            return
        key_path = self.base_dir / "keys/ed25519.key"
        if not key_path.exists():
            LOGGER.warning("Auto ballot skipped: private key missing at %s", key_path)
            return
        electorate = self.auto_ballot.electorate or list(self.state.roster)
        if not electorate:
            LOGGER.debug("Auto ballot skipped: electorate empty")
            return
        if not self.auto_ballot.options:
            LOGGER.debug("Auto ballot skipped: no options configured")
            return
        now = datetime.now(timezone.utc)
        ballot_id = now.strftime("%Y%m%dT%H%M%S-auto")
        ballots_dir = self.base_dir / "org/policy/_ballots"
        ballots_dir.mkdir(parents=True, exist_ok=True)
        ballot_path = ballots_dir / f"{ballot_id}.yaml"

        materials = list(self.auto_ballot.proposal_materials)
        if not materials:
            materials = [pm_result.get("output"), pm_result.get("summary")]
        else:
            materials.extend([pm_result.get("output"), pm_result.get("summary")])
        materials_norm = [
            path
            for path in (self._normalise_material_path(item) for item in materials if item)
            if path
        ]
        window_end = now + timedelta(hours=4)
        ballot_data = {
            "id": ballot_id,
            "title": self.auto_ballot.title,
            "rule": self._governance_rule,
            "quorum": self._governance_quorum,
            "electorate": electorate,
            "options": dict(self.auto_ballot.options),
            "proposal_materials": materials_norm,
            "window": {
                "start": now.isoformat().replace("+00:00", "Z"),
                "end": window_end.isoformat().replace("+00:00", "Z"),
            },
        }
        try:
            ballot_path.write_text(yaml.safe_dump(ballot_data, sort_keys=False), encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("Failed to write auto ballot %s: %s", ballot_path, exc)
            return

        if not self._run_ballot_pipeline(ballot_path, ballot_id, electorate):
            return
        LOGGER.info("Auto-generated ballot %s at %s", ballot_id, ballot_path)

    def _normalise_material_path(self, value: str | None) -> str:
        if not value:
            return ""
        candidate = Path(value)
        if not candidate.is_absolute():
            return candidate.as_posix()
        try:
            return candidate.relative_to(self.base_dir).as_posix()
        except ValueError:
            return candidate.as_posix()

    def _run_ballot_pipeline(
        self, ballot_path: Path, ballot_id: str, electorate: Sequence[str]
    ) -> bool:
        try:
            ballot_arg = ballot_path.relative_to(self.base_dir).as_posix()
        except ValueError:
            ballot_arg = ballot_path.as_posix()
        commands = [
            [sys.executable, "-m", "scripts.gedi_ballot", "propose", ballot_arg],
        ]
        options_order = list(self.auto_ballot.options.keys())
        default_ranking = ">".join(options_order) if options_order else ""
        vote_rankings = dict(self.auto_ballot.vote_rankings)
        for agent in electorate:
            ranking = vote_rankings.get(agent, default_ranking)
            if not ranking:
                continue
            commands.append(
                [
                    sys.executable,
                    "-m",
                    "scripts.gedi_ballot",
                    "vote",
                    ballot_id,
                    "--agent",
                    agent,
                    "--ranking",
                    ranking,
                ]
            )
        commands.append([sys.executable, "-m", "scripts.gedi_ballot", "tally", ballot_id])
        commands.append([sys.executable, "-m", "scripts.gedi_ballot", "adopt", ballot_id])

        env = os.environ.copy()
        for cmd in commands:
            try:
                subprocess.run(cmd, check=True, cwd=self.base_dir, env=env)
            except subprocess.CalledProcessError as exc:
                LOGGER.warning("Auto ballot command failed (%s): %s", " ".join(cmd), exc)
                return False
        return True

    def _append_governance_events(self, events_path: Path) -> list[dict[str, Any]]:
        absolute = events_path if events_path.is_absolute() else (self.base_dir / events_path)
        ballot_events, self._processed_ballots = collect_ballot_lifecycle_events(
            self.base_dir, self._processed_ballots
        )
        incident_events, self._processed_incidents = collect_incident_lifecycle_events(
            self.base_dir, self._processed_incidents
        )
        records = ballot_events + incident_events
        if not records:
            return []
        absolute.parent.mkdir(parents=True, exist_ok=True)
        with absolute.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        LOGGER.info(
            "Appended %s governance lifecycle events to %s",
            len(records),
            absolute,
        )
        return records

    def _apply_lifecycle(self, summary: RoundSummary) -> None:
        """Adjust roster based on lifecycle actions and spec limits."""

        changes_made = False
        for action in summary.lifecycle_actions:
            act = str(action.get("act"))
            target = str(action.get("target") or action.get("agent_id") or action.get("agent"))
            if not target:
                continue
            if act in {"roster.add", "governance.add_agent"}:
                if target not in self.state.roster:
                    self.state.roster.append(target)
                    self.state.created.append(target)
                    changes_made = True
            elif act in {"roster.remove", "governance.remove_agent"}:
                if target in self.state.roster:
                    self.state.roster.remove(target)
                    self.state.retired.append(target)
                    changes_made = True

        if (
            self.lifecycle.max_agents is not None
            and len(self.state.roster) > self.lifecycle.max_agents
        ):
            overflow = self.state.roster[self.lifecycle.max_agents :]
            if overflow:
                LOGGER.info("Trimming roster to max_agents=%s", self.lifecycle.max_agents)
            for agent_id in overflow:
                if agent_id in self.state.roster:
                    self.state.roster.remove(agent_id)
                    self.state.retired.append(agent_id)
                    changes_made = True

        if changes_made:
            LOGGER.info("Roster updated: %s", ", ".join(self.state.roster))
