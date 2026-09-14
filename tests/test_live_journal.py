from pathlib import Path

import pytest

from polymarket_bot.paper_store import StateStore


def test_live_journal_reserves_before_submit_and_fails_closed(tmp_path: Path):
    store = StateStore(tmp_path / "state.json", tmp_path / "events.jsonl")
    attempt = store.reserve_live_attempt("market-1", {"stake_usd": "30"}, maximum=1)
    assert attempt == 1
    with pytest.raises(RuntimeError, match="canary lock already exists"):
        store.reserve_live_attempt("market-2", {"stake_usd": "30"}, maximum=1)
    store.finish_live_attempt(attempt, "filled", {"order_id": "one"})
    assert store._read()["live_attempts"][0]["status"] == "filled"
