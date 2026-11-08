import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from polymarket_bot.polygon_rpc import check_polygon_approvals, sdk_environment
from polymarket_bot.twap_config import TwapSettings


def test_rpc_override_only_changes_the_pinned_sdk_rpc_url(monkeypatch):
    sdk = pytest.importorskip('polymarket')
    from polymarket._internal.environment import get_environment_config
    url = 'https://rpc.example.test/polygon'
    monkeypatch.setenv('POLYMARKET_POLYGON_RPC_URL', url)
    settings = TwapSettings.from_env()
    original = get_environment_config(sdk.PRODUCTION)
    config = get_environment_config(sdk_environment(settings.polygon_rpc_url))
    assert config == replace(original, rpc_url=url)
    assert original.rpc_url != url


def test_rpc_approvals_read_checks_chain_and_never_sends_approvals():
    sdk = pytest.importorskip('polymarket')
    from polymarket._internal.environment import get_environment_config
    requests = []

    class Rpc:
        async def verify_chain_id(self, chain):
            assert chain == 137
            requests.append('chain')

        async def eth_call_batch(self, calls):
            assert requests == ['chain']
            assert len(calls) > 1
            requests.append('allowances')
            return ['0x' + '0' * 64] * len(calls)

    client = SimpleNamespace(_ctx=SimpleNamespace(
        rpc=Rpc(), wallet='0x' + '1' * 40,
        environment_config=get_environment_config(sdk_environment('https://polygon.publicnode.com'))))
    result = asyncio.run(check_polygon_approvals(client))
    assert requests == ['chain', 'allowances']
    assert result['approvals_read_ok'] and result['chain_id'] == 137
    assert result['missing_erc20'] > 0 and result['missing_erc1155'] > 0


def test_rpc_failure_blocks_readiness_without_exposing_provider_key():
    pytest.importorskip('polymarket')
    from polymarket.errors import RequestRejectedError

    class Rpc:
        async def verify_chain_id(self, chain):
            assert chain == 137

        async def eth_call_batch(self, calls):
            raise RequestRejectedError('blocked: /test-provider-key', status=400)

    client = SimpleNamespace(_ctx=SimpleNamespace(
        rpc=Rpc(), wallet='0x' + '1' * 40,
        environment_config=sdk_environment('https://rpc.example.test/test-provider-key')._config))
    with pytest.raises(RuntimeError, match='rpc.example.test approvals read failed') as error:
        asyncio.run(check_polygon_approvals(client))
    assert 'HTTP 400' in str(error.value)
    assert 'test-provider-key' not in str(error.value)
