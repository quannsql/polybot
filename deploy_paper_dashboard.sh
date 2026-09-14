#!/bin/sh
set -eu
cd /home/ubuntu/polybot
sudo install -d -m 700 /opt/polybot/dashboard
if ! sudo test -s /opt/polybot/dashboard/password; then
  sudo sh -c 'umask 077; openssl rand -hex 16 > /opt/polybot/dashboard/password'
fi
sudo docker build -f Dockerfile.dashboard -t polybot-dashboard .
sudo docker network inspect polybot-dashboard-net >/dev/null 2>&1 || sudo docker network create polybot-dashboard-net
sudo docker run -d --name polybot-dashboard --restart unless-stopped \
  --network polybot-dashboard-net --read-only --cap-drop ALL \
  --security-opt no-new-privileges --memory 192m --cpus 0.5 \
  --log-opt max-size=5m --log-opt max-file=2 \
  -v polybot-paper-data:/data:ro \
  -v /opt/polybot/dashboard/password:/run/secrets/paper_password:ro \
  polybot-dashboard
sudo docker run -d --name polybot-dashboard-tunnel --restart unless-stopped \
  --network polybot-dashboard-net --read-only --cap-drop ALL \
  --security-opt no-new-privileges --memory 192m \
  --log-opt max-size=5m --log-opt max-file=2 \
  cloudflare/cloudflared:latest tunnel --no-autoupdate --url http://polybot-dashboard:8080
