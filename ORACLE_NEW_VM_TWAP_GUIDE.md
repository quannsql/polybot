# Tạo VM Ubuntu mới và triển khai TWAP — 09/11/2026

Hướng dẫn này dùng bản code đã tích hợp trên PC tại `D:\polybot`, chưa push
GitHub. Không dùng riêng `git clone`/`git pull` để lấy bản TWAP này.

Ba nơi thao tác được ghi rõ: **Oracle Console**, **PowerShell PC**, **SSH VM mới**.
Các chữ như `IP_MOI`, `OCID_VM_MOI`, `OCID_SECRET_CU` là chỗ phải thay giá trị thật.
Không dán private key SSH, private key ví hoặc nội dung Vault lên chat.

## 1. Giữ máy cũ và các thông tin cần dùng

Trong Oracle Console, chọn region và compartment đang chứa máy có IP
`SERVER_PUBLIC_IP`. Ghi lại:

- Availability domain (AD), VCN và public subnet.
- OCID và tên boot volume của máy cũ.
- Tags → free-form tag `polybot_secret_ocid`: sao chép giá trị OCID secret.
- Nếu không thấy tag: tìm secret tài khoản bot trong Vault/Secret Management
  và sao chép **Secret OCID**, không phải Vault OCID hay Key OCID. Không sửa
  nội dung secret. Code cần JSON bốn biến tài khoản như bot cũ.
- Compartment chứa secret; có thể khác compartment chứa VM.

Chọn **Stop** máy cũ và chờ **Stopped** để bot cũ không tiếp tục đặt lệnh.
Giữ boot volume, Vault, secret, VCN. Chưa Terminate máy cũ trong luồng chính.
Stop không giải phóng toàn bộ quota provisioned; nếu tạo song song báo quota,
đọc mục 12 trước khi thay đổi máy cũ.

## 2. Tạo SSH key trên PC

Mở **PowerShell PC**, chạy:

```powershell
$KeyDir = Join-Path $env:USERPROFILE '.ssh'
New-Item -ItemType Directory -Path $KeyDir -Force
$KeyPath = Join-Path $KeyDir 'polybot_oracle'
Test-Path -LiteralPath $KeyPath
```

Nếu kết quả `False`, chạy:

```powershell
ssh-keygen -t ed25519 -a 64 -C "polybot-oracle-pc" -f "$KeyPath"
```

Nhập passphrase và nhập lại khi được hỏi. Nếu kết quả `True`, giữ key hiện có;
không ghi đè. Sau đó:

```powershell
$KeyOwner = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
icacls "$KeyPath" /inheritance:r
icacls "$KeyPath" /grant:r "${KeyOwner}:(R)"
Get-Content -LiteralPath "$KeyPath.pub"
```

Sao chép toàn bộ dòng `ssh-ed25519 ...`. File `.pub` là public key để đưa lên
Oracle. File không có `.pub` là private key, cần sao lưu ở nơi riêng có bảo vệ.
Passphrase vừa tạo bảo vệ file key, không phải mật khẩu Ubuntu.

## 3. Tạo VM mới trong Oracle Console

Compute → Instances → **Create instance**. Có thể dùng ô tìm kiếm của Console
nếu vị trí menu thay đổi.

| Mục | Giá trị |
|---|---|
| Name | `polybot-twap-new` |
| Compartment | Cùng compartment máy cũ nếu thuận tiện |
| Availability domain | Cùng AD với boot volume cũ để gắn ổ lấy dữ liệu |
| Image | Canonical Ubuntu 24.04 LTS, bản platform image chuẩn |
| Shape | `VM.Standard.A1.Flex`, ARM; khởi đầu 1 OCPU / 6 GB RAM nếu quota cho phép |
| Network | VCN và **public subnet** cũ đang có internet, nếu phù hợp |
| Public IPv4 | Bật **Assign a public IPv4 address** |
| SSH keys | **Paste public keys**, dán dòng `.pub` ở mục 2 |
| Boot volume | Mặc định khoảng 47–50 GB; tính cả ổ cũ trong tổng storage |
| Metadata endpoint | Cho phép IMDSv2; không cần bật legacy IMDSv1 |

Không chọn lại boot volume cũ làm hệ điều hành của VM mới. Mục tiêu là Ubuntu
mới hoàn toàn; ổ cũ sẽ gắn riêng để đọc dữ liệu.

