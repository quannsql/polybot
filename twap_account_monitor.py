"""Read-only Polymarket collateral balance snapshot sidecar for the dashboard."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
import os
from pathlib import Path
import signal

from polymarket_bot.oci_vault import load_oci_vault_env_if_configured
from polymarket_bot.polymarket_api import PolymarketLiveExecutor
from polymarket_bot.twap_config import TwapSettings


OUTPUT = Path(os.environ.get('POLYBOT_ACCOUNT_SNAPSHOT_PATH', '/account-data/twap_account.json'))
INTERVAL_SECONDS = 60
logger = logging.getLogger('polymarket_bot.account_monitor')


def write_snapshot(balance):
    record = {
        'timestamp': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        'event': 'twap_account_snapshot',
        'payload': {'balance_usd': format(balance, 'f'), 'currency': 'pUSD'},
    }
    temporary = OUTPUT.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(record, stream, separators=(',', ':'), allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(OUTPUT)


async def run():
    load_oci_vault_env_if_configured()
    settings = TwapSettings.from_env()
    if settings.mode != 'live':
        raise RuntimeError('Account balance monitor requires the live account environment')
    executor = PolymarketLiveExecutor(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await executor.connect(check_balance=False)
    logger.info('Read-only collateral balance monitor started for %s',
                settings.wallet_address[:6] + '…' + settings.wallet_address[-4:])
    try:
        while not stop.is_set():
            try:
                result = await executor.client.get_balance_allowance(asset_type='COLLATERAL')
                balance = Decimal(int(result.balance)) / Decimal(1_000_000)
                write_snapshot(balance)
                logger.info('CLOB collateral snapshot updated')
            except Exception as error:
                # Keep the last good snapshot. Never expose API or exception contents.
                logger.warning('CLOB collateral snapshot failed: %s', type(error).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
    finally:
        await executor.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    asyncio.run(run())
