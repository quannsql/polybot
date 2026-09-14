# Bot2 — triển khai canary live tối đa $30

Bot1 trong `D:\backtest` không bị sửa hoặc dừng. Bot2 dùng CLOB V2 SDK,
lệnh BUY `FOK`, `max_price`, `max_spend`, journal ghi trước khi gửi và giới
hạn đúng **một lần thử** trong state hiện tại. `FOK` nghĩa là khớp toàn bộ
ngay hoặc hủy; bot không chủ động để phần dư treo trên sổ lệnh.

## Giới hạn phải hiểu trước

- Đây là khả năng thực thi kỹ thuật, không phải chứng nhận chiến lược có lãi.
- Calibration mẫu vẫn `approved=false`; vì vậy bot không đặt lệnh dù đã có
  secret. Chỉ dùng artifact forward-calibration đúng nguồn và đúng policy đã
  được bạn duyệt. Không đổi file mẫu thành `true` để ép bot giao dịch.
- `max_spend=30` dùng fee schedule V2 vừa đọc để giảm notional. SDK ghi rõ phí
  có thể đổi trước execution, nên gọi đây là **trần mục tiêu all-in**, không
  phải bảo đảm kế toán tuyệt đối tới từng micro-dollar.
- Một lần thua có thể mất gần toàn bộ $30. Giá outcome cao làm win-rate cao
  nhưng payout khi thắng nhỏ.
- Geoblock server pass không chứng minh người dùng/tài khoản đủ điều kiện.
  Không dùng VPN, proxy hoặc cloud server để lách hạn chế vị trí.

## Bốn giá trị lấy từ Polymarket

| Biến | Lấy ở đâu | Lưu ý |
|---|---|---|
| `POLYMARKET_WALLET_ADDRESS` | Profile menu → copy wallet address | Đây là account/profile wallet giữ pUSD và position, không phải địa chỉ nạp bridge |
| `POLYMARKET_RELAYER_API_KEY` | Settings → API Keys → Relayer API Keys → Create | Chỉ copy một lần vào secret file |
| `POLYMARKET_RELAYER_API_KEY_ADDRESS` | Cùng màn hình, trường **Signer Address** | Không phải profile wallet; hai địa chỉ có thể khác nhau |
| `POLYMARKET_SIGNER_PRIVATE_KEY` | Private key điều khiển đúng Signer Address ở trên | Không gửi qua chat, email, Git hoặc log |

Với tài khoản Google, loại ví tùy thời điểm tạo: tài khoản mới có thể là
`DEPOSIT_WALLET`, tài khoản Google cũ là `POLY_PROXY`. Chạy checker để SDK
trả loại thực tế rồi đặt `POLYMARKET_EXPECTED_WALLET_TYPE` theo đúng kết quả.

Help Center hiện chỉ mô tả export key Magic.Link cho tài khoản đăng ký bằng
email. Nếu trang export chính thức không cho tài khoản Google xuất đúng key,
không lấy key từ localStorage/extension và không đoán. Hỏi Polymarket Support,
hoặc dùng một tài khoản ví ngoài chuyên biệt chỉ nạp vốn thử. Session Key an
toàn hơn vì không rút được tiền, nhưng hiện beta, chỉ hỗ trợ Deposit Wallet và
cần Builder API key được Polymarket cho phép.

Không cần tự tạo CLOB API key/secret/passphrase: V2 SDK derive L2 credentials
từ signer lúc kết nối. Relayer key là loại khóa khác, dùng cho wallet action
gasless/approval.

## Không có PC/terminal: dùng OCI Vault

Bot hỗ trợ một OCI Vault Secret chứa cả bốn biến tài khoản. Secret không nằm
trong Git, Docker image, instance metadata hoặc lệnh chạy container. VM đọc nó
bằng Instance Principal và chỉ lấy version `CURRENT`.

1. Oracle Console → **Identity & Security → Vault** → Create Vault. Không bật
   “Virtual Private Vault” nếu không thực sự cần HSM dedicated.
2. Trong vault, tạo một symmetric Master Encryption Key.
3. Vào **Secrets → Create Secret**, chọn Manual/plain-text và nhập đúng JSON:

```json
{
  "POLYMARKET_SIGNER_PRIVATE_KEY": "0x...",
  "POLYMARKET_WALLET_ADDRESS": "0x...",
  "POLYMARKET_RELAYER_API_KEY": "...",
  "POLYMARKET_RELAYER_API_KEY_ADDRESS": "0x..."
}
```

Console tự base64 encode. Copy **Secret OCID**, không copy nội dung secret.

