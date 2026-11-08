"""Inspect or reconcile the TWAP journal; no BUY/SELL submission command."""
import argparse
import asyncio
import json
from pathlib import Path
import sqlite3


def status(path):
    path = Path(path).resolve()
    if not path.exists():
        print(json.dumps(dict(state=str(path),exists=False)))
        return
    db = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    db.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in db.execute('SELECT id,slug,created_ms,day,side,budget,status,won,redeem_status FROM orders ORDER BY id')]
        legacy = [dict(r) for r in db.execute('SELECT slug,reconciled FROM legacy')]
        print(json.dumps(dict(state=str(path),orders=rows,legacy=legacy),indent=2))
    finally:
        db.close()


async def reconcile():
    from dotenv import load_dotenv
    from polymarket_bot.oci_vault import load_oci_vault_env_if_configured
    from polymarket_bot.twap_config import TwapSettings
    from polymarket_bot.twap_engine import TwapBot
    load_dotenv(); load_oci_vault_env_if_configured()
    settings = TwapSettings.from_env()
    engine = TwapBot(settings)
    try:
        await engine.start(check_trading_ready=False,collect_prices=False)
        await engine.reconcile()
    finally:
        await engine.close()
    status(settings.state_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['status','reconcile'])
    parser.add_argument('--state',default=None)
    args = parser.parse_args()
    if args.command == 'status':
        import os
        status(args.state or os.getenv('POLYMARKET_STATE_PATH','logs/twap_state.sqlite3'))
    else:
        if args.state:
            parser.error('Reconcile uses the live env state; do not override it here')
        asyncio.run(reconcile())


if __name__ == '__main__':
    main()
