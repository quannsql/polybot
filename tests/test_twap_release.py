import hashlib
import json
from pathlib import Path
import tarfile


def test_release_matches_current_source_and_contains_no_runtime_secrets():
    root=Path(__file__).resolve().parents[1]
    path=root/'data/releases/polybot-twap-live-20261109.tar.gz'
    if not path.exists():
        import pytest
        pytest.skip('Build release with make_twap_release.py first')
    with tarfile.open(path) as archive:
        names=archive.getnames()
        assert all(not name.startswith(('/','data/','.git/','.venv')) and '..' not in Path(name).parts for name in names)
        assert '.env' not in names and not any(name.endswith(('.key','.pem','.sqlite3')) for name in names)
        assert 'polymarket_bot/twap_engine.py' in names and 'ORACLE_TWAP_LIVE_GUIDE.md' in names
        manifest=json.loads(archive.extractfile('RELEASE_MANIFEST.json').read())
        assert manifest['strategy']=='twap60_spot_1400_v1'
        assert manifest['sdk']=='polymarket-client==0.17.0'
        for name,expected in manifest['files'].items():
            value=archive.extractfile(name).read()
            assert hashlib.sha256(value).hexdigest()==expected
            assert value==(root/name).read_bytes().replace(b'\r\n',b'\n')
        for name in ['deploy_twap_oracle.sh','deploy_live_oracle.sh']:
            assert b'\r\n' not in archive.extractfile(name).read()


def test_deployment_reuses_journal_and_limits_new_trial():
    root=Path(__file__).resolve().parents[1]
    script=(root/'deploy_twap_oracle.sh').read_text()
    env=(root/'.env.live.example').read_text()
    assert 'twap_state.sqlite3' in env and 'POLYMARKET_LIVE_MAX_ORDERS=5' in env
    assert 'POLYMARKET_DAILY_LOSS_STOP=1' in env
    assert 'docker volume rm' not in script and 'docker system prune' not in script
    assert 'backup' in script and '--restart=no' in script
    assert 'verify_twap_runtime.py --feed-seconds 70' in script
