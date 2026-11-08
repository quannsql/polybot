# Triển khai TWAP live trên Ubuntu Oracle Cloud — SERVER_PUBLIC_IP

Bản này thay luồng live Bollinger/Variant B bằng **BTC15m, Chainlink TWAP60 +
spot Chainlink**. Hướng được khóa ở14:00, TWAP dẫn>=0,05%, spot>=TWAP để mua Up
hoặc spot<=TWAP để mua Down. Giữ tới settlement; chưa tự bán cắt lỗ.

Mục tiêu mỗi lệnh gồm phí là$20; SDK để dư1cent và kiểm tra lại chi phí theo
fee metadata trước gửi. Phí thay đổi tại match vẫn là rủi ro thực thi. Mặc định
tối đa**5 lần gửi/intent mới**, một lần/market, không reset khi restart; dừng
entry sau một lệnh thua đã được xác nhận trong ngày UTC. Chỉ giữ một vị thế
chưa xác nhận kết quả. Auto-redeem vị thế mới thắng khi SDK hỗ trợ ví đã cấu hình.

Tôi đã kiểm tra cổng22 của IP trên: server trả OpenSSH của Ubuntu. Chưa đăng
nhập, chưa triển khai server và chưa gửi lệnh Polymarket. SSH private key chưa
có trên PC; phần1–3 giúp thiết lập quyền truy cập VM hiện tại.

## 1. Tạo SSH key trên PC Windows — PowerShell

Mở PowerShell trên PC, chạy từng dòng:

```powershell
$KeyDir = Join-Path $env:USERPROFILE '.ssh'
New-Item -ItemType Directory -Path $KeyDir -Force
$KeyPath = Join-Path $KeyDir 'polybot_oracle'
Test-Path -LiteralPath $KeyPath
```

Nếu kết quả cuối là `False`, tạo key. Nếu `True`, giữ key đó, không ghi đè.

```powershell
ssh-keygen -t ed25519 -a 64 -C "polybot-oracle-pc" -f "$KeyPath"
```

Nhập passphrase bảo vệ key và nhập lại khi được hỏi. Sau đó:

```powershell
$KeyOwner = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
icacls "$KeyPath" /inheritance:r
icacls "$KeyPath" /grant:r "${KeyOwner}:(R)"
Get-Content -LiteralPath "$KeyPath.pub"
```

Sao chép **toàn bộ một dòng bắt đầu bằng `ssh-ed25519`**. Đây là public key.
File không có `.pub` là private key, giữ trên PC. SSH key vào server và private
key ví ký lệnh Polymarket là hai loại key khác nhau.

Tạo key trên PC **chưa tự cho phép đăng nhập VM**. Cần thêm public key vào
`/home/ubuntu/.ssh/authorized_keys` của VM.
[OpenSSH trên Windows](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_keymanagement).

## 2. Cài public key lên VM hiện tại

Nếu vẫn còn phiên SSH/quyền sudo từ máy cũ, dùng phiên đó và chạy phần2.3 với
`sudo`/root. Đây là cách nhanh nhất và không cần reboot.

Nếu không còn key cũ hoặc phiên đăng nhập, dùng Oracle Console để vào recovery.
Không tạo lại instance hoặc xóa boot volume vì dữ liệu/Vault/state cũ cần giữ.

### 2.1. Mở serial console qua trình duyệt

1. Oracle Cloud Console → Compute → Instances → chọn VM có IP `SERVER_PUBLIC_IP`.
2. Tìm **Console connection**, có thể nằm dưới **OS Management** hoặc Resources
   tùy giao diện, chọn **Launch Cloud Shell connection**.
3. Chờ console kết nối. Cloud Shell kết nối được console không đồng nghĩa đã
   đăng nhập Ubuntu. Nếu thấy `login:` và chưa từng đặt password, không có
   password mặc định để nhập; chuyển bước recovery bên dưới.

