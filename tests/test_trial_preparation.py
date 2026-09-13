import asyncio
from decimal import Decimal
import json
from pathlib import Path

import pytest

from preflight_trial import geographic_check, validate_profile
from polymarket_bot.config import Settings
from polymarket_bot.polymarket_api import PolymarketLiveExecutor
from polymarket_bot.actual_research import buy_depth


@pytest.mark.parametrize('country', ['US', 'SG', 'TH', 'IR'])
def test_published_api_restrictions_cannot_be_overridden_by_false_endpoint(country):
    assert geographic_check({'blocked': False, 'country': country, 'region': ''})['new_order_network_check'] is False


def test_netherlands_api_exception_is_not_eligibility_approval():
    x = geographic_check({'blocked': False, 'country': 'NL', 'region': ''})
    assert x['new_order_network_check'] is True
    assert x['nl_help_center_conflict_needs_review'] is True
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


def test_legacy_live_path_cannot_be_accidentally_enabled():
    settings=Settings(mode='live',dry_run=False,live_confirmation='I_UNDERSTAND_LIVE_TRADING',
                      signer_private_key='fake_not_a_key')
    with pytest.raises(ValueError, match='not ready'):
        settings.validate()
    executor=PolymarketLiveExecutor(settings)
    with pytest.raises(RuntimeError, match='disabled'):
        asyncio.run(executor.connect())
    with pytest.raises(RuntimeError, match='disabled'):
        asyncio.run(executor.buy('not-a-token', Decimal(30)))


def test_thirty_dollars_includes_fee_and_walks_depth():
    b={'timestamp':'100000','bids':[{'price':'.84','size':'100'}],
       'asks':[{'price':'.85','size':'20'},{'price':'.86','size':'100'}], 'min_order_size':'5'}
    f=buy_depth(b, {'status':'known','rate':.07},budget=30,max_price=.90,now_ms=100000)
    assert len(f['fills']) == 2
    assert 29.99 <= f['total_cost'] <= 30
    assert f['notional'] < 30
    assert f['fee_cash_equivalent'] > 0
    assert f['total_cost'] == pytest.approx(f['notional']+f['fee_cash_equivalent'])