Kiểm tra nhãn Always Free/ước tính chi phí trên tài khoản trước khi Create.
Tài liệu hiện nêu mức Always Free A1 tương đương tổng 2 OCPU / 12 GB RAM và
200 GB block storage; quota/ưu đãi thực tế cần xem Console, bao gồm máy cũ.
Nếu shape không có capacity, chưa xóa máy cũ để thử vận may.

Sau Create, chờ **Running**, ghi lại **Public IP mới** và **Instance OCID mới**.
IP mới không mặc định là `SERVER_PUBLIC_IP`.

Kiểm tra NSG/security list của subnet có ingress **TCP 22** từ public IP PC
của bạn, source CIDR dạng `YOUR_PUBLIC_IP/32`. Có thể xem public IP PC trong
trình duyệt; đây là địa chỉ mạng internet của PC, không phải `192.168.x.x`.
Bot không cần mở cổng web inbound. Nếu VCN mới: dùng luồng tạo VCN có internet,
public subnet và route `0.0.0.0/0` tới Internet Gateway; egress mặc định phải
cho phép bot gọi HTTPS/WebSocket và các dịch vụ Oracle.

## 4. SSH vào VM mới

Trên **PowerShell PC**, thay IP thật tại dòng đầu:

```powershell
$ServerIp = 'IP_MOI'
$KeyPath = Join-Path $env:USERPROFILE '.ssh\polybot_oracle'
Test-NetConnection -ComputerName $ServerIp -Port 22
ssh -i "$KeyPath" "ubuntu@$ServerIp"
```

Lần đầu SSH hỏi host fingerprint: đối chiếu fingerprint của VM nếu có,
chỉ xác nhận khi đúng máy vừa tạo. Nhập passphrase key nếu được hỏi.
Tài khoản Ubuntu mặc định là `ubuntu`, không phải tài khoản Oracle/email.
Khi thấy `ubuntu@...:~$`, đang ở **SSH VM mới**.

```bash
whoami
uname -m
cat /etc/os-release
sudo -n true
```

Cần thấy `ubuntu`, `aarch64` (với A1), Ubuntu 24.04 và sudo không báo lỗi.
Từ đây các block Bash chạy trên VM; giữ PowerShell PC thứ hai để upload file.

## 5. Cấp quyền VM mới đọc Vault cũ

Vault/secret cũ tiếp tục dùng; quyền Instance Principal của VM cũ không tự
chuyển sang VM mới. SSH key vào Ubuntu độc lập với private key ví trong Vault.

**5.1. Tag VM mới**

Chi tiết VM mới → Tags → Add tags → **Free-form tag**:

```text
Key:   polybot_secret_ocid
Value: OCID_SECRET_CU
```

Giá trị phải bắt đầu tương tự `ocid1.vaultsecret...`; không điền nội dung secret.
Tag chỉ chỉ định secret cần đọc, chưa tự cấp quyền IAM.

**5.2. Dynamic group**

Identity & Security → Domains → chọn domain đang dùng → Dynamic groups.
Giao diện IAM cũ có thể để Dynamic groups trực tiếp trong Identity.
Tạo group `polybot-twap-new-dg`, matching rule:

```text
instance.id = 'OCID_VM_MOI'
```

Thay OCID thật của **VM mới**. Không thay bằng IP hoặc boot-volume OCID.

**5.3. Policy đọc đúng secret**

Identity & Security → Policies → chọn compartment chứa secret, hoặc một
compartment cha có phạm vi bao phủ nó → Create policy. Tên gợi ý
`polybot-twap-new-vault-read`, chọn manual editor.

Nếu group thuộc domain `Default`, statement mẫu:

```text
Allow dynamic-group 'Default'/'polybot-twap-new-dg' to read secret-bundles in compartment id OCID_COMPARTMENT_CHUA_SECRET where target.secret.id = 'OCID_SECRET_CU'
```

Thay đúng domain nếu khác `Default`, compartment OCID và secret OCID.
Với IAM cũ không có identity domain, chủ thể có thể viết
`dynamic-group polybot-twap-new-dg`. Không cấp `manage all-resources`.
Nếu Console báo lỗi cú pháp/chủ thể, lưu lại thông báo để chỉnh đúng IAM của
tài khoản; không mở rộng quyền để bỏ qua lỗi.

IAM có thể cần thời gian lan truyền; Oracle nêu thay đổi matching rules có
thể mất khoảng một giờ. Chỉ tiếp tục live sau khi lệnh `check` thành công.

