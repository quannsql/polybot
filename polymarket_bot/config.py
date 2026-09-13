from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value == value and abs(value) != float("inf") else default


def _int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Runtime controls.  Paper mode and no calibrated model are deliberate defaults."""

    mode: str = "paper"
    symbol: str = "BTCUSDT"
    gamma_url: str = "https://gamma-api.polymarket.com"
    clob_url: str = "https://clob.polymarket.com"
    geoblock_url: str = "https://polymarket.com/api/geoblock"
    binance_url: str = "https://api.binance.com"
    poll_seconds: int = 5
    decision_delay_seconds: int = 20
    max_entry_delay_seconds: int = 45
    signal_policy: str = 'boundary'
    router_enabled: bool = True
    aux_enabled: bool = True
    history_5m_bars: int = 240
    data_source: str = "binance"
    router_sma_days: int = 25
    router_short_depth_pct: float = 1.5
    short_lane_run_bps: float = 60.0
    session_start_utc: int = 8
    session_end_utc: int = 22
    taker_fee_rate: float = 0.07
    min_edge: float = 0.03
    max_spread: float = 0.04
    bankroll_usd: float = 100.0
    max_stake_usd: float = 10.0
    kelly_fraction: float = 0.10
    calibration_path: Path = Path("calibration.json")
    state_path: Path = Path("logs/paper_state.json")
    decision_log_path: Path = Path("logs/decisions.jsonl")
    signer_private_key: str | None = field(default=None, repr=False)
    wallet_address: str | None = None
    relayer_api_key: str | None = field(default=None, repr=False)
    relayer_api_key_address: str | None = field(default=None, repr=False)
    live_confirmation: str = ""
    dry_run: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("POLYMARKET_MODE", "paper").strip().lower()
        if mode not in {"paper", "live"}:
            raise ValueError("POLYMARKET_MODE must be paper or live")
        settings = cls(
            mode=mode,
            symbol=os.getenv("POLYMARKET_SYMBOL", "BTCUSDT").upper(),
            poll_seconds=max(1, _int("POLYMARKET_POLL_SECONDS", 5)),
            decision_delay_seconds=max(0, _int("POLYMARKET_DECISION_DELAY_SECONDS", 20)),
            max_entry_delay_seconds=_int('POLYMARKET_MAX_ENTRY_DELAY_SECONDS', 45),
            signal_policy=os.getenv('POLYMARKET_SIGNAL_POLICY', 'boundary'),
            router_enabled=_flag('POLYMARKET_ROUTER_ENABLED', True),
            aux_enabled=_flag('POLYMARKET_AUX_ENABLED', True),
            history_5m_bars=max(80, _int("POLYMARKET_HISTORY_5M_BARS", 240)),
            data_source=os.getenv("POLYMARKET_DATA_SOURCE", "binance").strip().lower(),
            router_sma_days=max(2, _int("POLYMARKET_ROUTER_SMA_DAYS", 25)),
            router_short_depth_pct=_float("POLYMARKET_ROUTER_SHORT_DEPTH_PCT", 1.5),
            short_lane_run_bps=max(0.0, _float("POLYMARKET_SHORT_LANE_RUN_BPS", 60.0)),
            session_start_utc=_int("POLYMARKET_SESSION_START_UTC", 8) % 24,
            session_end_utc=_int("POLYMARKET_SESSION_END_UTC", 22) % 24,
            taker_fee_rate=max(0.0, _float("POLYMARKET_TAKER_FEE_RATE", 0.07)),
            min_edge=max(0.0, _float("POLYMARKET_MIN_EDGE", 0.03)),
            max_spread=max(0.0, _float("POLYMARKET_MAX_SPREAD", 0.04)),
            bankroll_usd=max(0.0, _float("POLYMARKET_BANKROLL_USD", 100.0)),
            max_stake_usd=max(0.0, _float("POLYMARKET_MAX_STAKE_USD", 10.0)),
            kelly_fraction=min(1.0, max(0.0, _float("POLYMARKET_KELLY_FRACTION", 0.10))),
            calibration_path=Path(os.getenv("POLYMARKET_CALIBRATION_PATH", "calibration.json")),
            state_path=Path(os.getenv("POLYMARKET_STATE_PATH", "logs/paper_state.json")),
            decision_log_path=Path(os.getenv("POLYMARKET_DECISION_LOG", "logs/decisions.jsonl")),
            signer_private_key=os.getenv("POLYMARKET_SIGNER_PRIVATE_KEY"),
            wallet_address=os.getenv("POLYMARKET_WALLET_ADDRESS"),
            relayer_api_key=os.getenv("POLYMARKET_RELAYER_API_KEY"),
            relayer_api_key_address=os.getenv("POLYMARKET_RELAYER_API_KEY_ADDRESS"),
            live_confirmation=os.getenv("POLYMARKET_LIVE_CONFIRM", ""),
            dry_run=_flag("POLYMARKET_DRY_RUN", mode != "live"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.signal_policy not in {'boundary', 'latest_5m'}:
            raise ValueError('Signal policy must use fixed 15m contract windows')
        if not 0 <= self.decision_delay_seconds <= self.max_entry_delay_seconds < 300:
            raise ValueError('Entry delays must satisfy 0 <= delay <= max delay < 300s')
        if self.symbol != "BTCUSDT":
            raise ValueError("Bot 2 currently supports BTCUSDT only")
        if self.data_source not in {"binance"}:
            raise ValueError("POLYMARKET_DATA_SOURCE must be binance for this first version")
        if self.history_5m_bars < 80:
            raise ValueError("history_5m_bars must be at least 80")
        if self.max_stake_usd > self.bankroll_usd:
            raise ValueError("max stake cannot exceed bankroll")
        if self.mode == "live":
            raise ValueError('Live trading is not ready: capped execution and fill reconciliation are not approved. Use preflight_trial.py and paper capture.')

    def load_calibration(self) -> dict:
        """Load an explicitly supplied probability calibration, if any.

        The bot never treats raw Bollinger scores as probabilities.  A missing
        calibration therefore makes a decision paper-only instead of silently
        turning a 53% proxy accuracy into a fabricated probability.
        """
        try:
            payload = json.loads(self.calibration_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
