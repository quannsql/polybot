"""Public/account/feed checks. Never signs or submits a BUY or SELL order."""
import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import importlib.metadata
import json
import time

from polymarket_bot.geography import geographic_check
from polymarket_bot.oci_vault import load_oci_vault_env_if_configured
from polymarket_bot.polymarket_api import PolymarketLiveExecutor
from polymarket_bot.twap_config import TwapSettings,STRATEGY
from polymarket_bot.twap_execution import TwapPublic
from polymarket_bot.twap_feed import ChainlinkFeed


class ProbeStore:
    def __init__(self):
        self.counts = {'twap':0,'spot':0}
        self.openings = {}
    def log(self, event, payload):
        pass
    def record_price(self, kind, point, origin):
        if origin == 'update':
            self.counts[kind] += 1
    def record_opening(self, point):
        if point.observed_ms%900000 == 0 and point.received_ms <= point.observed_ms+5000:
            self.openings[point.observed_ms] = point


async def check(args):
    if args.public_only:
        settings = TwapSettings()
    else:
        from dotenv import load_dotenv
        load_dotenv()
        load_oci_vault_env_if_configured()
        settings = TwapSettings.from_env()
        settings.require_account()
    api = TwapPublic(settings)
    executor = None; feed = None
    try:
        await api.sync_clock()
        if abs(api.server_clock_offset_ms) > 1500:
            raise RuntimeError('Clock skew exceeds1.5s; synchronize the server clock')
        start = int(datetime.now(timezone.utc).timestamp())//900*900
        record = await api.market_record(start)
        try:
            geo = geographic_check(await api.geoblock())
        except Exception as error:
            geo = dict(status='unavailable',new_order_network_check=False,error_type=type(error).__name__)
        output = dict(check_only=True,order_submitted=False,strategy=STRATEGY,
            market_slug=record['parsed']['slug'],market_version=record['parsed']['raw'].get('version','v1'),
            settlement_source=record['parsed']['resolution_source'],twap_lookback_seconds=60,
            fee=record['fee'],tick=str(record['tick']),clock_offset_ms=api.server_clock_offset_ms,
            geography=geo)
        if args.public_only:
            print(json.dumps(output,indent=2))
            if not geo.get('new_order_network_check'):
                raise RuntimeError('Public market checks completed, but this network did not pass the geography check')
            return
        if settings.mode == 'live' and not geo.get('new_order_network_check'):
            print(json.dumps(output,indent=2))
            raise RuntimeError('Geography must pass before live account preparation')
        executor = PolymarketLiveExecutor(settings)
        await executor.connect(check_balance=False)
        balance = await executor.client.get_balance_allowance(asset_type='COLLATERAL')
        output['account'] = dict(wallet=str(executor.client.wallet),wallet_type=executor.client.wallet_type,
            collateral_balance=str(Decimal(balance.balance)/1000000),
            balance_at_least20=balance.balance>=20000000,
            allowance_count=len(balance.allowances),
            note='CLOB keys and signer material are not printed. No trading approvals changed by this check.')
        output['sdk_version'] = importlib.metadata.version('polymarket-client')
        if not args.account_only:
            probe = ProbeStore(); feed = ChainlinkFeed(probe)
            feed.start(executor.client)
            await asyncio.sleep(args.feed_seconds)
            now = time.time_ns()//1000000
            a,b = feed.twap.asof(now),feed.spot.asof(now)
            output['feed'] = dict(live_update_counts=probe.counts,
                twap_fresh=a is not None,spot_fresh=b is not None,
                twap_minute_valid=feed.twap.valid_minute(now),spot_minute_valid=feed.spot.valid_minute(now),
                opening_seen_during_probe=bool(probe.openings),
                opening_note='A mid-market start normally waits for the NEXT opening; historical snapshot is not a substitute for timely receipt.')
            if a is None or b is None or not feed.twap.valid_minute(now) or not feed.spot.valid_minute(now):
                print(json.dumps(output,indent=2))
                raise RuntimeError('Authenticated Chainlink TWAP/spot feeds did not pass freshness/continuity checks')
        print(json.dumps(output,indent=2))
        if not geo.get('new_order_network_check'):
            raise RuntimeError('This network is not allowed to submit new orders')
        if settings.mode == 'live' and balance.balance < 20000000:
            raise RuntimeError('Less than20 collateral available')
    finally:
        if feed:
            await feed.close()
        if executor:
            await executor.close()
        await api.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--public-only',action='store_true')
    group.add_argument('--account-only',action='store_true')
    parser.add_argument('--feed-seconds',type=int,default=70)
    args = parser.parse_args()
    if not 65 <= args.feed_seconds <= 300:
        parser.error('Feed probe needs65..300 seconds')
    asyncio.run(check(args))


if __name__ == '__main__':
    main()
