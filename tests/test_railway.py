from pathlib import Path

import pytest

import railway_entrypoint as entry
from polymarket_bot.geography import geographic_check


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    import os
    for name in list(os.environ):
        if name.startswith(('POLYMARKET_', 'OCI_POLYBOT_', 'RAILWAY_')):
            monkeypatch.delenv(name)


@pytest.mark.parametrize('country', ['NL', 'IE', 'JP', 'MT', 'KR'])
def test_frontend_only_restrictions_still_obey_endpoint(country):
    assert geographic_check(dict(blocked=False, country=country))['new_order_network_check']
    assert not geographic_check(dict(blocked=True, country=country))['new_order_network_check']


@pytest.mark.parametrize('country', ['US', 'SG', 'AR', 'GB', 'IR'])
def test_api_close_only_or_blocked_cannot_be_overridden(country):
    assert not geographic_check(dict(blocked=False, country=country))['new_order_network_check']


@pytest.mark.parametrize('country,region', [('CA','ON'), ('CA','QC'), ('UA','43'), ('CA',None), ('UA','')])
def test_regional_restrictions_fail_closed(country, region):
    assert not geographic_check(dict(blocked=False, country=country, region=region))['new_order_network_check']


def test_first_deployment_probe_ignores_account_and_live_flags(monkeypatch):
    monkeypatch.setenv('POLYMARKET_MODE', 'live')
    calls = []
    monkeypatch.setattr(entry.subprocess, 'run', lambda args, **kw: calls.append((args, kw)))
    monkeypatch.setattr(entry.os, 'execv', lambda *a: pytest.fail('probe must not start trading'))
    entry.main()
    assert calls[0][0][-1] == '--public-only'
    assert calls[0][1]['check'] is True


def test_account_probe_disables_oci_metadata(monkeypatch):
    monkeypatch.setenv('POLYMARKET_RAILWAY_ACTION', 'check')
    monkeypatch.setenv('OCI_POLYBOT_USE_INSTANCE_METADATA', '1')
    assert entry.prepare_environment() == 'check'
    assert entry.os.environ['OCI_POLYBOT_USE_INSTANCE_METADATA'] == '0'


def test_worker_refuses_ephemeral_disk(monkeypatch):
    monkeypatch.setenv('POLYMARKET_RAILWAY_ACTION', 'run')
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH', '/data')
    monkeypatch.setattr(Path, 'is_mount', lambda p: False)
    with pytest.raises(RuntimeError, match='persistent'):
        entry.prepare_environment()


def worker_env(monkeypatch, mode='paper'):
    monkeypatch.setenv('POLYMARKET_RAILWAY_ACTION', 'run')
    monkeypatch.setenv('POLYMARKET_MODE', mode)
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH', '/data')
    monkeypatch.setattr(Path, 'is_mount', lambda p: True)


def test_paper_defaults_keep_live_journal_separate(monkeypatch):
    worker_env(monkeypatch)
    assert entry.prepare_environment() == 'run'
    assert entry.os.environ['POLYMARKET_STATE_PATH'] == '/data/twap_paper.sqlite3'


def test_live_still_requires_all_existing_confirmations(monkeypatch):
    worker_env(monkeypatch, 'live')
    with pytest.raises(ValueError, match='Live requires'):
        entry.prepare_environment()


def test_worker_rejects_journal_outside_volume(monkeypatch):
    worker_env(monkeypatch)
    monkeypatch.setenv('POLYMARKET_STATE_PATH', '/tmp/state.sqlite3')
    with pytest.raises(ValueError, match='persistent /data'):
        entry.prepare_environment()


def test_live_worker_passes_existing_gates_then_replaces_process(monkeypatch):
    worker_env(monkeypatch, 'live')
    from polymarket_bot.twap_config import CONFIRMATION
    monkeypatch.setenv('POLYMARKET_DRY_RUN', '0')
    monkeypatch.setenv('POLYMARKET_LIVE_CONFIRM', CONFIRMATION)
    monkeypatch.setenv('POLYMARKET_ACCOUNT_ELIGIBILITY_CONFIRMED', '1')
    for name in ['SIGNER_PRIVATE_KEY', 'WALLET_ADDRESS', 'RELAYER_API_KEY', 'RELAYER_API_KEY_ADDRESS']:
        monkeypatch.setenv('POLYMARKET_' + name, 'test-only-not-a-real-secret')
    calls = []
    monkeypatch.setattr(entry.os, 'execv', lambda *a: calls.append(a))
    monkeypatch.setattr(entry.subprocess, 'run', lambda *a, **kw: pytest.fail('run must replace process'))
    entry.main()
    assert calls[0][1][-1] == 'run_bot.py'
    assert entry.os.environ['POLYMARKET_STATE_PATH'] == '/data/twap_state.sqlite3'


def test_failed_feed_check_propagates_failure(monkeypatch):
    monkeypatch.setenv('POLYMARKET_RAILWAY_ACTION', 'check')
    def fail(args, **kwargs):
        assert args[-2:] == ['--feed-seconds', '70']
        raise entry.subprocess.CalledProcessError(1, args)
    monkeypatch.setattr(entry.subprocess, 'run', fail)
    with pytest.raises(entry.subprocess.CalledProcessError):
        entry.main()


def test_secrets_are_not_part_of_docker_context():
    root = Path(__file__).resolve().parents[1]
    assert '.env.*' in (root/'.dockerignore').read_text()
    docker = (root/'Dockerfile').read_text()
    assert 'railway_entrypoint.py' in docker and 'COPY . ' not in docker
    assert '.env' not in docker
