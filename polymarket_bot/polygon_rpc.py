"""Polygon RPC adapter for the pinned polymarket-client 0.17.0."""
import asyncio
from dataclasses import replace
from urllib.parse import urlsplit


DEFAULT_POLYGON_RPC_URL = 'https://polygon.publicnode.com'


def rpc_host(url):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme == 'https' and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.fragment
                and not any(char.isspace() for char in url)):
            return parsed.hostname
    except ValueError:
        pass
    raise ValueError('POLYMARKET_POLYGON_RPC_URL must be an HTTPS Polygon mainnet RPC URL')


def sdk_environment(url):
    # The SDK exposes an Environment argument, but 0.17.0's helper for
    # constructing one is internal. Keep all production addresses unchanged.
    from polymarket import PRODUCTION
    from polymarket._internal.environment import get_environment_config, with_environment_config

    rpc_host(url)
    config = replace(get_environment_config(PRODUCTION), rpc_url=url)
    return with_environment_config(PRODUCTION, config=config)


async def check_polygon_approvals(client):
    """Read the same on-chain allowances batch that SDK live setup uses."""
    from polymarket._internal.actions.relayer.approvals import get_trading_approvals_state

    ctx = client._ctx  # SDK 0.17.0; use exactly the configured client RPC.
    config = ctx.environment_config
    host = rpc_host(config.rpc_url)
    try:
        async with asyncio.timeout(20):
            await ctx.rpc.verify_chain_id(137)
            state = await get_trading_approvals_state(ctx.rpc, wallet=ctx.wallet, config=config)
    except Exception as error:
        # Do not expose a URL path/query that could contain a provider key.
        status = getattr(error, 'status', None)
        detail = f', HTTP {status}' if isinstance(status, int) else ''
        raise RuntimeError(f'Polygon RPC {host} approvals read failed ({type(error).__name__}{detail}). '
                           'Check POLYMARKET_POLYGON_RPC_URL.') from None
    return {'host': host, 'chain_id': 137, 'approvals_read_ok': True,
            'missing_erc20': len(state.missing.erc20),
            'missing_erc1155': len(state.missing.erc1155)}