## 6. Cài Docker và đồng bộ giờ — SSH VM mới

Các lệnh sau dành cho Ubuntu mới, chưa cài Docker:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl python3
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
sudo timedatectl set-ntp true
timedatectl status
sudo docker version
sudo docker run --rm hello-world
df -h
```

Đồng hồ cần được đồng bộ. Không cần cài Python dependencies lên host;
Docker image sẽ cài các thư viện đã ghim phiên bản.

## 7. Upload bản TWAP từ PC và build

Trên **PowerShell PC**, dùng cùng IP mới ở mục 4:

```powershell
$ServerIp = 'IP_MOI'
$KeyPath = Join-Path $env:USERPROFILE '.ssh\polybot_oracle'
Get-FileHash -Algorithm SHA256 -LiteralPath 'D:\polybot\data\releases\polybot-twap-live-20261109.tar.gz'
scp -i "$KeyPath" 'D:\polybot\data\releases\polybot-twap-live-20261109.tar.gz' "ubuntu@${ServerIp}:~/"
scp -i "$KeyPath" 'D:\polybot\data\releases\polybot-twap-live-20261109.tar.gz.sha256' "ubuntu@${ServerIp}:~/"
```

SHA256 đã kiểm tra trên PC:

```text
60fb634db73e44dd0074eea3aa32dd377a1494c8ed8177af370c731cc866e06f
```

Trở lại **SSH VM mới**:

```bash
cd ~
sha256sum -c polybot-twap-live-20261109.tar.gz.sha256
mkdir -p ~/polybot-twap-20261109
tar -xzf ~/polybot-twap-live-20261109.tar.gz -C ~/polybot-twap-20261109
cd ~/polybot-twap-20261109
python3 verify_release.py
bash -n deploy_twap_oracle.sh
sudo bash deploy_twap_oracle.sh init
sudo bash deploy_twap_oracle.sh build
sudo bash deploy_twap_oracle.sh public-check
sudo bash deploy_twap_oracle.sh check
```

Không chạy các bước sau nếu bước trước báo lỗi. Hash phải `OK`, strategy phải
`twap60_spot_1400_v1`. Build có thể mất vài phút. `check` thu stream khoảng 70s.
Các lệnh kiểm tra này không gửi BUY/SELL.

Kết quả cần: `order_submitted: false`, đúng wallet, `balance_at_least20: true`,
`twap_fresh`, `spot_fresh`, hai `minute_valid` đều true, geography có
`new_order_network_check: true`. `opening_seen_during_probe: false` có thể bình
thường nếu probe không đi qua đầu market. Kiểm tra số dư collateral thực từ
account probe; không mặc định mọi loại USD/token trong ví đều khả dụng cho bot.

Geography không đạt hoặc không xác minh được thì dừng triển khai live tại đây.
Không tắt bộ kiểm tra và không dùng proxy để vượt hạn chế của nền tảng.

## 8. Chuyển dữ liệu từ máy cũ mà không cần SSH/password cũ

Code không chứa journal tài khoản. Bot mới mặc định tìm `/data/live_state.json`
và `/data/twap_state.sqlite3`. Phải giữ lịch sử nếu đã có; đừng tạo volume trắng
để bỏ qua lệnh pending hoặc giới hạn lệnh của lần chạy trước.

**8.1. Gắn ổ cũ — Oracle Console**

1. Xác nhận VM cũ **Stopped**. Từ chi tiết máy cũ → Boot volume → Detach.
2. Trên VM mới → Attached block volumes → Attach block volume. Chọn boot
   volume cũ như **data volume**, đúng tên/OCID đã ghi. Nếu trình chọn mặc định
   chỉ hiện block volumes, tìm tùy chọn chọn boot volume hoặc nhập volume OCID.
3. Chọn **Read-only**, attachment **Paravirtualized** nếu được hỗ trợ. Không
   dùng Replace boot volume cho VM mới, không format ổ.
4. Nếu chỉ có iSCSI, dùng đúng các lệnh **iSCSI commands → Connect** do Oracle
   sinh cho attachment đó trên VM mới. Không đoán IP/target iSCSI.

**8.2. Xác định phân vùng và mount chỉ đọc — SSH VM mới**

```bash
lsblk -o NAME,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINTS
findmnt /
```

Phân vùng đang mount `/` thuộc máy mới, không chọn nó. Trên ổ cũ, root thường
là phân vùng số 1, ext4; phân vùng số 16 là `/boot` đã thấy ở GRUB. Nhưng phải
xác nhận thiết bị từ `lsblk`/attachment; tên có thể khác `/dev/sdb`.

Thay `THIET_BI_ROOT_CU` bằng partition thật, ví dụ `/dev/sdb1` **chỉ nếu đúng**:

```bash
OldRoot='THIET_BI_ROOT_CU'
test -b "$OldRoot"
sudo mkdir -p /mnt/polybot-old
sudo mount -t ext4 -o ro,noload "$OldRoot" /mnt/polybot-old
sudo test -d /mnt/polybot-old/etc
sudo test -d /mnt/polybot-old/home/ubuntu
```

Nếu không xác định được thiết bị, filesystem không phải ext4, hoặc mount báo
lỗi, dừng phần này và gửi `lsblk`/lỗi. Các bước tạo VM, Vault và build vẫn đã
hoàn thành; chưa cho bot đặt lệnh khi chưa đối chiếu dữ liệu cũ.

**8.3. Xác định data mount của container cũ, không in secrets**

Đoạn Python chỉ in tên container và mount `/data`, không in Env/private key:

```bash
sudo python3 - <<'PY'
import json
from pathlib import Path
base = Path('/mnt/polybot-old/var/lib/docker/containers')
found = False
for p in sorted(base.glob('*/config.v2.json')):
    try:
        obj = json.loads(p.read_text())
    except (OSError, ValueError):
        continue
    name = obj.get('Name', '').lstrip('/')
    if 'polybot' not in name.lower():
        continue
    mounts = obj.get('MountPoints', {})
    for key, m in mounts.items():
        if key == '/data' or m.get('Destination') == '/data':
            found = True
            print(json.dumps({'container': name, 'type': m.get('Type'),
                'volume': m.get('Name'), 'source': m.get('Source')}, ensure_ascii=False))
