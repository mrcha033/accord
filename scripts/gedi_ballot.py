"""GEDI ballot CLI supporting propose, vote, tally, and adopt.

Ballot specification lives under ``org/policy/_ballots`` with structure:

- Logs: ``logs/gedi/<ballot-id>.jsonl`` (append-only)
- Result documents: ``org/policy/norms/<ballot-id>-result.md``
- Adopted documents: ``org/policy/norms/<ballot-id>-adopted.md``
- Bus announcement + adoption summaries under ``bus/policy/``

Each Markdown output receives an in-toto provenance header and DSSE envelope
via the existing ``scripts.provtools`` tooling.
"""

from __future__ import annotations

import argparse
import json
import textwrap
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import yaml

from scripts import provtools

UTC = timezone.utc
BASE_DIR = Path(".").resolve()
ATTN_ROOT = BASE_DIR / "attestations/gedi"


def _rel(path: Path) -> str:
    candidate = path.resolve()
    try:
        return str(candidate.relative_to(BASE_DIR))
    except ValueError:
        return str(candidate)


@dataclass
class Ballot:
    id: str
    title: str
    rule: str
    quorum: float
    options: Dict[str, str]
    electorate: List[str]
    proposal_materials: List[str]
    window: Dict[str, str]


def _utcnow() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_jsonl(path: Path, record: dict) -> None:
    _ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_ballot(path: Path) -> Ballot:
    data = _load_yaml(path)
    return Ballot(
        id=str(data["id"]),
        title=str(data.get("title", "")),
        rule=str(data.get("rule", "condorcet")).lower(),
        quorum=float(data.get("quorum", 0.0)),
        options=dict(data.get("options", {})),
        electorate=list(data.get("electorate", [])),
        proposal_materials=list(data.get("proposal_materials", [])),
        window=dict(data.get("window", {})),
    )


def _materials_block(materials: Iterable[str]) -> str:
    lines = []
    for material in materials:
        lines.append(f"    - name: \"{material}\"\n      digest: {{}}")
    return "\n".join(lines) if lines else "        []"


def _provenance_header(
    *,
    subject: str,
    materials: Iterable[str],
    agent_id: str,
    agent_role: str,
    predicate_extra: dict | None = None,
) -> str:
    extra_yaml = (
        textwrap.indent(
            yaml.safe_dump(predicate_extra or {}, sort_keys=False).rstrip(), "      "
        )
        if predicate_extra
        else ""
    )
    return textwrap.dedent(
        f"""<!--
provenance:
  _type: "https://in-toto.io/Statement/v0.1"
  subject:
    - name: "{subject}"
      digest: {{}}
  predicateType: "https://accord.ai/schemas/policy@v1"
  predicate:
    produced_by:
      agent_id: "{agent_id}"
      agent_role: "{agent_role}"
    process:
      toolchain:
        - name: "gedi_ballot"
          version: "0.1"
    materials:
{_materials_block(materials)}
{('    extra:\n' + extra_yaml) if extra_yaml else ''}
-->
"""
    )


def _dsse_build(markdown: Path, private_key: Path, output_dsse: Path) -> None:
    _ensure_parent(output_dsse)
    namespace = argparse.Namespace(
        file=str(markdown),
        priv=str(private_key),
        out=str(output_dsse),
        base=str(BASE_DIR),
        keyid="",
    )
    rc = provtools.cmd_build(namespace)
    if rc != 0:
        raise SystemExit(f"DSSE build failed for {markdown}")


def _pairwise_preferences(
    votes: List[List[str]], options: List[str]
) -> Dict[Tuple[str, str], int]:
    counts = {(a, b): 0 for a in options for b in options if a != b}
    for ranking in votes:
        positions = {opt: idx for idx, opt in enumerate(ranking) if opt in options}
        for a in options:
            for b in options:
                if a == b:
                    continue
                if a in positions and b in positions and positions[a] < positions[b]:
                    counts[(a, b)] += 1
    return counts


def _condorcet_winner(votes: List[List[str]], options: List[str]) -> str | None:
    pairwise = _pairwise_preferences(votes, options)
    for candidate in options:
        if all(
            pairwise[(candidate, other)] > pairwise[(other, candidate)]
            for other in options
            if other != candidate
        ):
            return candidate
    return None


def _borda_winner(votes: List[List[str]], options: List[str]) -> str:
    scores = {opt: 0 for opt in options}
    size = len(options)
    for ranking in votes:
        for idx, opt in enumerate(ranking):
            if opt in scores:
                scores[opt] += size - idx - 1
    return min(scores.items(), key=lambda item: (-item[1], item[0]))[0]


def _irv_winner(votes: List[List[str]], options: List[str]) -> str:
    active = set(options)
    while len(active) > 1:
        counts = {opt: 0 for opt in active}
        for ranking in votes:
            for opt in ranking:
                if opt in active:
                    counts[opt] += 1
                    break
        total = sum(counts.values())
        for opt, value in counts.items():
            if value * 2 > total:
                return opt
        eliminated = min(counts.items(), key=lambda item: (item[1], item[0]))[0]
        active.remove(eliminated)
    return next(iter(active)) if active else options[0]


