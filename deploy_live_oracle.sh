#!/bin/sh
set -eu

cd /home/ubuntu/polybot
sudo install -d -m 700 /opt/polybot/live
sudo sh -c 'umask 077; cat > /opt/polybot/live/runtime.env' <<'EOF'
POLYMARKET_MODE=live
POLYMARKET_DRY_RUN=0
POLYMARKET_LIVE_CONFIRM=I_UNDERSTAND_ONE_20_USD_ORDER_CAN_LOSE_ALL
POLYMARKET_ACCOUNT_ELIGIBILITY_CONFIRMED=1
OCI_POLYBOT_USE_INSTANCE_METADATA=1
POLYMARKET_EXECUTION_STRATEGY=legacy_1230_ref85
POLYMARKET_DATA_SOURCE=lighter
POLYMARKET_DECISION_DELAY_SECONDS=750
POLYMARKET_MAX_ENTRY_DELAY_SECONDS=755
POLYMARKET_POLL_SECONDS=1
POLYMARKET_LIVE_QUOTE_MAX_AGE_MS=1500
POLYMARKET_MARKET_EVENT_DEBOUNCE_MS=100
POLYMARKET_SIGNAL_POLICY=latest_5m
POLYMARKET_SESSION_START_UTC=0
POLYMARKET_SESSION_END_UTC=0
POLYMARKET_MIN_ENTRY_PRICE=0.85
POLYMARKET_REFERENCE_MAX_AGE_SECONDS=75
POLYMARKET_REFERENCE_PRICE_PADDING=0.01
POLYMARKET_MAX_SPREAD=1.0
POLYMARKET_LIVE_FIXED_STAKE_USD=20
POLYMARKET_MAX_STAKE_USD=20
POLYMARKET_BANKROLL_USD=50
POLYMARKET_LIVE_MAX_ORDERS=1
POLYMARKET_LIVE_MAX_PRICE=0.99
POLYMARKET_LIVE_PRICE_SLIPPAGE=0.01
POLYMARKET_CALIBRATION_PATH=/app/live_1230_strategy_approval.json
POLYMARKET_STATE_PATH=/data/live_state.json
POLYMARKET_DECISION_LOG=/data/live_decisions.jsonl
EOF

sudo docker build -f Dockerfile.live -t polybot-live:1230 .
sudo docker run --rm --env-file /opt/polybot/live/runtime.env \
  polybot-live:1230 python -B verify_live_account.py
sudo docker volume inspect polybot-live-data >/dev/null 2>&1 || \
  sudo docker volume create polybot-live-data >/dev/null
if sudo docker container inspect polybot-live >/dev/null 2>&1; then
  sudo docker rm -f polybot-live >/dev/null
fi
sudo docker run -d --name polybot-live --restart unless-stopped \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 512m --cpus 1 --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  --log-opt max-size=5m --log-opt max-file=3 \
  --env-file /opt/polybot/live/runtime.env \
  -v polybot-live-data:/data \
  polybot-live:1230
