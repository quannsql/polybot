from __future__ import annotations

import argparse
import asyncio
import logging
import os

from polymarket_bot.twap_config import TwapSettings as Settings
from polymarket_bot.twap_engine import TwapBot as BotEngine
from polymarket_bot.oci_vault import load_oci_vault_env_if_configured


async def _run_once(engine: BotEngine) -> None:
    try:
        await engine.start()
        # Reconnect snapshots are not live observations. Build one fresh minute.
        await asyncio.sleep(65)
        await engine.run_once()
    finally:
        await engine.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="BTC15m Chainlink TWAP60 + spot live test")
    parser.add_argument("--once", action="store_true", help="warm feeds65s, then evaluate once; a missing opening skips the market")
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    load_oci_vault_env_if_configured()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    engine = BotEngine(settings)
    if args.once:
        asyncio.run(_run_once(engine))
    else:
        asyncio.run(engine.run_forever())


if __name__ == "__main__":
    main()
