# Polybot TWAP Monitor

The read-only dashboard tracks the live bot journal, Chainlink 60-second TWAP
and Spot feeds, market timing, order decisions, CLOB collateral and redemption
state. The interface is in English and refreshes every 10 seconds.

Available account collateral is read from Polymarket's authenticated CLOB client
by a separate sidecar once per minute. The sidecar uses the bot's existing
account environment and writes only the numeric pUSD balance and timestamp to
its own restricted snapshot file. The dashboard container cannot read the
wallet credentials or the bot's writable data volume. A current balance
snapshot appears after the sidecar's first successful poll.

The order table shows signed shares, notional, estimated fee, limit price,
resolution and redemption details. A verified cash P&amp;L is not available
from the current journal because it does not yet persist confirmed trade and
fee receipts. Win rate uses only markets resolved in the journal.

## Deploy on the Oracle VM

Run these commands in the Ubuntu SSH session:

```bash
cd ~/polybot-twap
git pull --ff-only origin codex/twap-railway
sudo bash deploy_twap_dashboard.sh start
sudo bash deploy_twap_cloudflare.sh start
```

On first start, the dashboard script generates a high-entropy dashboard
password and prints it once. The password is stored root-only at
`/opt/polybot/secrets/dashboard_password`; retrieve it on the VM with:

```bash
sudo cat /opt/polybot/secrets/dashboard_password
```

Use the `https://….trycloudflare.com` URL printed by the Cloudflare command and
sign in with that password. The browser receives a signed, HttpOnly, SameSite
cookie that lasts up to 30 days, so page reloads and browser restarts do not
require another dashboard login. Use **Log out** to clear the browser cookie.
The password hash and signing key are stored as root-only files outside the bot
data volume.

Cloudflare Quick Tunnel URLs are temporary and change when the tunnel is
recreated. A new hostname uses a different browser cookie scope, so sign in once
on the new URL. Quick Tunnels are intended for testing and have no uptime
guarantee. The dashboard itself remains password protected. See
[Cloudflare Quick Tunnel limitations](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Check status and logs

Run these commands in the Ubuntu SSH session:

```bash
cd ~/polybot-twap
sudo bash deploy_twap_dashboard.sh status
sudo bash deploy_twap_dashboard.sh logs
sudo bash deploy_twap_cloudflare.sh status
sudo bash deploy_twap_cloudflare.sh logs
```

The dashboard and account monitor are separate from the trading container. The
dashboard binds only to `127.0.0.1:8787`; Cloudflare Tunnel connects to that
loopback address and does not publish port 8787. The balance sidecar runs with
read-only trading access and refreshes the collateral snapshot once per minute.

To stop remote access, stop the tunnel:

```bash
sudo bash deploy_twap_cloudflare.sh stop
```

To stop both dashboard services:

```bash
sudo bash deploy_twap_dashboard.sh stop
```

## Local SSH access

If needed, open a second PowerShell window and forward the dashboard over SSH:

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8787:127.0.0.1:8787 -i "$env:USERPROFILE\.ssh\polybot_oracle" ubuntu@129.151.220.29
```

Keep that window open and browse to [http://127.0.0.1:8787](http://127.0.0.1:8787).
Local access also requires the dashboard password.
