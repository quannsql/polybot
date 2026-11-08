"""Configuration for the replacement BTC15m TWAP + Chainlink spot runtime."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path

STRATEGY = 'twap60_spot_1400_v1'
CONFIRMATION = 'I_UNDERSTAND_TWAP_20_USD_LIVE_TEST'


def number(name, default, integer=False):
    raw = os.getenv(name, str(default))
    try:
        value = Decimal(raw)
        if not value.is_finite() or (integer and value != int(value)):
            raise ValueError()
    except (InvalidOperation, ValueError, OverflowError):
        raise ValueError(f'Invalid numeric setting {name}') from None
    return int(value) if integer else value


def flag(name, default=False):
    value = os.getenv(name, '1' if default else '0').lower().strip()
    if value not in {'1','0','true','false','yes','no','on','off'}:
        raise ValueError(f'Invalid boolean setting {name}')
    return value in {'1','true','yes','on'}


@dataclass(frozen=True)
class TwapSettings:
    mode: str = 'paper'
    execution_strategy: str = STRATEGY
    gamma_url: str = 'https://gamma-api.polymarket.com'
    clob_url: str = 'https://clob.polymarket.com'
    geoblock_url: str = 'https://polymarket.com/api/geoblock'
    decision_delay_seconds: int = 840
    max_entry_delay_seconds: int = 845
    minimum_lead_bps: Decimal = Decimal('5')
    min_entry_price: Decimal = Decimal('.85')  # Frozen historical reference, not an ask floor.
    reference_max_age_seconds: int = 75
    reference_price_padding: Decimal = Decimal('.01')
    live_fixed_stake_usd: Decimal = Decimal('20')
    max_stake_usd: Decimal = Decimal('20')
    bankroll_usd: Decimal = Decimal('50')
    live_max_price: Decimal = Decimal('.99')
    live_max_orders: int = 5
    live_quote_max_age_ms: int = 1500
    minimum_winning_pnl: Decimal = Decimal('.05')
    depth_fraction: Decimal = Decimal('.5')
    daily_loss_stop: bool = True
    auto_redeem: bool = True
    state_path: Path = Path('logs/twap_state.sqlite3')
    decision_log_path: Path = Path('logs/twap_decisions.jsonl')
    oracle_log_path: Path = Path('logs/twap_oracle.jsonl')
    legacy_state_path: Path = Path('logs/live_state.json')
    signer_private_key: str | None = field(default=None, repr=False)
    wallet_address: str | None = None
    relayer_api_key: str | None = field(default=None, repr=False)
    relayer_api_key_address: str | None = field(default=None, repr=False)
    expected_wallet_type: str = ''
    account_eligibility_confirmed: bool = False
    live_confirmation: str = ''
    dry_run: bool = True

    @classmethod
    def from_env(cls):
        mode = os.getenv('POLYMARKET_MODE','paper').lower().strip()
        settings = cls(mode=mode,
            execution_strategy=os.getenv('POLYMARKET_EXECUTION_STRATEGY', STRATEGY).strip(),
            decision_delay_seconds=number('POLYMARKET_DECISION_DELAY_SECONDS',840,True),
            max_entry_delay_seconds=number('POLYMARKET_MAX_ENTRY_DELAY_SECONDS',845,True),
            minimum_lead_bps=number('POLYMARKET_TWAP_MIN_LEAD_BPS',5),
            min_entry_price=number('POLYMARKET_MIN_ENTRY_PRICE','.85'),
            reference_max_age_seconds=number('POLYMARKET_REFERENCE_MAX_AGE_SECONDS',75,True),
            reference_price_padding=number('POLYMARKET_REFERENCE_PRICE_PADDING','.01'),
            live_fixed_stake_usd=number('POLYMARKET_LIVE_FIXED_STAKE_USD',20),
            max_stake_usd=number('POLYMARKET_MAX_STAKE_USD',20),
            bankroll_usd=number('POLYMARKET_BANKROLL_USD',50),
            live_max_price=number('POLYMARKET_LIVE_MAX_PRICE','.99'),
            live_max_orders=number('POLYMARKET_LIVE_MAX_ORDERS',5,True),
            live_quote_max_age_ms=number('POLYMARKET_LIVE_QUOTE_MAX_AGE_MS',1500,True),
            minimum_winning_pnl=number('POLYMARKET_MIN_WINNING_PNL','.05'),
            depth_fraction=number('POLYMARKET_DEPTH_FRACTION','.5'),
            daily_loss_stop=flag('POLYMARKET_DAILY_LOSS_STOP',True),
            auto_redeem=flag('POLYMARKET_AUTO_REDEEM',True),
            state_path=Path(os.getenv('POLYMARKET_STATE_PATH','logs/twap_state.sqlite3')),
            decision_log_path=Path(os.getenv('POLYMARKET_DECISION_LOG','logs/twap_decisions.jsonl')),
            oracle_log_path=Path(os.getenv('POLYMARKET_ORACLE_LOG','logs/twap_oracle.jsonl')),
            legacy_state_path=Path(os.getenv('POLYMARKET_LEGACY_STATE_PATH','logs/live_state.json')),
            signer_private_key=os.getenv('POLYMARKET_SIGNER_PRIVATE_KEY'),
            wallet_address=os.getenv('POLYMARKET_WALLET_ADDRESS'),
            relayer_api_key=os.getenv('POLYMARKET_RELAYER_API_KEY'),
            relayer_api_key_address=os.getenv('POLYMARKET_RELAYER_API_KEY_ADDRESS'),
            expected_wallet_type=os.getenv('POLYMARKET_EXPECTED_WALLET_TYPE','').strip().upper(),
            account_eligibility_confirmed=flag('POLYMARKET_ACCOUNT_ELIGIBILITY_CONFIRMED'),
            live_confirmation=os.getenv('POLYMARKET_LIVE_CONFIRM',''),
            dry_run=flag('POLYMARKET_DRY_RUN',mode!='live'))
        settings.validate()
        return settings

    def validate(self):
        if self.mode not in {'paper','live'} or self.execution_strategy != STRATEGY:
            raise ValueError(f'The replacement runtime requires POLYMARKET_EXECUTION_STRATEGY={STRATEGY}; remove the old profile')
        if self.decision_delay_seconds != 840 or not 840 <= self.max_entry_delay_seconds <= 845:
            raise ValueError('TWAP signal is frozen at14:00; submissions must end by14:05')
        if self.minimum_lead_bps != 5 or self.min_entry_price != Decimal('.85') or self.reference_max_age_seconds != 75 or self.reference_price_padding != Decimal('.01'):
            raise ValueError('TWAP research parity requires5bp, reference>=.85, max age75s, padding.01')
        if self.live_fixed_stake_usd != 20 or self.max_stake_usd != 20 or self.bankroll_usd < 20:
            raise ValueError('TWAP live test requires $20 all-in target per order and bankroll>=20')
        if not 0 < self.live_max_price <= Decimal('.99') or not 1 <= self.live_max_orders <= 1000:
            raise ValueError('Invalid price cap or maximum lifetime test submissions')
        if not 100 <= self.live_quote_max_age_ms <= 1500 or not 0 < self.depth_fraction <= 1 or self.minimum_winning_pnl < 0:
            raise ValueError('Invalid quote freshness, depth fraction or winning margin')
        if self.state_path.suffix != '.sqlite3':
            raise ValueError('Use a new .sqlite3 TWAP journal; preserve the old JSON journal separately')
        if self.expected_wallet_type not in {'','EOA','POLY_PROXY','GNOSIS_SAFE','DEPOSIT_WALLET'}:
            raise ValueError('Invalid wallet type')
        if self.mode == 'live':
            if self.dry_run or self.live_confirmation != CONFIRMATION or not self.account_eligibility_confirmed:
                raise ValueError('Live requires DRY_RUN=0, TWAP live confirmation and account eligibility setting')
            self.require_account()

    def require_account(self):
        values = {'POLYMARKET_SIGNER_PRIVATE_KEY':self.signer_private_key,
                  'POLYMARKET_WALLET_ADDRESS':self.wallet_address,
                  'POLYMARKET_RELAYER_API_KEY':self.relayer_api_key,
                  'POLYMARKET_RELAYER_API_KEY_ADDRESS':self.relayer_api_key_address}
        missing = [name for name,value in values.items() if not value or value.startswith('REPLACE')]
        if missing:
            raise ValueError('Authenticated Chainlink feed needs: '+', '.join(missing))