def _collect_votes(log_path: Path) -> List[List[str]]:
    if not log_path.exists():
        return []
    votes: List[List[str]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") == "vote" and isinstance(record.get("ranking"), list):
            votes.append([str(opt) for opt in record["ranking"]])
    return votes


def cmd_propose(args: argparse.Namespace) -> int:
    ballot_path = Path(args.ballot)
    ballot = load_ballot(ballot_path)
    log_path = BASE_DIR / f"logs/gedi/{ballot.id}.jsonl"
    announce_path = BASE_DIR / f"bus/policy/{ballot.id}-announce.md"
    _ensure_parent(log_path)
    _ensure_parent(announce_path)
    materials = [_rel(ballot_path)] + [_rel(Path(m)) for m in (ballot.proposal_materials or [])]
    header = _provenance_header(
        subject=_rel(announce_path),
        materials=materials,
        agent_id="AGENT-GEDI",
        agent_role="Decision Steward",
        predicate_extra={"ballot_id": ballot.id, "rule": ballot.rule, "quorum": ballot.quorum},
    )
    body = textwrap.dedent(
        f"""# {ballot.title}

- **Ballot ID:** {ballot.id}
- **Rule:** {ballot.rule}
- **Quorum:** {ballot.quorum}
- **Proposed:** {_utcnow()}
"""
    )
    announce_path.write_text(header + body, encoding="utf-8")
    _dsse_build(announce_path, Path(args.priv), ATTN_ROOT / f"{ballot.id}-announce.dsse")
    _write_jsonl(log_path, {"t": _utcnow(), "event": "propose", "ballot": ballot.id, "ballot_path": str(ballot_path)})
    print(json.dumps({"ok": True, "event": "propose", "ballot": ballot.id, "announce": _rel(announce_path)}))
    return 0


def cmd_vote(args: argparse.Namespace) -> int:
    ballot_path = BASE_DIR / "org/policy/_ballots" / f"{args.ballot}.yaml"
    ballot = load_ballot(ballot_path)
    ranking = [part.strip() for part in args.ranking.split(">") if part.strip()]
    unknown = [opt for opt in ranking if opt not in ballot.options]
    if unknown:
        print(json.dumps({"ok": False, "error": f"unknown options: {', '.join(unknown)}"}))
        return 1
    log_path = BASE_DIR / f"logs/gedi/{ballot.id}.jsonl"
    _write_jsonl(
        log_path,
        {"t": _utcnow(), "event": "vote", "ballot": ballot.id, "agent": args.agent, "ranking": ranking},
    )
    print(json.dumps({"ok": True, "event": "vote", "ballot": ballot.id, "agent": args.agent, "ranking": ranking}))
    return 0


def cmd_tally(args: argparse.Namespace) -> int:
    ballot_path = BASE_DIR / "org/policy/_ballots" / f"{args.ballot}.yaml"
    ballot = load_ballot(ballot_path)
    log_path = BASE_DIR / f"logs/gedi/{ballot.id}.jsonl"
    votes = _collect_votes(log_path)
    options = list(ballot.options.keys())
    if not options:
        print(json.dumps({"ok": False, "error": "ballot has no options"}))
        return 1
    if ballot.rule == "condorcet":
        winner = _condorcet_winner(votes, options) or _borda_winner(votes, options)
    elif ballot.rule == "irv":
        winner = _irv_winner(votes, options)
    elif ballot.rule == "consensus":
        unanimous = votes and all(ranking and ranking[0] == votes[0][0] for ranking in votes)
        winner = votes[0][0] if unanimous else _irv_winner(votes, options)
    else:
        print(json.dumps({"ok": False, "error": f"unknown rule {ballot.rule}"}))
        return 1
    electorate = set(ballot.electorate or [])
    voters = set()
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("event") == "vote" and record.get("agent"):
                voters.add(str(record["agent"]))
    turnout = (len(voters) / len(electorate)) if electorate else 1.0
    quorum_met = turnout >= ballot.quorum
    result_path = BASE_DIR / f"org/policy/norms/{ballot.id}-result.md"
    materials = [
        _rel(BASE_DIR / f"org/policy/_ballots/{ballot.id}.yaml"),
        _rel(BASE_DIR / f"logs/gedi/{ballot.id}.jsonl"),
    ] + [_rel(Path(m)) for m in (ballot.proposal_materials or [])]
    header = _provenance_header(
        subject=_rel(result_path),
        materials=materials,
        agent_id="AGENT-GEDI",
        agent_role="Decision Steward",
        predicate_extra={
            "ballot_id": ballot.id,
            "rule": ballot.rule,
            "winner": winner,
            "turnout": turnout,
            "quorum_met": quorum_met,
        },
    )
    body = textwrap.dedent(
        f"""# Result: {ballot.title}

- **Winner:** {winner} → {ballot.options[winner]}
- **Rule:** {ballot.rule}
- **Turnout:** {turnout:.2f} (quorum {ballot.quorum})
- **Tallied:** {_utcnow()}
"""
    )
    _ensure_parent(result_path)
    result_path.write_text(header + body, encoding="utf-8")
    _dsse_build(result_path, Path(args.priv), ATTN_ROOT / f"{ballot.id}-result.dsse")
    tally_summary = {
        "ballot": ballot.id,
        "rule": ballot.rule,
        "winner": winner,
        "turnout": turnout,
        "quorum_met": quorum_met,
        "options": options,
        "voters": sorted(voters),
    }
    (BASE_DIR / f"logs/gedi/{ballot.id}-tally.json").write_text(
        json.dumps(tally_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "event": "tally", "ballot": ballot.id, "winner": winner, "quorum_met": quorum_met}))
    return 0


