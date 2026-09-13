from __future__ import annotations

import argparse
import asyncio
import logging
import os

from polymarket_bot.config import Settings
from polymarket_bot.engine import BotEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="BTC 15m Polymarket Bot 2")
    parser.add_argument("--once", action="store_true", help="evaluate one current market")
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    engine = BotEngine(settings)
    if args.once:
        asyncio.run(engine.run_once())
    else:
        asyncio.run(engine.run_forever())


if __name__ == "__main__":
    main()
