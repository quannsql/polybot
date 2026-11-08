#!/usr/bin/env bash
set -euo pipefail
umask 077
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$TASK_ROOT"
ACTION="${1:-help}"
IMAGE="polybot-twap:20261109"
NAME="polybot-twap"
RUNTIME="/opt/polybot/live/twap.env"
ACCOUNT="${POLYBOT_ACCOUNT_ENV:-/opt/polybot/secrets/account.env}"
VOLUME="${POLYBOT_VOLUME:-}"

if [[ "$ACTION" == help ]]; then
  echo 'Commands: init | build | public-check | check | start | paper | logs | status | stop | reconcile | backup'
  exit 0
fi
if [[ "$EUID" -ne 0 ]]; then
  echo 'Run with sudo bash deploy_twap_oracle.sh COMMAND' >&2
  exit 1
fi

choose_volume() {
  if [[ -z "$VOLUME" ]]; then
    local candidates=() current old
    for old in polybot-twap polybot-live polybot-live-canary; do
      if docker container inspect "$old" >/dev/null 2>&1; then
        current="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}' "$old")"
        [[ -z "$current" ]] || candidates+=("$current")
      fi
    done
    if [[ "${#candidates[@]}" -eq 0 ]]; then
      for old in polybot-twap-paper polybot-paper; do
        if docker container inspect "$old" >/dev/null 2>&1; then
          current="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}}{{end}}{{end}}' "$old")"
          [[ -z "$current" ]] || candidates+=("$current")
        fi
      done
    fi
    if [[ "${#candidates[@]}" -gt 0 ]]; then
      mapfile -t candidates < <(printf '%s\n' "${candidates[@]}" | sort -u)
      if [[ "${#candidates[@]}" -ne 1 ]]; then
        echo 'More than one old data volume found. Select the existing LIVE volume using POLYBOT_VOLUME; none was modified:' >&2
        printf '%s\n' "${candidates[@]}" >&2
        exit 1
      fi
      VOLUME="${candidates[0]}"
    else
      VOLUME='polybot-live-data'
    fi
  fi
  if [[ "$VOLUME" == /* ]]; then
    [[ -d "$VOLUME" ]] || { echo 'Configured data directory does not exist' >&2; exit 1; }
  else
    docker volume inspect "$VOLUME" >/dev/null 2>&1 || docker volume create "$VOLUME" >/dev/null
  fi
  echo "Using existing/persistent data: $VOLUME"
}

environment_args() {
  [[ -f "$RUNTIME" ]] || { echo "Run init first: $RUNTIME is missing" >&2; exit 1; }
  ENV_ARGS=()
  if [[ -f "$ACCOUNT" ]]; then ENV_ARGS+=(--env-file "$ACCOUNT"); fi
  ENV_ARGS+=(--env-file "$RUNTIME")
}

stop_old() {
  local old
  for old in polybot-live polybot-live-canary polybot-paper polybot-twap-paper; do
    if docker container inspect "$old" >/dev/null 2>&1; then
      docker update --restart=no "$old" >/dev/null
      docker stop --time 30 "$old" >/dev/null
      echo "Stopped previous container: $old (state preserved)"
    fi
  done
}

backup() {
  local dir filename
  dir='/opt/polybot/backups'
  install -d -m 700 "$dir"
  filename="pre-twap-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz"
  docker run --rm -v "$VOLUME:/data:ro" -v "$dir:/backup" "$IMAGE" \
    tar -czf "/backup/$filename" -C /data .
  echo "State backup: $dir/$filename"
}

case "$ACTION" in
  init)
    install -d -m 700 /opt/polybot/live /opt/polybot/secrets
    if [[ ! -f "$RUNTIME" ]]; then
      install -m 600 .env.live.example "$RUNTIME"
      echo "Created runtime: $RUNTIME"
    else
      echo "Preserved existing runtime: $RUNTIME"
    fi
    echo 'Existing OCI Vault metadata is reused. For file secrets use /opt/polybot/secrets/account.env.'
    ;;
  build)
    docker build -f Dockerfile.live -t "$IMAGE" .
    ;;
  public-check)
    docker run --rm "$IMAGE" python -B verify_twap_runtime.py --public-only
    ;;
  check)
    environment_args
    docker run --rm "${ENV_ARGS[@]}" "$IMAGE" python -B verify_twap_runtime.py --feed-seconds 70
    ;;
  start)
    choose_volume
    environment_args
    if docker container inspect "$NAME" >/dev/null 2>&1; then
      if [[ "$(docker inspect --format '{{.State.Running}}' "$NAME")" == true ]]; then
        echo 'TWAP container already running. Stop it before replacing its image; journal is preserved.' >&2
        exit 1
      fi
    fi
    stop_old
    backup
    docker run --rm "${ENV_ARGS[@]}" "$IMAGE" python -B verify_twap_runtime.py --feed-seconds 70
    # Remove only this stopped container; do not remove any volume or journal.
    if docker container inspect "$NAME" >/dev/null 2>&1; then docker rm "$NAME" >/dev/null; fi
    docker run -d --name "$NAME" --restart unless-stopped \
      --read-only --cap-drop ALL --security-opt no-new-privileges \
      --pids-limit 128 --memory 512m --cpus 1 --tmpfs /tmp:rw,noexec,nosuid,size=64m \
      --log-opt max-size=10m --log-opt max-file=5 \
      "${ENV_ARGS[@]}" -v "$VOLUME:/data" "$IMAGE"
    echo 'TWAP live started. Missing opening waits for the next full market. Up to5 lifetime submissions, $20 target each.'
    ;;
  paper)
    choose_volume; environment_args
    if docker container inspect polybot-twap-paper >/dev/null 2>&1; then
      echo 'polybot-twap-paper already exists; inspect/stop it before recreating' >&2; exit 1
    fi
    docker run -d --name polybot-twap-paper --restart unless-stopped \
      "${ENV_ARGS[@]}" -v "$VOLUME:/data" \
      -e POLYMARKET_MODE=paper -e POLYMARKET_DRY_RUN=1 \
      -e POLYMARKET_STATE_PATH=/data/twap_paper.sqlite3 \
      -e POLYMARKET_DECISION_LOG=/data/twap_paper_decisions.jsonl \
      -e POLYMARKET_ORACLE_LOG=/data/twap_paper_oracle.jsonl "$IMAGE"
    ;;
  stop)
    if docker container inspect "$NAME" >/dev/null 2>&1; then
      docker update --restart=no "$NAME" >/dev/null
      docker stop --time 30 "$NAME"
    fi
    ;;
  logs)
    docker logs --tail 100 -f "$NAME"
    ;;
  status)
    choose_volume; environment_args
    if docker container inspect "$NAME" >/dev/null 2>&1; then
      docker inspect --format 'Running={{.State.Running}} Image={{.Config.Image}} Restart={{.HostConfig.RestartPolicy.Name}}' "$NAME"
    fi
    docker run --rm "${ENV_ARGS[@]}" -v "$VOLUME:/data" "$IMAGE" python -B manage_twap.py status
    ;;
  reconcile)
    choose_volume; environment_args
    if docker container inspect "$NAME" >/dev/null 2>&1 && [[ "$(docker inspect --format '{{.State.Running}}' "$NAME")" == true ]]; then
      echo 'Stop TWAP first; reconciliation never runs alongside its trading process' >&2; exit 1
    fi
    docker run --rm "${ENV_ARGS[@]}" -v "$VOLUME:/data" "$IMAGE" python -B manage_twap.py reconcile
    ;;
  backup)
    choose_volume
    if docker container inspect "$NAME" >/dev/null 2>&1 && [[ "$(docker inspect --format '{{.State.Running}}' "$NAME")" == true ]]; then
      echo 'Stop TWAP before a filesystem backup of its SQLite journal' >&2; exit 1
    fi
    stop_old; backup
    ;;
  *) echo "Unknown action: $ACTION" >&2; exit 1 ;;
esac