def cmd_adopt(args: argparse.Namespace) -> int:
    ballot_path = BASE_DIR / "org/policy/_ballots" / f"{args.ballot}.yaml"
    ballot = load_ballot(ballot_path)
    tally_path = BASE_DIR / f"logs/gedi/{ballot.id}-tally.json"
    if not tally_path.exists():
        print(json.dumps({"ok": False, "error": "tally results missing"}))
        return 1
    tally = json.loads(tally_path.read_text(encoding="utf-8"))
    if not tally.get("quorum_met", False):
        print(json.dumps({"ok": False, "error": "quorum not met"}))
        return 1
    winner = tally["winner"]
    source_path = BASE_DIR / ballot.options[winner]
    adopted_path = BASE_DIR / f"org/policy/norms/{ballot.id}-adopted.md"
    materials = [
        _rel(BASE_DIR / f"org/policy/_ballots/{ballot.id}.yaml"),
        _rel(BASE_DIR / f"logs/gedi/{ballot.id}.jsonl"),
        _rel(BASE_DIR / f"logs/gedi/{ballot.id}-tally.json"),
        _rel(source_path) if source_path.exists() else str(source_path),
    ]
    header = _provenance_header(
        subject=_rel(adopted_path),
        materials=materials,
        agent_id="AGENT-GEDI",
        agent_role="Decision Steward",
        predicate_extra={"ballot_id": ballot.id, "winner": winner},
    )
    content = (
        source_path.read_text(encoding="utf-8")
        if source_path.exists()
        else f"(missing reference: {source_path})"
    )
    adopted_body = header + textwrap.dedent(
        f"""# Adopted: {ballot.title}

> Source draft: `{source_path}`

{content}
"""
    )
    _ensure_parent(adopted_path)
    adopted_path.write_text(adopted_body, encoding="utf-8")
    _dsse_build(adopted_path, Path(args.priv), ATTN_ROOT / f"{ballot.id}-adopted.dsse")
    summary_path = BASE_DIR / f"bus/policy/{ballot.id}-adopted.md"
    summary_header = _provenance_header(
        subject=_rel(summary_path),
        materials=[_rel(adopted_path)],
        agent_id="AGENT-GEDI",
        agent_role="Decision Steward",
    )
    summary_body = summary_header + textwrap.dedent(
        f"""# Adopted: {ballot.title}

- **Winner:** {winner}
- **Adopted:** {_utcnow()}
"""
    )
    _ensure_parent(summary_path)
    summary_path.write_text(summary_body, encoding="utf-8")
    _dsse_build(summary_path, Path(args.priv), ATTN_ROOT / f"{ballot.id}-adopted-summary.dsse")
    print(json.dumps({"ok": True, "event": "adopt", "ballot": ballot.id, "adopted": _rel(adopted_path)}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    propose = sub.add_parser("propose", help="announce ballot and initialise logs")
    propose.add_argument("ballot", help="Path to ballot YAML")
    propose.add_argument("--priv", default="keys/ed25519.key")
    propose.set_defaults(func=cmd_propose)
    vote = sub.add_parser("vote", help="record a ranked vote")
    vote.add_argument("ballot", help="Ballot identifier (YAML basename)")
    vote.add_argument("--agent", required=True)
    vote.add_argument("--ranking", required=True, help='Ranking string like "A>B>C"')
    vote.set_defaults(func=cmd_vote)
    tally = sub.add_parser("tally", help="compute winner and produce result document")
    tally.add_argument("ballot", help="Ballot identifier")
    tally.add_argument("--priv", default="keys/ed25519.key")
    tally.set_defaults(func=cmd_tally)
    adopt = sub.add_parser("adopt", help="promote winning option to adopted norm")
    adopt.add_argument("ballot", help="Ballot identifier")
    adopt.add_argument("--priv", default="keys/ed25519.key")
    adopt.set_defaults(func=cmd_adopt)
    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
