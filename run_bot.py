from __future__ import annotations

import argparse
import asyncio
import logging
import os

from polymarket_bot.config import Settings
from polymarket_bot.engine import BotEngine
from polymarket_bot.oci_vault import load_oci_vault_env_if_configured


async def _run_once(engine: BotEngine) -> None:
    if engine.executor is not None:
        await engine.executor.connect()
    try:
        await engine.run_once()
    finally:
        if engine.executor is not None:
            await engine.executor.close()
        await engine.api.close()
        close = getattr(engine.feed, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


def main() -> None:
    parser = argparse.ArgumentParser(description="BTC 15m Polymarket Bot 2")
    parser.add_argument("--once", action="store_true", help="evaluate one current market")
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
