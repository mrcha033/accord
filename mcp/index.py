"""Lightweight content index for MCP adapters."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class IndexEntry:
    path: str
    text: str
    topics: list[str]


class SimpleIndex:
    """JSONL-backed in-memory index for search and knowledge retrieval."""

    def __init__(self, base_dir: Path, *, jsonl_path: str = "docs/index.jsonl") -> None:
        self._base_dir = base_dir
        self._entries: List[IndexEntry] = []
        self._load(jsonl_path)

    def _load(self, jsonl_path: str) -> None:
        path = (self._base_dir / jsonl_path).resolve()
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                text = data.get("text", "")
                topics = data.get("topics", [])
                if not isinstance(text, str):
                    continue
                if not isinstance(topics, list):
                    topics = []
                entry = IndexEntry(
                    path=data.get("path", ""),
                    text=text,
                    topics=[str(topic).lower() for topic in topics],
                )
                if entry.path:
                    self._entries.append(entry)

    def search(self, pattern: str, limit: int) -> List[dict[str, str]]:
        pattern_lower = pattern.lower()
        results: List[dict[str, str]] = []
        for entry in self._entries:
            if pattern_lower in entry.text.lower():
                results.append(
                    {
                        "file": entry.path,
                        "snippet": self._first_match(entry.text, pattern_lower),
                    }
                )
            if len(results) >= limit:
                break
        return results

    def knowledge(self, topic: str, limit: int) -> List[str]:
        topic_lower = topic.lower()
        matches: List[str] = []
        for entry in self._entries:
            if topic_lower in entry.topics or topic_lower in entry.text.lower():
                matches.append(entry.path)
            if len(matches) >= limit:
                break
        return matches

    @staticmethod
    def _first_match(text: str, pattern_lower: str) -> str:
        for line in text.splitlines():
            if pattern_lower in line.lower():
                return line.strip()
        return text[:120].replace("\n", " ")


__all__ = ["SimpleIndex", "IndexEntry"]
