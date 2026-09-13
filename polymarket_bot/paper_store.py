from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .models import jsonable


class StateStore:
    """Tiny crash-safe store for one-decision-per-market paper/live state."""

    def __init__(self, state_path: Path, decision_log_path: Path):
        self.state_path = state_path
        self.decision_log_path = decision_log_path
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.decision_log_path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            value = {}
        if not isinstance(value, dict):
            value = {}
        value.setdefault("seen_markets", [])
        value.setdefault("positions", {})
        return value

    def seen(self, slug: str) -> bool:
        return slug in set(self._read().get("seen_markets", []))

    def mark_seen(self, slug: str) -> None:
        state = self._read()
        seen = list(dict.fromkeys([*state.get("seen_markets", []), slug]))
        # Keep a bounded window; old slugs are immutable and do not need RAM.
        state["seen_markets"] = seen[-2000:]
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def set_position(self, slug: str, value: dict[str, Any]) -> None:
        state = self._read()
        state.setdefault("positions", {})[slug] = jsonable(value)
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def log(self, event: str, payload: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "payload": jsonable(payload),
        }
        with self.decision_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
