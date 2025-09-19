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

from orchestrator.onboarding import AgentOnboardingError, materialize_agent
from orchestrator.runtime import load_alou_data, load_registered_agent_configs, run_all
from orchestrator.governance import (
    collect_ballot_lifecycle_events,
    collect_incident_lifecycle_events,
    detect_voting_coalitions,
    calculate_influence_metrics,
    update_trust_matrix,
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
        max_rounds_raw = data.get("max_rounds", 1)
        max_rounds = int(max_rounds_raw) if isinstance(max_rounds_raw, (int, str)) else 1
        cadence_raw = data.get("cadence_minutes")
        cadence_minutes = None if cadence_raw in (None, "", 0) else int(cadence_raw) if isinstance(cadence_raw, (int, str)) else None
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
        max_agents = None if max_agents_raw in (None, "") else int(max_agents_raw) if isinstance(max_agents_raw, (int, str)) else None
        probation_rounds_raw = data.get("probation_rounds", 0)
        probation_rounds = int(probation_rounds_raw) if isinstance(probation_rounds_raw, (int, str)) else 0
        evaluation_window_raw = data.get("evaluation_window", 3)
        evaluation_window = int(evaluation_window_raw) if isinstance(evaluation_window_raw, (int, str)) else 3
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
    options: Mapping[str, Any] = field(
        default_factory=lambda: {
            "ADD": "agent:add:AGENT-RISK01",
            "NONE": "retain-current-roster",
        }
    )
    title: str = "Autonomous governance adjustment"
    proposal_materials: list[str] = field(default_factory=list)
    vote_rankings: Mapping[str, str] = field(default_factory=dict)
    discover_proposals: bool = False
    retain_agents: list[str] = field(default_factory=list)
    # Enhanced features
    byzantine_tolerance: float = 0.33
    coalition_detection: bool = True
    trust_tracking: bool = True
    dynamic_voting: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "AutoBallotConfig":
        if not data:
            return cls()
        enabled = bool(data.get("enabled", False))
        cadence_raw = data.get("cadence_rounds")
        cadence = int(cadence_raw) if isinstance(cadence_raw, (int, str)) and cadence_raw else 0
        electorate_raw = data.get("electorate")
        electorate: list[str] = []
        if isinstance(electorate_raw, Sequence) and not isinstance(electorate_raw, (str, bytes)):
            electorate = [str(item) for item in electorate_raw]
        options_raw = data.get("options")
        if isinstance(options_raw, Mapping):
            options = {str(k): options_raw[k] for k in options_raw.keys()}
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
        discover = bool(data.get("discover_proposals", False))
        retain_raw = data.get("retain_agents")
        retain_agents: list[str] = []
        if isinstance(retain_raw, Sequence) and not isinstance(retain_raw, (str, bytes)):
            retain_agents = [str(item) for item in retain_raw]
        return cls(
            enabled=enabled,
            cadence_rounds=cadence,
            electorate=electorate,
            options=options,
            title=title,
            proposal_materials=proposal_materials,
            vote_rankings=vote_rankings,
            discover_proposals=discover,
            retain_agents=retain_agents,
            byzantine_tolerance=float(data.get("byzantine_tolerance", 0.33) or 0.33),
            coalition_detection=bool(data.get("coalition_detection", True)),
            trust_tracking=bool(data.get("trust_tracking", True)),
            dynamic_voting=bool(data.get("dynamic_voting", False)),
        )


@dataclass(slots=True)
class EconomicConfig:
    """Configuration for agent economic system."""

    enabled: bool = False
    starting_balance: int = 1000
    compute_cost: int = 10
    file_write_cost: int = 5
    search_cost: int = 2
    task_completion_reward: int = 100
    governance_participation_reward: int = 25

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "EconomicConfig":
        if not data:
            return cls()
        starting_balance_raw = data.get("starting_balance", 1000)
        starting_balance = int(starting_balance_raw) if isinstance(starting_balance_raw, (int, str)) else 1000
        compute_cost_raw = data.get("compute_cost", 10)
        compute_cost = int(compute_cost_raw) if isinstance(compute_cost_raw, (int, str)) else 10
        file_write_cost_raw = data.get("file_write_cost", 5)
        file_write_cost = int(file_write_cost_raw) if isinstance(file_write_cost_raw, (int, str)) else 5
        search_cost_raw = data.get("search_cost", 2)
        search_cost = int(search_cost_raw) if isinstance(search_cost_raw, (int, str)) else 2
        task_completion_reward_raw = data.get("task_completion_reward", 100)
        task_completion_reward = int(task_completion_reward_raw) if isinstance(task_completion_reward_raw, (int, str)) else 100
        governance_participation_reward_raw = data.get("governance_participation_reward", 25)
        governance_participation_reward = int(governance_participation_reward_raw) if isinstance(governance_participation_reward_raw, (int, str)) else 25

        return cls(
            enabled=bool(data.get("enabled", False)),
            starting_balance=starting_balance,
            compute_cost=compute_cost,
            file_write_cost=file_write_cost,
            search_cost=search_cost,
            task_completion_reward=task_completion_reward,
            governance_participation_reward=governance_participation_reward,
        )


@dataclass(slots=True)
class CrisisEvent:
    """A crisis event that affects the organization."""

    event_type: str
    trigger_round: int
    severity: float
    duration: int
    effects: Mapping[str, Any]
    active: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "CrisisEvent":
        trigger_round_raw = data.get("trigger_round", 1)
        trigger_round = int(trigger_round_raw) if isinstance(trigger_round_raw, (int, str)) else 1
        severity_raw = data.get("severity", 0.5)
        severity = float(severity_raw) if isinstance(severity_raw, (int, float, str)) else 0.5
        duration_raw = data.get("duration", 1)
        duration = int(duration_raw) if isinstance(duration_raw, (int, str)) else 1
        effects_raw = data.get("effects", {})
        effects = dict(effects_raw) if isinstance(effects_raw, Mapping) else {}

        return cls(
            event_type=str(data.get("type", "unknown")),
            trigger_round=trigger_round,
            severity=severity,
            duration=duration,
            effects=effects,
        )


@dataclass(slots=True)
class CrisisConfig:
    """Configuration for crisis simulation."""

    enabled: bool = False
    events: list[CrisisEvent] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "CrisisConfig":
        if not data:
            return cls()
        events = []
        events_raw = data.get("events", [])
        if isinstance(events_raw, Sequence):
            for event_data in events_raw:
                if isinstance(event_data, Mapping):
                    events.append(CrisisEvent.from_mapping(event_data))
        return cls(
            enabled=bool(data.get("enabled", False)),
            events=events,
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
    # Enhanced features
    agent_balances: dict[str, int] = field(default_factory=dict)
    active_crises: list[str] = field(default_factory=list)
    coalition_history: list[dict[str, Any]] = field(default_factory=list)
    trust_matrix: dict[str, dict[str, float]] = field(default_factory=dict)

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
        economics: EconomicConfig | None = None,
        crisis_config: CrisisConfig | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.guard = guard
        self.output_root = output_root
        self.timeline = timeline
        self.lifecycle = lifecycle
        self.auto_ballot = auto_ballot
        self.seed = seed
        self.spec_metadata = dict(spec_metadata)
        self.economics = economics or EconomicConfig()
        self.crisis_config = crisis_config or CrisisConfig()

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

    def _process_crisis_events(self) -> None:
        """Process and activate crisis events for current round."""
        if not self.crisis_config.enabled:
            return

        current_round = self.state.round

        for event in self.crisis_config.events:
            # Check if event should trigger this round
            if event.trigger_round == current_round and not event.active:
                event.active = True
                self.state.active_crises.append(event.event_type)

                # Log crisis activation
                crisis_log = {
                    "round": current_round,
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "duration": event.duration,
                    "effects": dict(event.effects)
                }
                LOGGER.info("Crisis activated: %s", crisis_log)

                # Log crisis event to timeline
                crisis_record = {
                    "t": datetime.now(timezone.utc).isoformat(),
                    "act": "crisis.activated",
                    "event_type": event.event_type,
                    "severity": event.severity,
                    "duration": event.duration,
                    "effects": dict(event.effects),
                }
                with self.timeline_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(crisis_record, ensure_ascii=False) + "\n")

                # Apply crisis effects immediately
                self._apply_crisis_effects(event)

            # Check if event should end
            elif event.active and current_round >= (event.trigger_round + event.duration):
                event.active = False
                if event.event_type in self.state.active_crises:
                    self.state.active_crises.remove(event.event_type)
                LOGGER.info("Crisis ended: %s", event.event_type)

    def _apply_crisis_effects(self, event: CrisisEvent) -> None:
        """Apply effects of a crisis event."""
        effects = event.effects

        # Economic effects
        if self.economics.enabled and "budget_reduction" in effects:
            reduction_factor = float(effects["budget_reduction"])
            for agent in self.state.agent_balances:
                current_balance = self.state.agent_balances[agent]
                new_balance = int(current_balance * (1.0 - reduction_factor))
                self.state.agent_balances[agent] = max(0, new_balance)

        # Trust degradation
        if "trust_degradation" in effects and self.auto_ballot.trust_tracking:
            degradation_factor = float(effects["trust_degradation"])
            for agent1 in self.state.trust_matrix:
                for agent2 in self.state.trust_matrix[agent1]:
                    current_trust = self.state.trust_matrix[agent1][agent2]
                    new_trust = max(0.0, current_trust - degradation_factor)
                    self.state.trust_matrix[agent1][agent2] = new_trust

    def _initialize_agent_economics(self) -> None:
        """Initialize economic state for new agents."""
        if not self.economics.enabled:
            return

        for agent in self.state.roster:
            if agent not in self.state.agent_balances:
                self.state.agent_balances[agent] = self.economics.starting_balance

    def _log_economic_transaction(self, events_path: Path, agent: str, amount: int, reason: str) -> None:
        """Log an economic transaction to the events file."""
        if not self.economics.enabled:
            return

        # Update balance
        current_balance = self.state.agent_balances.get(agent, 0)
        new_balance = max(0, current_balance + amount)
        self.state.agent_balances[agent] = new_balance

        # Log transaction
        transaction_record = {
            "t": datetime.now(timezone.utc).isoformat(),
            "act": "economic.balance_change",
            "agent": agent,
            "balance_change": amount,
            "reason": reason,
            "new_balance": new_balance,
        }

        absolute = events_path if events_path.is_absolute() else (self.base_dir / events_path)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        with absolute.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(transaction_record, ensure_ascii=False) + "\n")

    def run(self) -> dict[str, Any]:
        """Execute rounds until max_rounds reached or roster exhausted."""

        summaries: list[RoundSummary] = []
        while self._should_continue():
            round_number = self.state.round + 1
            round_dir = self.output_root / f"round-{round_number:04d}"
            round_dir.mkdir(parents=True, exist_ok=True)

            # Process crisis events at start of round
            self._process_crisis_events()

            # Initialize economics for new agents
            self._initialize_agent_economics()

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
        self._update_activity_metrics(summary)
        self._apply_lifecycle(summary)
        self.state.metrics["processed_ballots"] = sorted(self._processed_ballots)
        self.state.metrics["processed_incidents"] = sorted(self._processed_incidents)
        self.state.save(self.state_path)

    def _update_activity_metrics(self, summary: RoundSummary) -> None:
        activity = self.state.metrics.setdefault("agent_activity", {})
        window = max(self.lifecycle.evaluation_window, 1)
        outputs = {entry["agent_id"] for entry in summary.outputs}
        tracked_agents = set(self.state.roster) | outputs
        for agent in tracked_agents:
            history = activity.setdefault(agent, [])
            history.append(1 if agent in outputs else 0)
            if len(history) > window:
                del history[0]
        # prune entries for agents no longer active
        inactive = [agent for agent in activity.keys() if agent not in tracked_agents]
        for agent in inactive:
            history = activity.get(agent, [])
            if len(history) > window:
                activity[agent] = history[-window:]

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
        options = self._compose_auto_ballot_options()
        if not options:
            LOGGER.debug("Auto ballot skipped: no options available")
            return
        electorate = self._compose_auto_ballot_electorate()
        if not electorate:
            LOGGER.debug("Auto ballot skipped: electorate empty")
            return
        if not self._auto_ballot_needs_action(options):
            LOGGER.debug("Auto ballot skipped: all option targets already satisfied")
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
            materials.extend([item for item in [pm_result.get("output"), pm_result.get("summary")] if item is not None])
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
            "options": dict(options),
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

        if not self._run_ballot_pipeline(ballot_path, ballot_id, electorate, options):
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
        self,
        ballot_path: Path,
        ballot_id: str,
        electorate: Sequence[str],
        options: Mapping[str, Any],
    ) -> bool:
        try:
            ballot_arg = ballot_path.relative_to(self.base_dir).as_posix()
        except ValueError:
            ballot_arg = ballot_path.as_posix()
        commands = [
            [sys.executable, "-m", "scripts.gedi_ballot", "propose", ballot_arg],
        ]
        options_order = list(options.keys())
        default_ranking = ">".join(options_order) if options_order else ""
        # Dynamic voting: replace hardcoded rankings with contextual decision-making
        if hasattr(self.auto_ballot, 'dynamic_voting') and self.auto_ballot.dynamic_voting:
            for agent in electorate:
                ranking = self._generate_dynamic_vote_ranking(agent, options, options_order)
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
        else:
            # Fallback to hardcoded rankings if dynamic voting is disabled
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

        env = os.environ.copy()
        for cmd in commands:
            try:
                subprocess.run(cmd, check=True, cwd=self.base_dir, env=env)
            except subprocess.CalledProcessError as exc:
                LOGGER.warning("Auto ballot command failed (%s): %s", " ".join(cmd), exc)
                return False

        adopt_cmd = self._build_adopt_command(ballot_id)
        if adopt_cmd:
            try:
                subprocess.run(adopt_cmd, check=True, cwd=self.base_dir, env=env)
            except subprocess.CalledProcessError as exc:
                LOGGER.warning("Auto ballot adoption failed (%s): %s", " ".join(adopt_cmd), exc)
                return False
        return True

    def _generate_dynamic_vote_ranking(self, agent: str, options: Mapping[str, Any], options_order: list[str]) -> str:
        """Generate dynamic vote ranking based on organizational context and agent reasoning."""
        if not options_order:
            return ""

        # Analyze organizational context
        crisis_active = any(
            event.active
            for event in self.crisis_config.events
            if self.crisis_config.enabled
        )

        # Get agent-specific context
        current_roster_size = len(self.state.roster)
        agent_balance = self.state.agent_balances.get(agent, 0) if self.economics.enabled else 1000
        budget_stressed = agent_balance < (self.economics.starting_balance * 0.5) if self.economics.enabled else False

        # Analyze options and make autonomous decision
        scored_options = []
        for option_key in options_order:
            score = self._score_option_for_agent(agent, option_key, options[option_key], {
                "crisis_active": crisis_active,
                "budget_stressed": budget_stressed,
                "roster_size": current_roster_size,
                "agent_balance": agent_balance
            })
            scored_options.append((option_key, score))

        # Sort by score (highest first) and create ranking
        scored_options.sort(key=lambda x: x[1], reverse=True)
        ranking = ">".join([option[0] for option in scored_options])

        LOGGER.info(
            "Agent %s autonomous decision: %s (context: crisis=%s, budget_stressed=%s, roster=%d)",
            agent, ranking, crisis_active, budget_stressed, current_roster_size
        )

        return ranking

    def _score_option_for_agent(self, agent: str, option_key: str, option_value: Any, context: dict[str, Any]) -> float:
        """Score a ballot option from an agent's perspective based on organizational context."""
        base_score = 0.5  # Neutral baseline

        # Handle NONE (status quo) option
        if option_key == "NONE" or self._is_noop_option(option_value):
            # During crisis, status quo gets negative score (need change)
            if context["crisis_active"]:
                base_score = 0.2  # Prefer change during crisis
            else:
                base_score = 0.6  # Slight preference for stability normally
            return base_score

        # Analyze add_agent options
        action, target_agent = self._interpret_option_action(option_value)
        if action == "add" and target_agent:
            # Adding agents during crisis is generally good (more help)
            if context["crisis_active"]:
                base_score = 0.8
            else:
                base_score = 0.7

            # Agent-specific reasoning
            if agent == "AGENT-OPS01":
                # Ops agent values operational support agents highly during crisis
                if context["crisis_active"] and "RISK" in target_agent:
                    base_score = 0.9  # Risk analysis is critical during crisis
            elif agent == "AGENT-PM01":
                # PM agent considers governance and policy implications
                if "RISK" in target_agent:
                    base_score = 0.8  # Risk management aligns with policy goals
            elif agent == "AGENT-ENG01":
                # Engineering agent considers technical workload
                if context["roster_size"] < 4:  # Small team needs help
                    base_score = 0.8

            # Budget considerations - if agents are budget stressed, they want help
            if context["budget_stressed"]:
                base_score += 0.1  # Slight boost for wanting help when stressed

        elif action == "remove" and target_agent:
            # Removing agents is generally negative unless specific conditions
            base_score = 0.3
            if context["budget_stressed"]:
                base_score = 0.4  # Slightly less negative if budget constrained

        return max(0.0, min(1.0, base_score))  # Clamp to [0, 1]

    def _auto_ballot_needs_action(self, options: Mapping[str, Any]) -> bool:
        if not isinstance(options, Mapping):
            return True
        roster_set = set(self.state.roster)
        needs_action = False
        for value in options.values():
            action, agent_id = self._interpret_option_action(value)
            if not agent_id:
                if self._is_noop_option(value):
                    continue
                needs_action = True  # directive we cannot interpret -> keep ballot
                continue
            if action == "add" and agent_id not in roster_set:
                return True
            if action == "remove" and agent_id in roster_set:
                return True
        return needs_action

    @staticmethod
    def _interpret_option_action(option: Any) -> tuple[str | None, str | None]:
        if isinstance(option, str):
            lower = option.strip().lower()
            if lower.startswith("agent:add:"):
                return "add", option.split(":", 2)[-1]
            if lower.startswith("agent:remove:") or lower.startswith("agent:suspend:"):
                return "remove", option.split(":", 2)[-1]
            return None, None
        if isinstance(option, Mapping):
            action = str(option.get("action", "")).lower()
            agent = option.get("agent") or option.get("agent_id")
            if not isinstance(agent, str) or not agent:
                return None, None
            if action in {"add_agent", "add", "recruit", "activate"}:
                return "add", agent
            if action in {"remove_agent", "remove", "retire", "suspend"}:
                return "remove", agent
        return None, None

    @staticmethod
    def _is_noop_option(option: Any) -> bool:
        if isinstance(option, str):
            lower = option.strip().lower()
            return lower in {"retain-current-roster", "none", "noop", "skip"}
        if isinstance(option, Mapping):
            action = str(option.get("action", "")).lower()
            return action in {"noop", "retain", "keep"}
        return False

    def _compose_auto_ballot_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if isinstance(self.auto_ballot.options, Mapping):
            options.update(self.auto_ballot.options)
        if self.auto_ballot.discover_proposals:
            for key, payload in self._discover_proposal_options().items():
                options.setdefault(key, payload)
        for agent_id in self._identify_removal_candidates():
            options.setdefault(f"REMOVE-{agent_id}", f"agent:remove:{agent_id}")
        return options

    def _discover_proposal_options(self) -> dict[str, Mapping[str, Any]]:
        proposals_dir = self.base_dir / "org/policy/proposals"
        if not proposals_dir.exists():
            return {}
        discovered: dict[str, Mapping[str, Any]] = {}
        for proposal in sorted(proposals_dir.glob("*.alou.md")):
            try:
                data = load_alou_data(proposal)
            except Exception as exc:  # pragma: no cover - defensive guard
                LOGGER.debug("Skipping proposal %s: %s", proposal, exc)
                continue
            agent_id = str(data.get("agent_id", "")).strip()
            if not agent_id:
                continue
            key = f"ADD-{agent_id}"
            try:
                rel_path = proposal.relative_to(self.base_dir).as_posix()
            except ValueError:
                rel_path = proposal.as_posix()
            discovered.setdefault(
                key,
                {
                    "action": "add_agent",
                    "agent": agent_id,
                    "artifact": rel_path,
                },
            )
        return discovered

    def _compose_auto_ballot_electorate(self) -> list[str]:
        voters = set(self.auto_ballot.electorate or [])
        registry_dir = self.base_dir / "org/_registry"
        for agent_id in self.state.roster:
            alou_path = registry_dir / f"{agent_id}.alou.md"
            if not alou_path.exists():
                continue
            try:
                data = load_alou_data(alou_path)
            except Exception:  # pragma: no cover - defensive guard
                continue
            gedi_raw = data.get("gedi")
            gedi = gedi_raw if isinstance(gedi_raw, dict) else {}
            roles = {str(role).lower() for role in gedi.get("roles", []) or []}
            if "voter" in roles:
                voters.add(agent_id)
        ordered = sorted(voters)
        return ordered

    def _identify_removal_candidates(self) -> list[str]:
        retain = set(self.auto_ballot.retain_agents or [])
        join_rounds: dict[str, int] = self.state.metrics.get("agent_join_round", {})
        activity: dict[str, list[int]] = self.state.metrics.get("agent_activity", {})
        probation = max(self.lifecycle.probation_rounds, 0)
        window = max(self.lifecycle.evaluation_window, 1)
        candidates: list[str] = []
        for agent_id in self.state.roster:
            if agent_id in retain:
                continue
            join_round = join_rounds.get(agent_id, 0)
            if self.state.round - join_round < probation:
                continue
            history = activity.get(agent_id, [])
            if len(history) < window:
                continue
            if sum(history) == 0:
                candidates.append(agent_id)
        return candidates

    def _build_adopt_command(self, ballot_id: str) -> list[str] | None:
        logs_dir = self.base_dir / "logs/gedi"
        tally_path = logs_dir / f"{ballot_id}-tally.json"
        if not tally_path.exists():
            LOGGER.warning("Skipping adopt for %s: tally file missing", ballot_id)
            return None
        try:
            tally = json.loads(tally_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            LOGGER.warning("Skipping adopt for %s: tally file is invalid JSON", ballot_id)
            return None
        winner = str(tally.get("winner", ""))
        if not winner:
            LOGGER.warning("Skipping adopt for %s: winner missing", ballot_id)
            return None
        option_value = None
        if isinstance(self.auto_ballot.options, Mapping):
            option_value = self.auto_ballot.options.get(winner)
        artifact_value = self._option_artifact(option_value)
        if not artifact_value:
            LOGGER.info("Skipping adopt for %s: no option value for winner %s", ballot_id, winner)
            return None
        if not self._is_pathlike_option(option_value):
            LOGGER.info(
                "Skipping adopt for %s: winner %s value treated as directive (%s)",
                ballot_id,
                winner,
                option_value,
            )
            return None
        source_path = Path(artifact_value)
        if not source_path.is_absolute():
            source_path = (self.base_dir / source_path).resolve()
        if not source_path.exists():
            LOGGER.warning(
                "Skipping adopt for %s: source artifact %s missing",
                ballot_id,
                source_path,
            )
            return None
        return [sys.executable, "-m", "scripts.gedi_ballot", "adopt", ballot_id]

    def _option_artifact(self, value: Any) -> str | None:
        if isinstance(value, str):
            candidate = value.strip()
            return candidate or None
        if isinstance(value, Mapping):
            for key in ("artifact", "path", "target"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
        return None

    def _is_pathlike_option(self, value: Any) -> bool:
        candidate = self._option_artifact(value)
        if not candidate or ":" in candidate and "/" not in candidate:
            return False
        suffix = Path(candidate).suffix.lower()
        if suffix in {".md", ".markdown", ".yaml", ".yml", ".json"}:
            return True
        return "/" in candidate

    def _append_governance_events(self, events_path: Path) -> list[dict[str, Any]]:
        absolute = events_path if events_path.is_absolute() else (self.base_dir / events_path)
        ballot_events, self._processed_ballots = collect_ballot_lifecycle_events(
            self.base_dir, self._processed_ballots
        )
        incident_events, self._processed_incidents = collect_incident_lifecycle_events(
            self.base_dir, self._processed_incidents
        )

        # Enhanced social dynamics analysis
        governance_records = ballot_events + incident_events
        social_records = []

        if self.auto_ballot.coalition_detection:
            # Process ballot events for coalition detection
            for event in ballot_events:
                if event.get("act") == "governance.ballot_result" and "votes" in event:
                    coalitions = detect_voting_coalitions(event, self.state.coalition_history)
                    if coalitions:
                        self.state.coalition_history.extend(coalitions)
                        for coalition in coalitions:
                            social_records.append({
                                "t": event.get("t", datetime.now(timezone.utc).isoformat()),
                                "act": "social.coalition_detected",
                                "agents": coalition["agents"],
                                "agreement_rate": coalition["agreement_rate"],
                                "type": coalition["type"],
                            })

                    # Calculate influence metrics
                    influence = calculate_influence_metrics(event, coalitions)
                    for agent, influence_score in influence.items():
                        social_records.append({
                            "t": event.get("t", datetime.now(timezone.utc).isoformat()),
                            "act": "social.influence_update",
                            "agent": agent,
                            "influence_score": influence_score,
                        })

        if self.auto_ballot.trust_tracking:
            # Update trust matrix based on voting behavior
            for event in ballot_events:
                if event.get("act") == "governance.ballot_result" and "votes" in event:
                    coalitions = detect_voting_coalitions(event, self.state.coalition_history[-5:])
                    old_trust = dict(self.state.trust_matrix)
                    update_trust_matrix(self.state.trust_matrix, event, coalitions)

                    # Record trust changes
                    for agent1 in self.state.trust_matrix:
                        for agent2 in self.state.trust_matrix[agent1]:
                            old_trust_value = old_trust.get(agent1, {}).get(agent2, 0.5)
                            new_trust_value = self.state.trust_matrix[agent1][agent2]
                            if abs(new_trust_value - old_trust_value) > 0.01:  # Significant change
                                social_records.append({
                                    "t": event.get("t", datetime.now(timezone.utc).isoformat()),
                                    "act": "social.trust_update",
                                    "from_agent": agent1,
                                    "to_agent": agent2,
                                    "trust_delta": new_trust_value - old_trust_value,
                                    "new_trust": new_trust_value,
                                })

        records = governance_records + social_records
        if not records:
            return []

        absolute.parent.mkdir(parents=True, exist_ok=True)
        with absolute.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        LOGGER.info(
            "Appended %s governance events (%s social dynamics) to %s",
            len(governance_records),
            len(social_records),
            absolute,
        )
        return records

    def _try_materialize_agent(self, agent_id: str, action: Mapping[str, Any]) -> bool:
        artifact = (
            action.get("artifact")
            or action.get("path")
            or action.get("target")
            or (action.get("details") or {}).get("artifact")
            or (action.get("details") or {}).get("path")
        )
        if not isinstance(artifact, str) or not artifact.strip():
            LOGGER.warning("Cannot materialize %s: no artifact reference in action", agent_id)
            return False
        artifact = artifact.strip()
        try:
            result = materialize_agent(self.base_dir, artifact)
        except AgentOnboardingError as exc:
            LOGGER.warning(
                "Agent onboarding failed for %s from %s: %s",
                agent_id,
                artifact,
                exc,
            )
            return False
        LOGGER.info(
            "Materialized agent %s from %s (prompt created=%s)",
            result.agent_id,
            artifact,
            result.prompt_created,
        )
        return True

    def _apply_lifecycle(self, summary: RoundSummary) -> None:
        """Adjust roster based on lifecycle actions and spec limits."""

        changes_made = False
        registry = load_registered_agent_configs(self.base_dir)
        for action in summary.lifecycle_actions:
            act = str(action.get("act"))
            target = str(action.get("target") or action.get("agent_id") or action.get("agent"))
            if not target:
                continue
            if act in {"roster.add", "governance.add_agent"}:
                if target not in registry:
                    if not self._try_materialize_agent(target, action):
                        LOGGER.warning(
                            "Skipping roster add for %s: onboarding materials missing",
                            target,
                        )
                        continue
                    registry = load_registered_agent_configs(self.base_dir)
                if target not in self.state.roster:
                    self.state.roster.append(target)
                    if target not in self.state.created:
                        self.state.created.append(target)
                    join_rounds = self.state.metrics.setdefault("agent_join_round", {})
                    join_rounds.setdefault(target, summary.round)
                    changes_made = True
            elif act in {"roster.remove", "governance.remove_agent"}:
                if target in self.state.roster:
                    self.state.roster.remove(target)
                    if target not in self.state.retired:
                        self.state.retired.append(target)
                    join_rounds = self.state.metrics.get("agent_join_round", {})
                    join_rounds.pop(target, None)
                    activity = self.state.metrics.get("agent_activity", {})
                    activity.pop(target, None)
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