if not found:
    print('NO_POLYBOT_DATA_MOUNT_FOUND: inspect old deployment; do not assume empty history')
PY
```

Chọn data của container live (`polybot-live`, `polybot-live-canary`, hoặc
`polybot-twap`), không chọn paper nếu có live. Nếu các live container dùng data
khác nhau, cần đối chiếu thời điểm/lần triển khai trước khi chọn. Docker data
root tùy chỉnh/rootless hoặc bot chạy trực tiếp bằng systemd có thể không nằm
ở đường dẫn trên; khi đó gửi kết quả metadata an toàn để xác định tiếp.

Ví dụ output source là `/var/lib/docker/volumes/polybot-live-data/_data`, thì
đường dẫn đọc trên VM mới là:

```bash
OldData='/mnt/polybot-old/var/lib/docker/volumes/polybot-live-data/_data'
sudo test -d "$OldData"
sudo ls -lah "$OldData"
```

Thay đúng đường dẫn theo source thật. Nếu source là bind mount `/home/ubuntu/...`,
cũng thêm tiền tố `/mnt/polybot-old` vào source đó. Không in nội dung `.env`.
Nếu dữ liệu nằm trên block volume khác, phải gắn volume đó; không kết luận
không có lịch sử chỉ vì boot volume không chứa file.

**8.4. Sao chép toàn bộ data vào volume mới khi bot chưa chạy**

```bash
sudo docker volume create polybot-live-data
sudo docker run --rm \
  --mount "type=bind,source=$OldData,target=/old,readonly" \
  --mount type=volume,source=polybot-live-data,target=/data \
  polybot-twap:20261109 sh -c 'test -z "$(ls -A /data)" && cp -a /old/. /data/'
