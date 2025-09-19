"""Agent interaction tracking and comprehensive output storage system."""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

LOGGER = logging.getLogger(__name__)


class InteractionTracker:
    """Tracks and stores all agent interactions and outputs comprehensively."""

    def __init__(self, base_dir: Path, output_root: Path):
        self.base_dir = base_dir
        self.output_root = output_root
        self.round_archive = output_root / "agent_outputs"
        self.interaction_log = output_root / "interactions.jsonl"
        self.conversation_archive = output_root / "conversations"

        # Create directories
        self.round_archive.mkdir(parents=True, exist_ok=True)
        self.conversation_archive.mkdir(parents=True, exist_ok=True)

    def log_interaction(
        self,
        source_agent: str,
        target_agent: str | None,
        interaction_type: str,
        content: str,
        metadata: Dict[str, Any] | None = None
    ) -> None:
        """Log an interaction between agents."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_agent": source_agent,
            "target_agent": target_agent,
            "interaction_type": interaction_type,  # "read", "write", "reference", "propose", "vote"
            "content_summary": content[:200] + "..." if len(content) > 200 else content,
            "content_length": len(content),
            "metadata": metadata or {}
        }

        with self.interaction_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def store_agent_output(
        self,
        round_number: int,
        agent_id: str,
        output_path: Path,
        summary_path: Path,
        full_content: str
    ) -> None:
        """Store complete agent output for the round."""
        round_dir = self.round_archive / f"round-{round_number:04d}"
        round_dir.mkdir(exist_ok=True)

        # Store full output
        agent_output_file = round_dir / f"{agent_id}_output.md"
        agent_output_file.write_text(full_content, encoding="utf-8")

        # Store metadata
        metadata = {
            "agent_id": agent_id,
            "round": round_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "original_output_path": str(output_path),
            "original_summary_path": str(summary_path),
            "content_length": len(full_content),
            "word_count": len(full_content.split())
        }

        metadata_file = round_dir / f"{agent_id}_metadata.json"
        metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        # Copy original files if they exist
        if output_path.exists():
            shutil.copy2(output_path, round_dir / f"{agent_id}_original_output.md")
        if summary_path.exists():
            shutil.copy2(summary_path, round_dir / f"{agent_id}_original_summary.md")

    def track_bus_interactions(self, round_number: int) -> None:
        """Analyze and track blackboard-style interactions via bus/ directories."""
        bus_dir = self.base_dir / "bus"
        if not bus_dir.exists():
            return

        round_interactions = []

        # Scan all bus directories for recent activity
        for bus_subdir in bus_dir.iterdir():
            if not bus_subdir.is_dir():
                continue

            for file_path in bus_subdir.glob("**/*.md"):
                try:
                    stat_info = file_path.stat()
                    modified_time = datetime.fromtimestamp(stat_info.st_mtime, timezone.utc)

                    # If modified in the last hour (likely this round)
                    time_diff = datetime.now(timezone.utc) - modified_time
                    if time_diff.total_seconds() < 3600:  # 1 hour threshold
                        content = file_path.read_text(encoding="utf-8")

                        # Extract agent references from content
                        referenced_agents = self._extract_agent_references(content)

                        interaction = {
                            "round": round_number,
                            "timestamp": modified_time.isoformat(),
                            "bus_file": str(file_path.relative_to(self.base_dir)),
                            "referenced_agents": referenced_agents,
                            "content_length": len(content),
                            "last_modified": modified_time.isoformat()
                        }
                        round_interactions.append(interaction)

                except Exception as e:
                    LOGGER.warning(f"Error tracking bus file {file_path}: {e}")

        # Store bus interactions for this round
        if round_interactions:
            bus_log = self.conversation_archive / f"round-{round_number:04d}_bus_interactions.json"
            bus_log.write_text(json.dumps(round_interactions, indent=2), encoding="utf-8")

    def _extract_agent_references(self, content: str) -> List[str]:
        """Extract AGENT-* references from content."""
        import re
        pattern = r'AGENT-[A-Z0-9]+'
        return list(set(re.findall(pattern, content)))

    def analyze_conversation_patterns(self, round_number: int) -> Dict[str, Any]:
        """Analyze conversation patterns and agent relationships."""
        # Read recent interactions
        interactions = []
        if self.interaction_log.exists():
            with self.interaction_log.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        interactions.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # Focus on recent interactions (last 10 rounds worth)
        recent_interactions = [
            i for i in interactions
            if i.get("metadata", {}).get("round", 0) >= round_number - 10
        ]

        # Analyze patterns
        agent_interactions = {}
        interaction_types = {}

        for interaction in recent_interactions:
            source = interaction["source_agent"]
            target = interaction.get("target_agent")
            itype = interaction["interaction_type"]

            # Count interactions by agent
            if source not in agent_interactions:
                agent_interactions[source] = {"outgoing": 0, "incoming": 0, "targets": set()}
            agent_interactions[source]["outgoing"] += 1

            if target:
                agent_interactions[source]["targets"].add(target)
                if target not in agent_interactions:
                    agent_interactions[target] = {"outgoing": 0, "incoming": 0, "targets": set()}
                agent_interactions[target]["incoming"] += 1

            # Count interaction types
            interaction_types[itype] = interaction_types.get(itype, 0) + 1

        # Convert sets to lists for JSON serialization
        for agent_data in agent_interactions.values():
            agent_data["targets"] = list(agent_data["targets"])

        analysis = {
            "round": round_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_interactions": len(recent_interactions),
            "agent_interactions": agent_interactions,
            "interaction_types": interaction_types,
            "most_active_agents": sorted(
                agent_interactions.items(),
                key=lambda x: x[1]["outgoing"] + x[1]["incoming"],
                reverse=True
            )[:5]
        }

        # Store analysis
        analysis_file = self.conversation_archive / f"round-{round_number:04d}_analysis.json"
        analysis_file.write_text(json.dumps(analysis, indent=2), encoding="utf-8")

        return analysis

    def create_round_summary(self, round_number: int, agent_results: Sequence[Dict[str, str]]) -> Dict[str, Any]:
        """Create comprehensive summary of round interactions and outputs."""
        summary = {
            "round": round_number,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agents_active": len(agent_results),
            "agent_outputs": []
        }

        total_content_length = 0
        total_word_count = 0

        for result in agent_results:
            agent_id = result["agent_id"]
            output_path = Path(result["output"])

            # Read the actual output content
            try:
                if output_path.exists():
                    content = output_path.read_text(encoding="utf-8")
                    content_length = len(content)
                    word_count = len(content.split())

                    total_content_length += content_length
                    total_word_count += word_count

                    summary["agent_outputs"].append({
                        "agent_id": agent_id,
                        "output_path": str(output_path),
                        "summary_path": result.get("summary", ""),
                        "content_length": content_length,
                        "word_count": word_count,
                        "has_agent_references": len(self._extract_agent_references(content)) > 0
                    })
            except Exception as e:
                LOGGER.warning(f"Error reading output for {agent_id}: {e}")

        summary["total_content_length"] = total_content_length
        summary["total_word_count"] = total_word_count
        summary["average_output_length"] = total_content_length // len(agent_results) if agent_results else 0

        # Store round summary
        summary_file = self.output_root / f"round-{round_number:04d}_summary.json"
        summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        return summary


def enhanced_log_event(
    events_path: Path,
    tracker: InteractionTracker,
    *,
    agent_id: str,
    action: str,
    targets: list[str],
    dsse_ref: str,
    alou_rev: str,
    scopes: list[str],
    policy_refs: list[str],
    round_number: int | None = None,
    content: str = "",
) -> None:
    """Enhanced event logging with interaction tracking."""
    # Standard event logging
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
    }

    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Enhanced interaction tracking
    for target in targets:
        # Determine if this is an agent interaction
        target_agent = None
        for scope in scopes:
            if "AGENT-" in scope:
                # Extract agent ID from scope or target path
                import re
                agent_match = re.search(r'AGENT-[A-Z0-9]+', scope)
                if agent_match and agent_match.group() != agent_id:
                    target_agent = agent_match.group()
                    break

        # Log the interaction
        tracker.log_interaction(
            source_agent=agent_id,
            target_agent=target_agent,
            interaction_type=action,
            content=content,
            metadata={
                "round": round_number,
                "target_path": target,
                "scopes": scopes,
                "policy_refs": policy_refs
            }
        )