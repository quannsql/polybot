"""Railway worker: public probe by default; dashboard Variables supply secrets."""
import os
from pathlib import Path
import subprocess
import sys


def prepare_environment():
    action = os.getenv('POLYMARKET_RAILWAY_ACTION', 'probe').strip().lower()
    if action not in {'probe', 'check', 'run'}:
        raise ValueError('POLYMARKET_RAILWAY_ACTION must be probe, check or run')
    if action == 'probe':
        return action
    # Railway has no OCI Instance Principal. Never contact metadata for keys.
    os.environ['OCI_POLYBOT_USE_INSTANCE_METADATA'] = '0'
    if os.getenv('OCI_POLYBOT_SECRET_OCID', '').strip():
        raise ValueError('Use the four account Variables on Railway, not OCI_POLYBOT_SECRET_OCID')
    mode = os.getenv('POLYMARKET_MODE', 'paper').strip().lower()
    if mode not in {'paper', 'live'}:
        raise ValueError('POLYMARKET_MODE must be paper or live')
    os.environ['POLYMARKET_MODE'] = mode
    if action == 'check':
        return action
    mount = Path('/data').resolve()
    if os.getenv('RAILWAY_VOLUME_MOUNT_PATH') != '/data' or not mount.is_mount():
        raise RuntimeError('Attach a persistent Railway volume at /data before running the bot')
    defaults = {
        'POLYMARKET_STATE_PATH': f'/data/twap_{"paper" if mode == "paper" else "state"}.sqlite3',
        'POLYMARKET_DECISION_LOG': f'/data/twap_{mode}_decisions.jsonl',
        'POLYMARKET_ORACLE_LOG': f'/data/twap_{mode}_oracle.jsonl',
        'POLYMARKET_LEGACY_STATE_PATH': '/data/live_state.json',
    }
    for name, default in defaults.items():
        value = Path(os.environ.setdefault(name, default)).resolve()
        if not value.is_relative_to(mount) or value == mount:
            raise ValueError(f'{name} must be a file inside the persistent /data volume')
    # Do not invent live confirmation/eligibility: TwapSettings validates them.
    from polymarket_bot.twap_config import TwapSettings
    TwapSettings.from_env()
    return action


def main():
    action = prepare_environment()
    if action in {'probe', 'check'}:
        args = ['--public-only'] if action == 'probe' else ['--feed-seconds', '70']
        print(f'Railway {action}: no BUY/SELL orders; exits after verification', flush=True)
        try:
            subprocess.run([sys.executable, '-B', 'verify_twap_runtime.py', *args], check=True)
        except subprocess.CalledProcessError as error:
            print(f'Railway {action} failed (exit {error.returncode}). Read the geography endpoint_blocked/policy_blocked fields above. '
                  'For probe/check, set Restart Policy to Never to avoid repeated failed probes.', flush=True)
            raise SystemExit(error.returncode if error.returncode > 0 else 1) from None
    else:
        # Replace PID1 so the existing engine receives Railway SIGTERM directly.
        os.execv(sys.executable, [sys.executable, '-B', 'run_bot.py'])


if __name__ == '__main__':
    main()