```

Lệnh cố ý không ghi đè nếu volume đích đã có dữ liệu. Nếu báo lỗi vì volume
không trống, không xóa volume; kiểm tra xem đã chuyển xong hay đang có journal.
Sao chép cả SQLite WAL/SHM và các file lock nếu có, không chỉ copy một file db.

```bash
cd ~/polybot-twap-20261109
sudo bash deploy_twap_oracle.sh backup
sudo bash deploy_twap_oracle.sh reconcile
sudo bash deploy_twap_oracle.sh status
```

`reconcile` không gửi BUY/SELL; có thể claim/redeem vị thế thắng theo cấu hình.
Mở Polymarket bằng đúng ví, đối chiếu **Open orders**, **Trades/Activity** và
**Positions**. Hủy các lệnh cũ còn treo mà bạn không muốn tiếp tục; kiểm tra
receipt của lệnh có trạng thái chưa rõ. Không xóa journal để vượt `ambiguous`.

Nếu bot trước chưa từng đặt lệnh và thực sự không có dữ liệu để chuyển, chỉ
dùng volume mới sau khi đã xác nhận không có lệnh/vị thế bot cũ chưa xử lý trên
đúng ví. Đây là trường hợp bắt đầu journal mới, không phải cách xử lý lỗi state.

Sau khi copy/backup xong:

```bash
sudo umount /mnt/polybot-old
```

Oracle Console → detach **data attachment ổ cũ trên VM mới**, giữ volume.
Không mount vĩnh viễn ổ cũ và không thêm nó vào `/etc/fstab`.

## 9. Kiểm tra cấu hình và chạy live

Trên SSH VM mới:

```bash
cd ~/polybot-twap-20261109
sudo grep -E '^POLYMARKET_(MODE|DRY_RUN|EXECUTION_STRATEGY|LIVE_FIXED_STAKE_USD|MAX_STAKE_USD|LIVE_MAX_ORDERS|DAILY_LOSS_STOP|AUTO_REDEEM)=' /opt/polybot/live/twap.env
sudo bash deploy_twap_oracle.sh check
```

Cấu hình mặc định: live, $20 mục tiêu gồm phí mỗi lệnh, tối đa 5 intent/lần
thử trong journal, giữ một vị thế chưa xác nhận kết quả, dừng mua sau một lệnh
thua đã xác nhận trong ngày UTC, auto-redeem bật. Một intent bị hủy trước POST
cũng có thể chiếm một slot; restart không reset bộ đếm. Giới hạn 5 không phải
là bảo đảm lỗ tối đa $20; daily stop dựa trên kết quả đã biết.

Nếu đúng ví, dữ liệu cũ đã đối chiếu, máy cũ vẫn Stopped và check thành công:

```bash
sudo bash deploy_twap_oracle.sh start
sudo bash deploy_twap_oracle.sh logs
```

**`start` là bước bật giao dịch bằng tiền thật.** Nó backup data, check feed/
account 70s rồi chạy container `polybot-twap` nền và tự restart khi VM reboot.
Không cần để PC bật. Ctrl+C ở `logs` chỉ thoát xem log, bot vẫn chạy.

Bot dùng BTC15m, khóa tín hiệu ở 14:00 của market, TWAP60 dẫn tối thiểu 5 bp,
spot Chainlink củng cố TWAP; chỉ POST đến 14:05. Kiểm tra quote/depth/fee trước
gửi FOK, không ép khớp. Giữ tới settlement; chưa có SELL/cắt lỗ tự động.
Khởi động giữa market có thể chờ gần 29 phút để đến entry đầu có opening hợp lệ;
các bộ lọc có thể làm bot không giao dịch lâu hơn. Không có bảo đảm thắng 100%.

## 10. Vận hành, dừng và sao lưu

Xem trạng thái:

```bash
cd ~/polybot-twap-20261109
sudo bash deploy_twap_oracle.sh status
sudo docker logs --tail 100 polybot-twap
```

Dừng đặt lệnh mới:

```bash
sudo bash deploy_twap_oracle.sh stop
sudo bash deploy_twap_oracle.sh status
```

Dừng container không hủy lệnh đã gửi và không bán vị thế đã khớp. FOK đã khớp
không thể hủy phần khớp; kiểm tra tài khoản Polymarket khi cần xử lý vị thế.

Đối chiếu và backup sau khi dừng:

```bash
sudo bash deploy_twap_oracle.sh reconcile
sudo bash deploy_twap_oracle.sh backup
```

Chạy tiếp với cùng journal:

```bash
sudo bash deploy_twap_oracle.sh start
```

Nếu sau khi kiểm tra thử muốn tăng hạn mức từ 5 lên tổng 20 intent:

```bash
sudo bash deploy_twap_oracle.sh stop
sudo sed -i 's/^POLYMARKET_LIVE_MAX_ORDERS=5$/POLYMARKET_LIVE_MAX_ORDERS=20/' /opt/polybot/live/twap.env
sudo bash deploy_twap_oracle.sh start
```

Là tổng 20 tính cả lần cũ, không cộng thêm 20; $20/lệnh và daily stop vẫn giữ.
Không chạy `docker volume rm`, không xóa SQLite hay file legacy lock để reset.
Chưa Terminate máy cũ cho đến khi xác nhận backup và hoạt động máy mới.

## 11. Lỗi thường gặp

| Lỗi | Cách kiểm tra |
|---|---|
| SSH timeout | IP mới, VM Running, public subnet, public IPv4, route internet, TCP22 từ IP PC |
| Permission denied (publickey) | User `ubuntu`, đúng file key đã đưa `.pub` lúc tạo VM; thử `ssh -vvv -i ...` trên PC |
| Could not read polybot_secret_ocid | Free-form tag của VM mới đúng Secret OCID; không dùng defined tag cho loader này |
| Vault 403/404/NotAuthorizedOrNotFound | Group khớp OCID VM mới, đúng domain, policy read secret-bundles, đúng compartment/secret và thời gian lan truyền |
| Balance dưới20 | Kiểm tra đúng ví và collateral bot hỗ trợ; không sửa probe để bỏ qua |
| Chainlink feed không fresh | Kiểm tra kết nối/stream; để kiểm tra lại, không thay nguồn settlement bằng spot khác |
| Geography fail/unavailable | Dừng live; không tắt kiểm tra |
| opening_missing, oracle_warmup | Chờ opening mới/một phút dữ liệu liên tục |
| spot_not_supporting_twap | Bộ lọc chủ động bỏ market |
| ask_above_frozen_reference_cap, insufficient depth | Giá/khối lượng không phù hợp, không tăng cap để ép mua |
| pending/ambiguous/legacy_attempt_needs_reconciliation | Giữ state, đối chiếu receipt/Polymarket và reconcile khi dừng |
| lifetime_submission_limit | Đã đủ số intent trong journal; chỉ tăng giới hạn có chủ đích, không reset state |

Nếu cần hỗ trợ, gửi bước đang làm, thông báo lỗi và output đã che thông tin
nhạy cảm. Không gửi toàn bộ `docker inspect` vì có thể lộ env tài khoản.

## 12. Khi không đủ quota để tạo song song

Stop VM không nhất thiết giải phóng quota shape/storage. Đầu tiên kiểm tra
Limits/Quotas/Usage và tổng tài nguyên, kể cả boot volume được giữ.
Không nâng cấp sang cấu hình tính phí nếu chưa xem chi phí.

Nếu bắt buộc Terminate VM cũ để giải phóng quota, thao tác đó mất instance/IP
ephemeral và không bảo đảm lấy lại capacity ARM. Trước đó ghi đủ thông tin ở
mục 1, giữ Vault/secret, tạo backup boot volume nếu quota cho phép và xem chi
phí backup. Khi Terminate, **bỏ chọn Permanently delete the attached boot volume**
và không xóa các data volumes. Sau đó tạo VM mới cùng AD với ổ cũ và làm phần
chuyển dữ liệu. Đây là nhánh thay thế, không phải bước bắt buộc của luồng chính.

## 13. Kiểm chứng và tài liệu nguồn

Đã kiểm tra checksum archive ở PC; gói chưa được triển khai lên VM mới.
Kiểm thử mã trước đó: 223 passed, 14 skipped; parity tín hiệu 222 trường hợp
không lệch. Chưa xác nhận build Docker ARM, quyền Vault, stream tài khoản và
khớp lệnh thật trên VM mới; các lệnh check/start ở trên kiểm chứng theo từng bước.
Backtest giả định không phải PnL live hoặc cam kết win rate.

- [Oracle: tạo instance](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/launchinginstance.htm)
- [Oracle: Always Free và thiếu capacity](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [Oracle: SSH Linux](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/connect-to-linux-instance.htm)
- [Oracle: Instance Principals](https://docs.oracle.com/en-us/iaas/Content/Identity/Tasks/callingservicesfrominstances.htm)
- [Oracle: dynamic group matching rules](https://docs.oracle.com/en-us/iaas/Content/Identity/dynamicgroups/Writing_Matching_Rules_to_Define_Dynamic_Groups.htm)
- [Oracle: Vault permissions](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/keypolicyreference.htm)
- [Oracle: quy trình recovery boot volume](https://blogs.oracle.com/cloud-infrastructure/recovering-opc-user-ssh-key-on-oracle-cloud-infrastructure)
- [Oracle: gắn block volume](https://docs.oracle.com/en-us/iaas/Content/Block/Tasks/attach-compute-volume-attachment.htm)
- [Oracle: terminate instance](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/terminatinginstance.htm)
- [Docker: cài chính thức trên Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
