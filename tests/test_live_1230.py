import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from polymarket_bot.config import Settings
from polymarket_bot.engine import BotEngine
from polymarket_bot.models import Book, Market, SignalSnapshot
from polymarket_bot.polymarket_api import PolymarketLiveExecutor
from polymarket_bot.risk import RiskEngine


def live_settings(**changes):
    values = dict(
        mode='live', dry_run=False,
        live_confirmation='I_UNDERSTAND_ONE_20_USD_ORDER_CAN_LOSE_ALL',
        account_eligibility_confirmed=True,
        signer_private_key='fake', wallet_address='0x'+'1'*40,
        relayer_api_key='key', relayer_api_key_address='0x'+'2'*40,
        execution_strategy='legacy_1230_ref85', data_source='lighter',
        signal_policy='latest_5m', decision_delay_seconds=750,
        max_entry_delay_seconds=755, session_start_utc=0, session_end_utc=0,
        min_entry_price=.85, reference_max_age_seconds=75,
        reference_price_padding=.01, live_fixed_stake_usd=20,
        max_stake_usd=20, bankroll_usd=50, live_max_orders=1,
        max_spread=1,
    )
    values.update(changes)
    return Settings(**values)


def approval():
    return {
        'approved': True, 'strategy_id': 'dca_legacy_1230_ref85_v1',
        'signal_policy': 'latest_5m', 'signal_source': 'lighter_1m_resampled',
        'entry_seconds': 750, 'stake_usd': 20, 'bankroll_usd': 50,
        'descriptive_win_rate_by_source': {'main_5m': {'up': .9775}},
    }


def objects():
    start = datetime(2026, 9, 14, tzinfo=timezone.utc)
    market = Market('slug', 'Bitcoin Up or Down', 'condition', start,
        start.replace(minute=15), 'Chainlink', 'Chainlink', ('Up','Down'),
        ('up-token','down-token'), True, False, True, Decimal('.01'),
        Decimal('5'), True, False)
    signal = SignalSnapshot(start, 'long', 'up', 'main_5m', .75,
        1, 1, 1, 1, 1, 1, 'test')
    return market, signal


def test_exact_live_1230_profile_and_twenty_dollar_size():
    settings = live_settings()
    settings.validate()
    market, signal = objects()
    book = Book('up-token', Decimal('.83'), Decimal('.84'), Decimal('100'),
        Decimal('100'), Decimal('.01'), Decimal('.01'), Decimal('5'), False)
    decision = RiskEngine(settings, approval()).decide(market, book, signal)
    assert decision.action == 'buy'
    assert decision.stake_usd == Decimal('20.00')
    assert decision.reason == 'approved_legacy_threshold_rule'
    assert decision.edge_per_share == 0


@pytest.mark.parametrize('change', [
    {'decision_delay_seconds': 749}, {'live_fixed_stake_usd': 21},
    {'bankroll_usd': 49}, {'data_source': 'binance'},
])
def test_live_1230_profile_drift_fails_closed(change):
    with pytest.raises(ValueError, match='exact legacy'):
        live_settings(**change).validate()


def test_missing_exact_strategy_approval_cannot_buy():
    market, signal = objects()
    book = Book('up-token', Decimal('.85'), Decimal('.86'), Decimal('100'),
        Decimal('100'), Decimal('.01'), Decimal('.01'), Decimal('5'), False)
    decision = RiskEngine(live_settings(), {}).decide(market, book, signal)
    assert decision.action == 'paper_signal_only'
    assert decision.reason == 'legacy_strategy_missing_exact_approval'


def test_reference_is_frozen_at_1230_and_rounded_down_to_tick():
    market, signal = objects()
    engine = object.__new__(BotEngine)
    engine.settings = live_settings()
    engine.store = SimpleNamespace(log=lambda *args: None)
    due = int(market.start.timestamp()) + 750

    class Api:
        async def price_history(self, token, lo, hi):
            assert token == 'up-token' and hi == due
            return [{'t': due-15, 'p': .855}]

    engine.api = Api()
    cap = asyncio.run(engine._legacy_reference_cap(market, signal, market.start))
    assert cap == Decimal('.86')


def test_executor_cannot_exceed_twenty_even_if_called_directly():
    executor = PolymarketLiveExecutor(live_settings())
    executor.client = object()
    with pytest.raises(RuntimeError, match=r'no more than \$20'):
        asyncio.run(executor.buy('token', Decimal('20.01'), Decimal('.90')))
