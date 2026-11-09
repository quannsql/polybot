#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

BOT=polybot-twap
DASHBOARD=polybot-twap-dashboard
ACCOUNT_MONITOR=polybot-twap-account-monitor
ACCOUNT_IMAGE=polybot-twap-account-monitor:latest
PORT=8787
RUNTIME=/opt/polybot/live/twap.env
ACCOUNT_ENV=/opt/polybot/secrets/account.env
SECRET_DIR=/opt/polybot/secrets
ACCOUNT_DIR=/opt/polybot/live/dashboard-data

bot_setting() {
  local key="$1" default="$2" value
  value="$(docker inspect --format "{{range .Config.Env}}{{if eq (index (split . \"=\") 0) \"$key\"}}{{println .}}{{end}}{{end}}" "$BOT")"
  value="${value#*=}"
  printf '%s\n' "${value:-$default}"
}

case "${1:-help}" in
  start)
    install -d -m 700 "$SECRET_DIR"
    install -d -m 700 "$ACCOUNT_DIR"
    if [[ ! -f "$ACCOUNT_DIR/twap_account.json" ]]; then
      install -m 600 /dev/null "$ACCOUNT_DIR/twap_account.json"
    fi
    if [[ ! -f "$SECRET_DIR/dashboard_password" || ! -f "$SECRET_DIR/dashboard_password_salt" \
      || ! -f "$SECRET_DIR/dashboard_password_hash" || ! -f "$SECRET_DIR/dashboard_password_rounds" \
      || ! -f "$SECRET_DIR/dashboard_session_secret" ]]; then
      python3 - "$SECRET_DIR" <<'PY'
import hashlib
import os
from pathlib import Path
import secrets
import sys

directory = Path(sys.argv[1])
password = secrets.token_urlsafe(18)
salt = secrets.token_bytes(24)
rounds = 600_000
password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, rounds)
values = {
    'dashboard_password': password + '\n',
    'dashboard_password_salt': salt.hex() + '\n',
    'dashboard_password_hash': password_hash.hex() + '\n',
    'dashboard_password_rounds': str(rounds) + '\n',
    'dashboard_session_secret': secrets.token_bytes(48).hex() + '\n',
}
for name, value in values.items():
    path = directory / name
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(value, encoding='ascii')
    os.chmod(temporary, 0o600)
    temporary.replace(path)
print('Generated a new dashboard password. Retrieve it with: sudo cat /opt/polybot/secrets/dashboard_password')
print('Dashboard password: ' + password)
PY
    fi
    volume="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}' "$BOT")"
    if [[ -z "$volume" ]]; then
      echo 'The TWAP bot must have a data mount at /data.' >&2
      exit 1
    fi
    journal="$(bot_setting POLYMARKET_STATE_PATH /data/twap_state.sqlite3)"
    decisions="$(bot_setting POLYMARKET_DECISION_LOG /data/twap_decisions.jsonl)"
    oracle="$(bot_setting POLYMARKET_ORACLE_LOG /data/twap_oracle.jsonl)"
    account_log=/run/data/twap_account.json
    max_orders="$(bot_setting POLYMARKET_LIVE_MAX_ORDERS 5)"
    entry_end="$(bot_setting POLYMARKET_MAX_ENTRY_DELAY_SECONDS 845)"
    for path in "$journal" "$decisions" "$oracle"; do
      if [[ "$path" != /data/* ]]; then
        echo 'The TWAP journal and logs must be inside /data.' >&2
        exit 1
      fi
    done
    docker build -f Dockerfile.twap-dashboard -t "$DASHBOARD" .
    if docker container inspect "$DASHBOARD" >/dev/null 2>&1; then
      docker rm -f "$DASHBOARD" >/dev/null
    fi
    # Host networking lets the HTTP server itself bind only to loopback.
    docker run -d --name "$DASHBOARD" --restart unless-stopped \
      --network host --read-only --cap-drop ALL --security-opt no-new-privileges \
      --memory 64m --cpus 0.25 --pids-limit 32 --log-opt max-size=2m --log-opt max-file=2 \
      -v "$volume:/data:ro" \
      -v "$ACCOUNT_DIR:/run/data:ro" \
      -v "$SECRET_DIR/dashboard_password_salt:/run/secrets/dashboard_password_salt:ro" \
      -v "$SECRET_DIR/dashboard_password_hash:/run/secrets/dashboard_password_hash:ro" \
      -v "$SECRET_DIR/dashboard_password_rounds:/run/secrets/dashboard_password_rounds:ro" \
      -v "$SECRET_DIR/dashboard_session_secret:/run/secrets/dashboard_session_secret:ro" \
      "$DASHBOARD" python -B twap_dashboard.py \
      --db "$journal" --decisions "$decisions" --oracle "$oracle" \
      --account "$account_log" \
      --max-orders "$max_orders" --entry-end-seconds "$entry_end" --port "$PORT"
    echo "Password-protected dashboard launched on 127.0.0.1:$PORT. Browser sessions last up to 30 days."
    bot_image="$(docker inspect --format '{{.Config.Image}}' "$BOT")"
    if [[ -f "$RUNTIME" ]] && docker image inspect "$bot_image" >/dev/null 2>&1; then
      env_args=()
      if [[ -f "$ACCOUNT_ENV" ]]; then env_args+=(--env-file "$ACCOUNT_ENV"); fi
      env_args+=(--env-file "$RUNTIME")
      docker build --build-arg "BASE_IMAGE=$bot_image" \
        -f Dockerfile.twap-account-monitor -t "$ACCOUNT_IMAGE" .
      if docker container inspect "$ACCOUNT_MONITOR" >/dev/null 2>&1; then
        docker rm -f "$ACCOUNT_MONITOR" >/dev/null
      fi
      docker run -d --name "$ACCOUNT_MONITOR" --restart unless-stopped \
        --read-only --cap-drop ALL --security-opt no-new-privileges \
        --memory 128m --cpus 0.25 --pids-limit 32 \
        --tmpfs /tmp:rw,noexec,nosuid,size=16m \
        --log-opt max-size=2m --log-opt max-file=2 \
        "${env_args[@]}" -e POLYBOT_ACCOUNT_SNAPSHOT_PATH=/account-data/twap_account.json \
        -v "$ACCOUNT_DIR:/account-data" "$ACCOUNT_IMAGE"
      echo 'Read-only CLOB balance monitor launched. It refreshes once per minute.'
    else
      echo 'Account balance monitor was not started. Runtime environment or bot image is unavailable.' >&2
    fi
    ;;
  status)
    docker inspect --format 'Dashboard Running={{.State.Running}} RestartCount={{.RestartCount}}' "$DASHBOARD"
    if docker container inspect "$ACCOUNT_MONITOR" >/dev/null 2>&1; then
      docker inspect --format 'BalanceMonitor Running={{.State.Running}} RestartCount={{.RestartCount}}' "$ACCOUNT_MONITOR"
    else
      echo 'BalanceMonitor is not installed.'
    fi
    ;;
  logs)
    docker logs --tail 50 "$DASHBOARD"
    if docker container inspect "$ACCOUNT_MONITOR" >/dev/null 2>&1; then docker logs --tail 20 "$ACCOUNT_MONITOR"; fi
    ;;
  stop)
    docker stop "$DASHBOARD"
    if docker container inspect "$ACCOUNT_MONITOR" >/dev/null 2>&1; then docker stop "$ACCOUNT_MONITOR"; fi
    ;;
  *) echo "Usage: sudo bash $0 {start|status|logs|stop}" ;;
esac
