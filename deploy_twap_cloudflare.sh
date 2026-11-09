#!/usr/bin/env bash
set -euo pipefail

DASHBOARD=polybot-twap-dashboard
TUNNEL=polybot-twap-cloudflared
IMAGE=cloudflare/cloudflared:latest
PORT=8787

dashboard_is_ready() {
  if ! docker inspect --format '{{.State.Running}}' "$DASHBOARD" 2>/dev/null | grep -qx true; then
    echo 'The TWAP dashboard container is not running. Start it with deploy_twap_dashboard.sh first.' >&2
    exit 1
  fi
  if ! command -v curl >/dev/null 2>&1; then
    echo 'curl is required for the local dashboard health check.' >&2
    exit 1
  fi
  for _ in {1..30}; do
    if curl --fail --silent --max-time 2 -H 'Host: 127.0.0.1' \
      "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      return 0
    fi
    if ! docker inspect --format '{{.State.Running}}' "$DASHBOARD" 2>/dev/null | grep -qx true; then
      echo 'The dashboard container exited before its health check passed:' >&2
      docker logs --tail 80 "$DASHBOARD" >&2
      exit 1
    fi
    sleep 1
  done
  echo 'The dashboard did not pass its loopback health check within 30 seconds:' >&2
  docker logs --tail 80 "$DASHBOARD" >&2
  exit 1
}

case "${1:-help}" in
  start)
    dashboard_is_ready
    docker pull "$IMAGE"
    if docker container inspect "$TUNNEL" >/dev/null 2>&1; then
      docker rm -f "$TUNNEL" >/dev/null
    fi
    # Host networking reaches the dashboard's loopback listener without publishing a port.
    docker run -d --name "$TUNNEL" --restart unless-stopped \
      --network host --read-only --cap-drop ALL --security-opt no-new-privileges \
      --memory 96m --cpus 0.25 --pids-limit 32 \
      --tmpfs /tmp:rw,noexec,nosuid,size=16m \
      --log-opt max-size=2m --log-opt max-file=2 \
      "$IMAGE" tunnel --no-autoupdate \
      --url "http://127.0.0.1:${PORT}" \
      --http-host-header 127.0.0.1
    tunnel_url=''
    for _ in {1..30}; do
      tunnel_url="$(docker logs "$TUNNEL" 2>&1 | grep -Eo 'https://[-[:alnum:]]+\.trycloudflare\.com' | head -n 1 || true)"
      if [[ -n "$tunnel_url" ]]; then
        break
      fi
      if ! docker inspect --format '{{.State.Running}}' "$TUNNEL" 2>/dev/null | grep -qx true; then
        echo 'cloudflared exited before publishing a Quick Tunnel URL:' >&2
        docker logs --tail 80 "$TUNNEL" >&2
        exit 1
      fi
      sleep 1
    done
    echo 'Cloudflare Quick Tunnel status:'
    docker inspect --format 'Running={{.State.Running}} RestartCount={{.RestartCount}}' "$TUNNEL"
    if [[ -n "$tunnel_url" ]]; then
      echo "Dashboard URL: $tunnel_url"
      echo 'Sign in with the dashboard password. Your browser session is saved for up to 30 days.'
    else
      echo 'cloudflared is running, but the URL did not appear within 30 seconds. Check logs with this script.' >&2
      docker logs --tail 80 "$TUNNEL"
      exit 1
    fi
    ;;
  status)
    docker inspect --format 'Running={{.State.Running}} RestartCount={{.RestartCount}}' "$TUNNEL"
    docker logs "$TUNNEL" 2>&1 | grep -Eo 'https://[[:alnum:]-]+\.trycloudflare\.com' | tail -n 1 || true
    ;;
  logs)
    docker logs --tail 80 "$TUNNEL"
    ;;
  stop)
    docker rm -f "$TUNNEL"
    ;;
  *)
    echo "Usage: sudo bash $0 {start|status|logs|stop}"
    ;;
esac
