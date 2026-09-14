from __future__ import annotations

from datetime import datetime, timezone
import json
import os
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
        value.setdefault("live_attempts", [])
        return value

    def _write(self, state: dict[str, Any]) -> None:
        """Atomically replace state; a crash must not erase the canary journal."""
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(jsonable(state), indent=2), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def seen(self, slug: str) -> bool:
        return slug in set(self._read().get("seen_markets", []))

    def mark_seen(self, slug: str) -> None:
        state = self._read()
        seen = list(dict.fromkeys([*state.get("seen_markets", []), slug]))
        # Keep a bounded window; old slugs are immutable and do not need RAM.
        state["seen_markets"] = seen[-2000:]
        self._write(state)

    def set_position(self, slug: str, value: dict[str, Any]) -> None:
        state = self._read()
        state.setdefault("positions", {})[slug] = jsonable(value)
        self._write(state)

    def reserve_live_attempt(self, slug: str, payload: dict[str, Any], maximum: int = 1) -> int:
        """Persist an intent before network submission; an ambiguous crash fails closed."""
        lock_path = self.state_path.with_suffix(self.state_path.suffix + ".live-submit.lock")
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError("live canary lock already exists; reconcile before retry") from exc
        try:
            os.write(descriptor, f"reserved {datetime.now(timezone.utc).isoformat()}\n".encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        state = self._read()
        attempts = state["live_attempts"]
        if len(attempts) >= maximum:
            raise RuntimeError(f"live canary limit reached ({len(attempts)}/{maximum})")
        if any(item.get("market_slug") == slug for item in attempts):
            raise RuntimeError(f"live order already attempted for {slug}")
        attempt_id = len(attempts) + 1
        attempts.append({
            "attempt_id": attempt_id,
            "market_slug": slug,
            "status": "reserved_before_submit",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "payload": jsonable(payload),
        })
        self._write(state)
        return attempt_id

    def finish_live_attempt(self, attempt_id: int, status: str, result: Any) -> None:
        state = self._read()
        for item in state["live_attempts"]:
            if item.get("attempt_id") == attempt_id:
                item["status"] = status
                item["finished_at"] = datetime.now(timezone.utc).isoformat()
                item["result"] = jsonable(result)
                self._write(state)
                return
        raise RuntimeError(f"unknown live attempt {attempt_id}")

    def log(self, event: str, payload: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "payload": jsonable(payload),
        }
        with self.decision_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
