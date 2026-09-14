"""Authenticated account readiness check. It never creates or submits an order."""
from __future__ import annotations

import asyncio
import json

from polymarket_bot.config import Settings
from polymarket_bot.geography import geographic_check
from polymarket_bot.polymarket_api import PolymarketLiveExecutor, PolymarketPublic
from polymarket_bot.oci_vault import load_oci_vault_env_if_configured


async def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    load_oci_vault_env_if_configured()
    settings = Settings.from_env()
    required = {
        "POLYMARKET_SIGNER_PRIVATE_KEY": settings.signer_private_key,
        "POLYMARKET_WALLET_ADDRESS": settings.wallet_address,
        "POLYMARKET_RELAYER_API_KEY": settings.relayer_api_key,
        "POLYMARKET_RELAYER_API_KEY_ADDRESS": settings.relayer_api_key_address,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError("Missing account variables: " + ", ".join(missing))
    public = PolymarketPublic(settings)
    geo = await public.geoblock()
    geo_check = geographic_check(geo)
    if not geo_check.get("new_order_network_check", False):
        raise RuntimeError("Polymarket geoblock did not allow new orders from this network")
    executor = PolymarketLiveExecutor(settings)
    await executor.connect()
    try:
        balance = await executor.client.get_balance_allowance(asset_type="COLLATERAL")
        output = {
            "check_only": True,
            "order_submitted": False,
            "country": geo_check.get("country"),
            "region": geo_check.get("region"),
            "wallet": str(executor.client.wallet),
            "wallet_type": executor.client.wallet_type,
            "pUSD_balance": str(balance.balance / 1_000_000),
            "allowance_count": len(balance.allowances),
            "allowances_sufficient_for_fixed_stake": (
                all(value >= int(settings.live_fixed_stake_usd * 1_000_000)
                    for value in balance.allowances.values())
                if balance.allowances else False
            ),
            "note": "No API key, passphrase, private key, or allowance values are printed.",
        }
        print(json.dumps(output, indent=2))
    finally:
        await executor.close()


if __name__ == "__main__":
    asyncio.run(main())
