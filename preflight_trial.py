"""Read-only $30 canary readiness check. Never signs, creates keys or submits orders."""
import argparse
import asyncio
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import time

import httpx
from polymarket_bot.actual_research import parse_market, fee_schedule, buy_depth
from polymarket_bot.geography import geographic_check

ROOT = Path(__file__).resolve().parent
def validate_profile(p):
    if p.get('schema') != 'polybot_trial_v1' or p.get('execution_mode') != 'disabled':
        raise ValueError('Only disabled preparation profiles are supported')
    if p.get('stake_usd_including_fee') != 30 or p.get('canary_max_new_orders') != 1:
        raise ValueError('First-trial preparation is exactly $30 and one order maximum')
    if p.get('canary_max_open_exposure_usd') != 30 or p.get('canary_stop_after_loss_usd') != 30:
        raise ValueError('Preparation exposure/loss caps must be $30')
    return p


async def inspect_public(profile):
    checks = {}
    # Normal direct requests; do not use proxy env variables to change location.
    async with httpx.AsyncClient(timeout=8., trust_env=False) as client:
        async def get(url, **params):
            a = time.time()
            try:
                r = await client.get(url, params=params or None)
                if r.status_code != 200:
                    return {'ok': False, 'http_status': r.status_code}
                return {'ok': True, 'data': r.json(), 'rtt_ms': round((time.time()-a)*1000),
                        'mid_local_time': (a+time.time())/2}
            except Exception as exc:
                return {'ok': False, 'error_type': type(exc).__name__}  # no exception URL/secret dump
        geo, clock = await asyncio.gather(get('https://polymarket.com/api/geoblock'),
                                         get('https://clob.polymarket.com/time'))
        checks['geography'] = geographic_check(geo.get('data'))
        if not geo['ok']:
            checks['geography']['request_error'] = {k:v for k,v in geo.items() if k!='data'}
        if not clock['ok'] or not isinstance(clock.get('data'), (float, int)):
            checks['server_clock'] = {'ok': False}
            return checks
        offset = clock['data']-clock['mid_local_time']
        checks['server_clock'] = {'ok': abs(offset) <= 300 and clock['rtt_ms'] <= 3000,
                                  'offset_seconds': offset, 'precision': 'integer seconds; diagnostic only'}
        start = int(clock['data'])//900*900
        response = await get(f'https://gamma-api.polymarket.com/events/slug/btc-updown-15m-{start}')
        if not response['ok']:
            checks['market'] = response
            return checks
        try:
            event = response['data']; market = parse_market(event, start)
            info, up, down = await asyncio.gather(
                get(f"https://clob.polymarket.com/clob-markets/{market['condition_id']}"),
                get('https://clob.polymarket.com/book', token_id=market['tokens']['up']),
                get('https://clob.polymarket.com/book', token_id=market['tokens']['down']))
            fee = fee_schedule(market, info.get('data', {}))
            checks['market'] = {'slug': market['slug'], 'rule_type': market['rule_type'],
                                'accepting_orders': market['raw'].get('acceptingOrders') is True,
                                'fee_status': fee['status'],
                                'verified_live_price_to_beat_present': (event.get('eventMetadata') or {}).get('priceToBeat') is not None}
            checks['depth_cost_only_30usd'] = {}
            for side, response in [('up',up),('down',down)]:
                try:
                    b = response.get('data', {})
                    if b.get('market') != market['condition_id'] or str(b.get('asset_id')) != market['tokens'][side]:
                        raise ValueError('book identity mismatch')
                    fill = buy_depth(b, fee, budget=profile['stake_usd_including_fee'], max_price=.99,
                                     now_ms=int((time.time()+offset)*1000))
                    checks['depth_cost_only_30usd'][side] = {**fill, 'not_a_trade_decision': True}
                except (ValueError, TypeError, KeyError) as exc:
                    checks['depth_cost_only_30usd'][side] = {'unavailable': str(exc)}
        except (ValueError, TypeError, KeyError):
            checks['market'] = {'ok': False, 'reason': 'unsupported or incomplete public metadata'}
    return checks


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, default=ROOT/'trial_30usd.json')
    parser.add_argument('--output', type=Path, default=ROOT/'trial_preflight.json')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--require-ready', action='store_true', help='Exit 2 while live prerequisites are incomplete')
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(ROOT):
        raise ValueError('Output must stay inside Bot2')
    profile = validate_profile(json.loads(args.profile.read_text(encoding='utf-8')))
    try:
        sdk = version('polymarket-client')
    except PackageNotFoundError:
        sdk = None
    checks = {} if args.offline else await inspect_public(profile)
    result = {'created_utc': datetime.now(timezone.utc).isoformat(), 'budget_usd_including_fee': 30,
              'mode': 'read_only_preflight', 'live_ready': False, 'sdk_installed_version': sdk,
              'secret_presence_only': {name: bool(os.getenv(name)) for name in [
                  'POLYMARKET_SIGNER_PRIVATE_KEY','POLYMARKET_WALLET_ADDRESS',
                  'POLYMARKET_RELAYER_API_KEY','POLYMARKET_RELAYER_API_KEY_ADDRESS']},
              'checks': checks, 'uncompleted_requirements': profile['live_prerequisites'],
              'note': 'Never signs or derives API keys. Presence of secrets and successful GETs do not prove wallet access, balance, allowance, eligibility or execution readiness.'}
    args.output.parent.mkdir(exist_ok=True, parents=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    if args.require_ready:
        raise SystemExit(2)


if __name__ == '__main__':
    asyncio.run(main())