Cloud Shell dùng kết nối console riêng, không yêu cầu bạn có SSH key cũ của
Ubuntu. [Oracle Console connection](https://docs.oracle.com/en-us/iaas/Content/Compute/References/serialconsole.htm).

### 2.2. Vào shell recovery Ubuntu

Việc này reboot VM và tạm dừng các dịch vụ trên máy.

1. Giữ console ở một tab. Tại tab chi tiết instance, chọn **Reboot**.
2. Quay lại console, nhấn `Esc` khi VM boot để mở GRUB. Nếu vào UEFI Boot
   Manager, chọn mục boot Ubuntu/boot volume, rồi tiếp tục mở menu GRUB.
3. Ở menu **GNU GRUB**, chọn dòng Ubuntu, nhấn `e`.
4. Tìm dòng bắt đầu bằng `linux` và có `root=UUID=...`. **Giữ nguyên kernel,
   UUID và các tham số khác**. Đổi từ riêng `ro` thành `rw`, thêm cuối dòng:

```text
init=/bin/bash
```

5. Nhấn `Ctrl+X` hoặc `F10` để boot. Khi có prompt root/bash, chạy phần2.3.

Nếu image chặn sửa GRUB hoặc không ra được shell, giữ nguyên VM và dùng hướng
recovery boot-volume chính thức của Oracle; đừng đoán tên partition hoặc format
ổ đĩa. [Ubuntu recovery](https://wiki.ubuntu.com/Recovery_mode),
[Oracle recovery SSH key](https://blogs.oracle.com/cloud-infrastructure/recovering-opc-user-ssh-key-on-oracle-cloud-infrastructure).

### 2.3. Thêm public key trong shell root của VM

Chạy trên **VM**, không phải PowerShell PC:

```bash
mount -o remount,rw /
install -d -m 700 -o ubuntu -g ubuntu /home/ubuntu/.ssh
```

Nếu file authorized_keys đã có, sao lưu trước:

```bash
if [ -f /home/ubuntu/.ssh/authorized_keys ]; then
  cp -p /home/ubuntu/.ssh/authorized_keys "/home/ubuntu/.ssh/authorized_keys.before-polybot-$(date +%s)"
fi
```

Thay dòng `PASTE_YOUR_PUBLIC_KEY_LINE_HERE` bằng **đúng dòng `.pub` ở bước1**
trước khi chạy block sau. Không dán private key:

```bash
cat >> /home/ubuntu/.ssh/authorized_keys <<'PUBLIC_KEY'
PASTE_YOUR_PUBLIC_KEY_LINE_HERE
PUBLIC_KEY
chown ubuntu:ubuntu /home/ubuntu/.ssh /home/ubuntu/.ssh/authorized_keys
chmod 700 /home/ubuntu/.ssh
chmod 600 /home/ubuntu/.ssh/authorized_keys
sync
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Dòng cuối hiện host fingerprint để đối chiếu khi SSH từ PC. Nếu đang ở shell
recovery `init=/bin/bash`, tiếp tục boot bình thường bằng:

```bash
exec /sbin/init
```

Nếu đã vào bằng phiên sudo bình thường thì không cần chạy `exec /sbin/init`.

## 3. SSH từ PC và dừng bot cũ

Trở lại **PowerShell PC**:

```powershell
$KeyPath = Join-Path $env:USERPROFILE '.ssh\polybot_oracle'
ssh -i "$KeyPath" ubuntu@SERVER_PUBLIC_IP
```

Đối chiếu host fingerprint, chấp nhận host đúng khi được hỏi, nhập passphrase
của SSH key nếu đã đặt. Khi có prompt `ubuntu@...`, các command Bash tiếp theo
chạy trên **server**.

```bash
whoami
cat /etc/os-release
sudo docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
```

Dừng các container bot cũ theo tên đã dùng trước đây, giữ nguyên volume/state:

```bash
for name in polybot-live polybot-live-canary polybot-paper; do
  if sudo docker container inspect "$name" >/dev/null 2>&1; then
    sudo docker update --restart=no "$name"
    sudo docker stop --time 30 "$name"
  fi
done
```

Nếu bot cũ có tên khác, dùng đúng tên thấy trong `docker ps -a` và dừng nó trước
khi chạy TWAP. Không chạy đồng thời hai bot trên cùng ví/state.

## 4. Chuyển bản code mới từ PC lên server

Code thay đổi hiện ở PC, chưa được push GitHub. Vì thế không dùng riêng
`git pull` để lấy bản mới. Mở **một cửa sổ PowerShell PC khác**:

```powershell
$KeyPath = Join-Path $env:USERPROFILE '.ssh\polybot_oracle'
Get-FileHash -Algorithm SHA256 'D:\polybot\data\releases\polybot-twap-live-20261109.tar.gz'
scp -i "$KeyPath" 'D:\polybot\data\releases\polybot-twap-live-20261109.tar.gz' ubuntu@SERVER_PUBLIC_IP:~/
scp -i "$KeyPath" 'D:\polybot\data\releases\polybot-twap-live-20261109.tar.gz.sha256' ubuntu@SERVER_PUBLIC_IP:~/
```

Bundle không chứa data nghiên cứu, `.env` có secrets, SSH key hoặc journal.
Trở lại cửa sổ **SSH server**:

```bash
cd ~
sha256sum -c polybot-twap-live-20261109.tar.gz.sha256
mkdir -p ~/polybot-twap-20261109
tar -xzf ~/polybot-twap-live-20261109.tar.gz -C ~/polybot-twap-20261109
cd ~/polybot-twap-20261109
python3 verify_release.py
bash -n deploy_twap_oracle.sh
```

Hash phải báo `OK`, verifier phải báo đúng strategy `twap60_spot_1400_v1`.
Thư mục code cũ `~/polybot` vẫn được giữ; Docker volume cũ sẽ được tái sử dụng.

## 5. Kiểm tra Docker và đồng hồ server

```bash
sudo docker version
sudo systemctl enable --now docker
sudo timedatectl set-ntp true
timedatectl status
df -h
```

Nếu Docker đã có như lần triển khai trước thì giữ bản cài hiện tại. Nếu lệnh
`docker` không tồn tại, cài theo [Docker Ubuntu](https://docs.docker.com/engine/install/ubuntu/).
Ví dụ cài mới qua repository chính thức, chỉ dùng khi chưa có Docker:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
ARCH=$(dpkg --print-architecture)
CODENAME=${UBUNTU_CODENAME:-$VERSION_CODENAME}
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' "$ARCH" "$CODENAME" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

Không dùng lệnh xóa Docker data, volume hoặc journal trong quá trình cập nhật.

## 6. Build bản TWAP và giữ kết nối ví cũ

```bash
cd ~/polybot-twap-20261109
sudo bash deploy_twap_oracle.sh init
sudo bash deploy_twap_oracle.sh build
sudo bash deploy_twap_oracle.sh public-check
```

`init` tạo `/opt/polybot/live/twap.env` nếu chưa có. `build` ghim SDK
`polymarket-client==0.17.0`. `public-check` không đọc secret và không đặt lệnh;
nó kiểm tra market15m/TWAP60, phí Gamma+CLOB, clock và geography từ chính VM.

Nếu lần trước đã dùng OCI Vault + Instance Principal và tag
`polybot_secret_ocid`, bản mới tiếp tục dùng cấu hình đó. Không cần đưa private
key ví vào repo hoặc dán vào chat. Chạy:

```bash
sudo bash deploy_twap_oracle.sh check
```

Lệnh kiểm tra account và stream trong70s, không gửi BUY/SELL. Kết quả cần có
`order_submitted:false`, đúng wallet, `balance_at_least20:true`, TWAP/spot fresh
và minute-valid, geography cho phép new orders. `opening_seen_during_probe:false`
có thể bình thường nếu probe không đi qua đầu market.

Nếu chưa có Vault hoạt động, dùng file account riêng trên server:

```bash
sudo install -d -m 700 /opt/polybot/secrets
if ! sudo test -f /opt/polybot/secrets/account.env; then
  sudo install -m 600 .env.account.example /opt/polybot/secrets/account.env
fi
sudo nano /opt/polybot/secrets/account.env
```

Điền bốn biến ví/relayer đang dùng ở lần thử trước. Không điền SSH key vào các
biến này. Khi đủ bốn biến, loader dùng chúng và không cần đọc Vault. Nếu muốn
chỉ định Vault OCID riêng, file account có thể chứa `OCI_POLYBOT_SECRET_OCID`.

```bash
sudo chmod 600 /opt/polybot/secrets/account.env
sudo bash deploy_twap_oracle.sh check
```

Nếu file account cũ nằm ở đường dẫn khác, giữ nguyên file đó và truyền:

```bash
sudo env POLYBOT_ACCOUNT_ENV=/opt/polybot/secrets/check.env bash deploy_twap_oracle.sh check
```

Khi `start` cũng truyền cùng `POLYBOT_ACCOUNT_ENV`. Các biến runtime cũ trong
file đó được file `twap.env` mới ghi đè; secrets được giữ nguyên. Bản mới không
dùng calibration/approval của Variant B để tạo xác suất hoặc cho phép giao dịch.

## 7. Chạy live

Kiểm tra các tham số không phải secret:

```bash
sudo grep -E '^POLYMARKET_(EXECUTION_STRATEGY|TWAP_MIN_LEAD_BPS|LIVE_FIXED_STAKE_USD|LIVE_MAX_ORDERS|DAILY_LOSS_STOP|AUTO_REDEEM)=' /opt/polybot/live/twap.env
```

Sau đó:

```bash
sudo bash deploy_twap_oracle.sh start
sudo bash deploy_twap_oracle.sh logs
```

`start` tự phát hiện data volume cũ, dừng container cũ theo tên đã biết, tắt
restart của chúng, sao lưu volume vào `/opt/polybot/backups`, kiểm tra feed/account
70s lần nữa rồi chạy `polybot-twap`. Không xóa journal hoặc reset số lần thử.
Nếu có nhiều volume cũ khác nhau, script in tên và dừng để bạn chọn đúng live
volume, ví dụ:

```bash
sudo env POLYBOT_VOLUME=polybot-live-data bash deploy_twap_oracle.sh start
```

Dùng đúng volume tìm được của container live cũ; không đoán một volume mới để
bỏ qua lịch sử lệnh. Nếu bot cũ dùng bind mount, có thể truyền đúng đường dẫn
data đó thay tên volume.

`Ctrl+C` khi đang xem logs chỉ thoát phần xem logs. Bot vẫn chạy nền và tự
khởi động lại khi VM reboot. Khi khởi động giữa market, bot không tự dựng mốc
đầu từ spot/nến: nó chờ một opening TWAP nhận đúng hạn. Có thể cần gần29 phút
để tới entry của market đầu tiên đủ opening; các bộ lọc/giá/depth có thể khiến
không có giao dịch lâu hơn.

Tín hiệu khóa tại14:00, POST chỉ trong14:00–14:05, ref>=.85/tuổi<=75s,
cap=ref+.01 làm tròn xuống tick và không quá.99. Ref+.01>=1 bị bỏ như nghiên
cứu. Ask/depth là dữ liệu mới, dùng50% depth; nếu không đủ thì bỏ lệnh, không
nới cap để ép khớp. Cần cả TWAP và spot hiện tại tiếp tục qua bộ lọc trước POST.

## 8. Xem trạng thái, dừng và tiếp tục

```bash
cd ~/polybot-twap-20261109
sudo bash deploy_twap_oracle.sh status
sudo docker logs --tail 100 polybot-twap
```

Các status quan trọng:

- `open`: giao dịch được xác nhận, đang chờ kết quả market.
- `resolved`, `won=1/0`: Gamma+CLOB đã đồng ý outcome; không phải tự tính PnL
  bằng giá giữa sổ lệnh. Tiền thực/phí kiểm tra bằng receipt và wallet.
- `rejected`: venue xác nhận không khớp; vẫn tính một lần thử, không gửi lại
  trong cùng market.
- `submitted`, `reserved`, `ambiguous`: chưa đủ bằng chứng kết thúc; bot chặn
  lệnh mới và giữ journal khi restart. Không xóa state để thử lại.
- `aborted_before_submit`: đã giữ một intent nhưng chốt cuối phát hiện giá/tín
  hiệu quá hạn; không POST. Intent vẫn tính vào hạn mức và không thử lại market đó.
- `lifetime_submission_limit`: đạt5 intent/lần thử trong journal mới.
- `daily_loss_stop_utc`: ngừng mua tới ngày UTC tiếp theo, tương ứng07:00 Việt Nam.

Dừng có chủ đích:

```bash
sudo bash deploy_twap_oracle.sh stop
sudo bash deploy_twap_oracle.sh status
```

Đối chiếu lại các lệnh pending và claim vị thế thắng theo cấu hình, không gửi
lệnh mua/bán mới:

```bash
sudo bash deploy_twap_oracle.sh reconcile
```

Nếu POST mất phản hồi mà không có order ID, tự đối chiếu Open orders/Trades/
Positions trên Polymarket. Journal không có nút tự xóa để giả định chưa khớp.
Nếu redeem báo `ambiguous_check_wallet`, kiểm tra/claim trong giao diện ví;
bot không tự lặp lại giao dịch redemption mơ hồ.

Chạy lại sau khi dừng:

```bash
sudo bash deploy_twap_oracle.sh start
```

Nếu muốn nâng tổng số lần thử từ5 lên20, giữ nguyên state và đổi đúng biến:

```bash
sudo bash deploy_twap_oracle.sh stop
sudo sed -i 's/^POLYMARKET_LIVE_MAX_ORDERS=5$/POLYMARKET_LIVE_MAX_ORDERS=20/' /opt/polybot/live/twap.env
sudo bash deploy_twap_oracle.sh start
```

Đây là **20 lần tính cả những lần đã có**, không phải cộng thêm20. Mỗi lần vẫn
$20 mục tiêu, dừng sau thua/ngày vẫn bật. Restart không đặt lại bộ đếm.

## 9. Kiểm tra lỗi thường gặp

- `Permission denied (publickey)`: kiểm tra đúng user `ubuntu`, đúng private
  key tương ứng dòng đã thêm vào authorized_keys; dùng `ssh -vvv -i ...` tại PC.
- `Connection timed out`: kiểm tra VM đang Running và NSG/security list cho
  phép TCP22 từ IP của PC. Lúc tôi kiểm tra, cổng22 hiện đã hoạt động.
- `Could not read polybot_secret_ocid`: kiểm tra tag/Instance Principal/Vault
  của VM hoặc dùng file account riêng ở bước6.
- Geography bị từ chối hoặc không xác minh được: bot không gửi lệnh. Không
  đổi thành spot/nguồn khác hoặc tắt kiểm tra để vượt qua lỗi này.
- `opening_missing...`: để bot chạy qua đầu một market mới.
- `oracle_warmup...`: cần một phút stream mới, không gap/source fallback.
- `spot_not_supporting_twap`: bỏ market theo chính bộ lọc mới.
- `reference_plus_1c_ge_one`, `ask_above_frozen_reference_cap`,
  `insufficient_haircut_depth_inside_cap`: không có giá/khối lượng phù hợp;
  không phải bằng chứng bot hỏng và không có bảo đảm mỗi ngày sẽ khớp lệnh.
- `legacy_attempt_needs_reconciliation`: chờ/đối chiếu lần thử cũ; không bỏ
  qua bằng cách tạo volume trắng.

Không gửi private key, file account.env hoặc toàn bộ `docker inspect` lên chat.
Log/status được thiết kế không in nội dung credential.

## 10. Phần đã kiểm tra và phần cần xác nhận tại VM

Đã kiểm thử offline luồng BUY bằng SDK giả lập, SDK0.17 API contract, trạng thái
crash/restart, data thời gian nhận, source/window, phí/cap, final quote và hạn
mức. Đối chiếu222 cơ hội: không sai lệch rule chọn hướng/lọc; giữ61 ở tuần
hiệu chuẩn và66 ở tuần đánh giá. Đây không xác nhận fill hoặc lợi nhuận live.

Đã đọc market BTC15m hiện tại: source đúng TWAP60, Gamma/CLOB phí khớp, clock
khớp. Kiểm tra geography từ môi trường PC không hoàn tất vì lỗi DNS tới endpoint;
không bỏ qua chốt này. **Geography VM, account, authenticated feeds, build Docker
và lệnh thật cần được xác nhận trên server bằng các command ở trên.** PC chưa
có Docker daemon và chưa có SSH key được VM chấp nhận nên tôi chưa chạy các bước
đó thay bạn.
