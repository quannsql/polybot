#!/bin/sh
set -eu
cd /home/ubuntu/polybot
sudo install -d -m 700 /opt/polybot/dashboard
if ! sudo test -s /opt/polybot/dashboard/password; then
  sudo sh -c 'umask 077; openssl rand -hex 16 > /opt/polybot/dashboard/password'
fi
sudo docker build -f Dockerfile.dashboard -t polybot-dashboard .
sudo docker network inspect polybot-dashboard-net >/dev/null 2>&1 || sudo docker network create polybot-dashboard-net
if sudo docker container inspect polybot-dashboard >/dev/null 2>&1; then
  sudo docker rm -f polybot-dashboard >/dev/null
fi
sudo docker run -d --name polybot-dashboard --restart unless-stopped \
  --network polybot-dashboard-net --read-only --cap-drop ALL \
  --security-opt no-new-privileges --memory 192m --cpus 0.5 \
  --log-opt max-size=5m --log-opt max-file=2 \
  -e LIVE_MODE_ENABLED=1 \
  -e 'LIVE_STRATEGY=DCA legacy · 12:30' \
  -e LIVE_STAKE_USD=20 -e LIVE_BANKROLL_USD=50 \
  -e LIVE_ENTRY_SECONDS=750 -e LIVE_MAX_ATTEMPTS=1 \
  -v polybot-paper-data:/data:ro \
  -v polybot-legacy-data:/robust:ro \
  -v polybot-live-data:/live:ro \
  -v /opt/polybot/dashboard/password:/run/secrets/paper_password:ro \
  polybot-dashboard
if ! sudo docker container inspect polybot-dashboard-tunnel >/dev/null 2>&1; then
  sudo docker run -d --name polybot-dashboard-tunnel --restart unless-stopped \
    --network polybot-dashboard-net --read-only --cap-drop ALL \
    --security-opt no-new-privileges --memory 192m \
    --log-opt max-size=5m --log-opt max-file=2 \
    cloudflare/cloudflared:latest tunnel --no-autoupdate --url http://polybot-dashboard:8080
fi