4. Copy **Instance OCID** từ trang Compute instance. Tạo Dynamic Group tên
   `polybot-vault-readers` với matching rule chỉ đúng VM này:

```text
ALL {instance.id = 'OCID_CUA_INSTANCE'}
```

5. Tạo IAM Policy trong compartment chứa secret:

```text
Allow dynamic-group polybot-vault-readers to read secret-bundles in compartment TEN_COMPARTMENT
```

6. Compute → Instances → instance `polybot` → tab **Tags** → **Add tags** →
   **Add a free-form tag**, rồi thêm:

```text
Key:   polybot_secret_ocid
Value: ocid1.vaultsecret...
```

`Dockerfile.live` tự đọc tag này qua Instance Principal; không cần đưa bốn secret
vào `docker run`. Nếu không muốn dùng tag, có thể truyền riêng
`OCI_POLYBOT_SECRET_OCID`; OCID là định danh, không phải nội dung bí mật.

Quyền Instance Principal áp dụng cho mọi tiến trình/user có thể chạy trên VM,
vì vậy chỉ cấp `read secret-bundles`, giới hạn Dynamic Group đúng một instance,
và không cài phần mềm không tin cậy trên máy này.

## Xác minh account, tuyệt đối chưa đặt lệnh

Trên Oracle, tạo secret file ngoài repository:

```bash
sudo install -d -m 700 /opt/polybot/secrets
sudo nano /opt/polybot/secrets/check.env
sudo chmod 600 /opt/polybot/secrets/check.env
```

Nội dung tối thiểu:

```dotenv
POLYMARKET_MODE=paper
POLYMARKET_SIGNER_PRIVATE_KEY=0x...
POLYMARKET_WALLET_ADDRESS=0x...
POLYMARKET_RELAYER_API_KEY=...
POLYMARKET_RELAYER_API_KEY_ADDRESS=0x...
POLYMARKET_EXPECTED_WALLET_TYPE=
```

Build và chạy checker:

```bash
cd ~/polybot
git pull
sudo docker build -f Dockerfile.live -t polybot-live .
sudo docker run --rm --env-file /opt/polybot/secrets/check.env polybot-live \
  python -B verify_live_account.py
```

Kết quả phải có `order_submitted: false`, đúng wallet, số dư ít nhất 30 pUSD,
và country/region phù hợp. Sau đó điền wallet type thực tế vào secret file.
Allowance false chưa đặt lệnh; SDK có thể thực hiện approval gasless khi lần
đặt lệnh đầu bị CLOB từ chối vì thiếu allowance.

## Chạy paper lâu dài trên Oracle

Đây là bước nên chạy trước live. Dùng volume riêng để state không mất khi
container restart:

```bash
sudo docker volume create polybot-data
sudo docker run -d --name polybot-paper --restart unless-stopped \
  --env-file /opt/polybot/secrets/check.env \
  -e POLYMARKET_STATE_PATH=/data/paper_state.json \
  -e POLYMARKET_DECISION_LOG=/data/paper_decisions.jsonl \
  -v polybot-data:/data polybot-live
sudo docker logs -f polybot-paper
```

## Arm đúng một canary live

Chỉ thực hiện sau khi có calibration forward `approved=true`, đã tự xác nhận
điều kiện sử dụng, và checker thành công. Copy `.env.live.example` sang
`/opt/polybot/secrets/live.env`, điền secret tại server, rồi:

```bash
sudo chmod 600 /opt/polybot/secrets/live.env
sudo docker rm -f polybot-paper
sudo docker run -d --name polybot-live-canary --restart no \
  --env-file /opt/polybot/secrets/live.env \
  -v polybot-data:/data polybot-live
sudo docker logs -f polybot-live-canary
```

Bot giữ hướng DCA chốt ở đầu window, kiểm tra entry từ T+10:30 tới T+11:30,
yêu cầu ask cùng hướng ít nhất 0.85, spread tối đa 0.03, edge sau phí tối thiểu
0.03 và price cap thấp hơn trong `ask+0.01` hoặc `0.97`.

Sau một intent—kể cả mạng lỗi khiến kết quả mơ hồ—journal chặn lần thứ hai.
Không xóa `/data/live_state.json` để retry trước khi đối chiếu order/position
trên Polymarket. Dừng bot sau lần thử:

```bash
sudo docker stop polybot-live-canary
sudo docker cp polybot-live-canary:/data/live_state.json ./live_state.json
sudo docker cp polybot-live-canary:/data/live_decisions.jsonl ./live_decisions.jsonl
```
