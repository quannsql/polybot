#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

BOT=polybot-twap
DASHBOARD=polybot-twap-dashboard
PORT=8787

bot_setting() {
  local key="$1" default="$2" value
  value="$(docker inspect --format "{{range .Config.Env}}{{if eq (index (split . \"=\") 0) \"$key\"}}{{println .}}{{end}}{{end}}" "$BOT")"
  value="${value#*=}"
  printf '%s\n' "${value:-$default}"
}

case "${1:-help}" in
  start)
    volume="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}' "$BOT")"
    if [[ -z "$volume" ]]; then
      echo 'The TWAP bot must have a data mount at /data.' >&2
      exit 1
    fi
    journal="$(bot_setting POLYMARKET_STATE_PATH /data/twap_state.sqlite3)"
    decisions="$(bot_setting POLYMARKET_DECISION_LOG /data/twap_decisions.jsonl)"
    oracle="$(bot_setting POLYMARKET_ORACLE_LOG /data/twap_oracle.jsonl)"
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
      -v "$volume:/data:ro" "$DASHBOARD" python -B twap_dashboard.py \
      --db "$journal" --decisions "$decisions" --oracle "$oracle" \
      --max-orders "$max_orders" --entry-end-seconds "$entry_end" --port "$PORT"
    echo "Dashboard launched on 127.0.0.1:$PORT. Open it through an SSH tunnel."
    ;;
  status) docker inspect --format 'Running={{.State.Running}} RestartCount={{.RestartCount}}' "$DASHBOARD" ;;
  logs) docker logs --tail 50 "$DASHBOARD" ;;
  stop) docker stop "$DASHBOARD" ;;
  *) echo "Usage: sudo bash $0 {start|status|logs|stop}" ;;
esac
