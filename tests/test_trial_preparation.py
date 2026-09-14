import asyncio
from decimal import Decimal
import json
from pathlib import Path
import time

import pytest

from preflight_trial import geographic_check, validate_profile
from polymarket_bot.config import Settings
from polymarket_bot.polymarket_api import PolymarketLiveExecutor
from polymarket_bot.actual_research import buy_depth


@pytest.mark.parametrize('country', ['US', 'SG', 'TH', 'IR'])
def test_published_api_restrictions_cannot_be_overridden_by_false_endpoint(country):
    assert geographic_check({'blocked': False, 'country': country, 'region': ''})['new_order_network_check'] is False


def test_netherlands_is_denied_even_if_endpoint_says_unblocked():
    x = geographic_check({'blocked': False, 'country': 'NL', 'region': ''})
    assert x['new_order_network_check'] is False
    assert geographic_check({'blocked': True, 'country': 'NL'})['new_order_network_check'] is False


@pytest.mark.parametrize('response', [None, {}, {'blocked': 'false', 'country': 'NL'}, {'blocked':False}])
def test_unknown_geo_fails_closed(response):
    assert geographic_check(response)['new_order_network_check'] is False


def test_trial_profile_cannot_enable_live_or_raise_budget():
    p=json.loads((Path(__file__).resolve().parents[1]/'trial_30usd.json').read_text())
    validate_profile(p)
    with pytest.raises(ValueError):
        validate_profile({**p, 'execution_mode': 'live'})
    with pytest.raises(ValueError):
        validate_profile({**p, 'stake_usd_including_fee': 31})


def test_live_path_cannot_be_accidentally_enabled():
    settings=Settings(mode='live',dry_run=False,live_confirmation='I_UNDERSTAND_LIVE_TRADING',
                      signer_private_key='fake_not_a_key')
    with pytest.raises(ValueError, match='Live mode is locked'):
        settings.validate()


def test_live_canary_hard_cap_and_confirmation():
    base = dict(mode='live', dry_run=False,
                live_confirmation='I_UNDERSTAND_ONE_30_USD_ORDER_CAN_LOSE_ALL',
                account_eligibility_confirmed=True,
                signer_private_key='fake', wallet_address='0x'+'1'*40,
                relayer_api_key='key', relayer_api_key_address='0x'+'2'*40)
    Settings(**base).validate()
    with pytest.raises(ValueError, match=r'hard \$30'):
        Settings(**base, max_stake_usd=31).validate()


def test_executor_rejects_more_than_thirty_without_network():
    settings = Settings(max_stake_usd=30, live_max_price=.97)
    executor = PolymarketLiveExecutor(settings)
    executor.client = object()
    with pytest.raises(RuntimeError, match=r'no more than \$30'):
        asyncio.run(executor.buy('token', Decimal('30.01'), Decimal('.90')))


def test_executor_uses_fok_price_and_spend_caps():
    class Rejected:
        ok = False
        def model_dump(self, mode):
            return {"ok": False, "code": "fok_not_filled", "message": "none"}

    class Client:
        def __init__(self):
            self.kwargs = None
        async def get_balance_allowance(self, **kwargs):
            return type('Balance', (), {'balance': 30_000_000})()
        async def place_market_order(self, **kwargs):
            self.kwargs = kwargs
            return Rejected()

    settings = Settings(max_stake_usd=30, live_max_price=.97)
    executor = PolymarketLiveExecutor(settings)
    executor.client = Client()
    result = asyncio.run(executor.buy('token', Decimal('30'), Decimal('.91')))
    assert executor.client.kwargs == {
        'token_id': 'token', 'side': 'BUY', 'amount': '30',
        'max_spend': '30', 'max_price': '0.91', 'order_type': 'FOK'
    }
    assert result['reconciled'] is True
    assert result['filled'] is False


def test_executor_rejects_stale_final_quote_before_submission():
    class Client:
        def __init__(self):
            self.submitted = False
        async def get_balance_allowance(self, **kwargs):
            return type('Balance', (), {'balance': 30_000_000})()
        async def place_market_order(self, **kwargs):
            self.submitted = True

    settings = Settings(live_quote_max_age_ms=100)
    executor = PolymarketLiveExecutor(settings)
    executor.client = Client()
    with pytest.raises(RuntimeError, match='Final quote became stale'):
        asyncio.run(executor.buy(
            'token', Decimal('30'), Decimal('.91'), quote_observed_at=time.monotonic() - 1
        ))
    assert executor.client.submitted is False


def test_executor_reuses_recent_balance_check():
    class Rejected:
        ok = False
        def model_dump(self, mode):
            return {"ok": False}

    class Client:
        def __init__(self):
            self.balance_calls = 0
        async def get_balance_allowance(self, **kwargs):
            self.balance_calls += 1
            return type('Balance', (), {'balance': 30_000_000})()
        async def place_market_order(self, **kwargs):
            return Rejected()

    executor = PolymarketLiveExecutor(Settings())
    executor.client = Client()

    async def exercise():
        await executor.ensure_balance(Decimal('30'), max_age=0)
        await executor.buy('token', Decimal('30'), Decimal('.91'))

    asyncio.run(exercise())
    assert executor.client.balance_calls == 1


def test_thirty_dollars_includes_fee_and_walks_depth():
    b={'timestamp':'100000','bids':[{'price':'.84','size':'100'}],
       'asks':[{'price':'.85','size':'20'},{'price':'.86','size':'100'}], 'min_order_size':'5'}
    f=buy_depth(b, {'status':'known','rate':.07},budget=30,max_price=.90,now_ms=100000)
    assert len(f['fills']) == 2
    assert 29.99 <= f['total_cost'] <= 30
    assert f['notional'] < 30
    assert f['fee_cash_equivalent'] > 0
    assert f['total_cost'] == pytest.approx(f['notional']+f['fee_cash_equivalent'])
