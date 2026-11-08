# TWAP trên Railway từ GitHub

Code dùng `Dockerfile` ở root. Oracle tiếp tục dùng `Dockerfile.live` riêng.
Không cần chạy Docker bên trong Railway, không dùng script deploy Oracle.
Không cần SSH key Ubuntu. Key ví chỉ thêm tại Variables của service Railway.

## 1. Deploy lần đầu để kiểm tra Amsterdam, chưa cần key ví

1. Railway → New Project → Deploy from GitHub repo → `quannsql/polybot`.
2. Chọn branch chứa thay đổi Railway được thông báo trong chat. Nếu Railway
   tự deploy branch mặc định `main`, đổi Source → Branch trước khi triển khai tiếp.
3. Root directory `/`; dùng Dockerfile root, không dùng Railpack hoặc Dockerfile.bot.
   Xóa Start Command cũ nếu có để Railway dùng CMD của Dockerfile.
4. Region: **EU West / Amsterdam**, ID `europe-west4-drams3a`.
5. Replicas: **1**. Tắt Serverless/App Sleeping. Không đặt Cron Schedule.
6. Không tạo public domain/port hoặc HTTP healthcheck: đây là background worker.
7. Restart Policy: **On Failure**, tối đa3 retries trong đợt kiểm tra.
8. Variables → Raw Editor: dán phần không secret từ `.env.railway.example`.
   Giai đoạn này chỉ cần `POLYMARKET_RAILWAY_ACTION=probe`; đó cũng là mặc định.
9. Deploy staged changes; đọc Deploy Logs.

`probe` chạy public market/fee/clock/geography checks, không đọc key và không
gửi BUY/SELL. Thành công sẽ in `order_submitted: false`, geography có
`country: NL`, `new_order_network_check: true`. Chương trình thoát sau kiểm tra;
trạng thái Completed/Stopped sau exit0 là bình thường, chưa phải bot chạy nền.

Nếu `blocked=true`, không có phản hồi hợp lệ, hoặc lỗi network: không bật live.
IP egress thực tế có thể khác suy đoán từ tên region, nên cần kết quả từ container.
Chưa tạo deployment Railway từ môi trường phát triển; kiểm tra này phải chạy
trong service của bạn.

## 2. Quy định địa lý đã áp dụng

[Tài liệu API Polymarket](https://docs.polymarket.com/api-reference/geoblock),
đọc ngày09/11/2026, phân biệt frontend-only với frontend+API. Hà Lan nằm trong
nhóm frontend-only. Code bỏ việc chặn NL chỉ dựa trên tên quốc gia, đồng thời
vẫn yêu cầu endpoint chính thức `https://polymarket.com/api/geoblock` trả rõ
`blocked=false`. Mỹ/Singapore và các quốc gia cấm API vẫn chặn, kể cả endpoint
trả false; phản hồi thiếu/sai định dạng không được dùng để cho phép giao dịch.

Trang Help Center có mô tả rộng hơn; eligibility của người dùng/tài khoản và
điều khoản vẫn áp dụng. IP hợp lệ không phải xác nhận pháp lý hoặc tài khoản.
Không có proxy, country spoofing hoặc tùy chọn tắt kiểm tra địa lý trong bản này.

## 3. Thêm key ở Variables và kiểm tra account/feed

Trong Variables → New Variable, thêm đúng bốn giá trị thật đang dùng cho ví bot:

| Variable | Nội dung |
|---|---|
| `POLYMARKET_SIGNER_PRIVATE_KEY` | Private key ví signer, không phải SSH key |
| `POLYMARKET_WALLET_ADDRESS` | Địa chỉ ví Polymarket/funder đúng tài khoản |
| `POLYMARKET_RELAYER_API_KEY` | Relayer API key đang dùng |
| `POLYMARKET_RELAYER_API_KEY_ADDRESS` | Địa chỉ gắn với relayer API key |

Không đưa key vào file trong repo, Build Command, Start Command hay log.
Không cần `.env` trên Railway. Variables được cấp trực tiếp cho process.
Không thêm `OCI_POLYBOT_SECRET_OCID`; Railway không có OCI Instance Principal.
Launcher tắt việc tìm key từ OCI instance metadata khi dùng check/run.

Đặt các biến:

```dotenv
POLYMARKET_RAILWAY_ACTION=check
POLYMARKET_MODE=paper
POLYMARKET_DRY_RUN=1
OCI_POLYBOT_USE_INSTANCE_METADATA=0
```

Deploy staged changes. Kiểm tra khoảng70s rồi thoát, không gửi BUY/SELL, không
thay trading approvals. Cần đúng wallet, đủ collateral dự kiến, TWAP/spot fresh
và minute-valid. `opening_seen_during_probe=false` bình thường nếu probe không
đi qua đầu market. Chạy thêm check ở mode live khi đã điền đủ các biến live
nếu muốn xác nhận ràng buộc balance>=20 trước khi run.

## 4. Tạo volume và chạy paper

Trên canvas/service, Add Volume → gắn vào service tại **`/data`**. Railway tự
cấp `RAILWAY_VOLUME_MOUNT_PATH`; không tự điền biến này để giả lập volume.
Chọn dung lượng phù hợp log (khuyến nghị ít nhất2GB, tính phí theo plan).
Launcher yêu cầu `/data` thực sự là mount point trước khi chạy bot.

Chuyển:

```dotenv
POLYMARKET_RAILWAY_ACTION=run
POLYMARKET_MODE=paper
POLYMARKET_DRY_RUN=1
```

Deploy và xem Deploy Logs. Paper vẫn cần bốn key để subscribe Chainlink feeds,
nhưng không đặt BUY/SELL. Journal paper mặc định `/data/twap_paper.sqlite3`,
tách khỏi live `/data/twap_state.sqlite3`. Không điền chung state path cho hai mode.

Khi chạy run, chỉnh Restart Policy **Always** nếu plan hỗ trợ; nếu dùng On Failure,
kiểm tra số retries/alert vì hết lượt sẽ không tự phục hồi. Volume và journal
vẫn giữ khi restart/redeploy. Chỉ một service/replica được phép dùng ví này để
giao dịch. Redeploy có thể gián đoạn stream và bot phải chờ warmup/opening mới.

## 5. Dữ liệu cũ và chuyển live

Dừng VM/bot Oracle trước khi bật live trên Railway. Giữ boot volume/dữ liệu cũ.
Nếu có journal live, chuyển toàn bộ data khi cả hai bot đều dừng, gồm SQLite,
WAL/SHM, JSON legacy và lock. Dùng Railway CLI SSH/SFTP hoặc volume file tools
để đưa vào volume `/data`, không vào `/app` hay filesystem tạm.

Giữ đúng tên `/data/twap_state.sqlite3`, `/data/live_state.json` và các file liên
quan. Dữ liệu đã nằm trong thư mục con có thể đặt các Variables PATH tương ứng,
nhưng tất cả phải ở trong `/data`. Không đổi state path để bỏ pending/ambiguous
hoặc reset hạn mức. Nếu chưa lấy được journal cũ, đối chiếu đầy đủ Open orders,
Trades và Positions; không coi volume trống là bằng chứng không có lệnh cũ.

Trong shell **của deployment** (Railway CLI `railway ssh` sau khi link đúng
project/service/environment; `railway run` chạy trên PC, không kiểm tra IP Railway):

```bash
python -B manage_twap.py status --state /data/twap_state.sqlite3
```

Khi cần reconcile, dừng worker giao dịch, dùng deployment có Start Command tạm
`python -B manage_twap.py reconcile`, cùng Variables live và cùng volume. Lệnh
không BUY/SELL nhưng có thể redeem theo cấu hình. Không chạy song song với worker.
Khôi phục Start Command mặc định sau khi xong.

Sau khi account/network/feed và trạng thái cũ đã được xác minh, thay Variables:

```dotenv
POLYMARKET_RAILWAY_ACTION=run
POLYMARKET_MODE=live
POLYMARKET_DRY_RUN=0
POLYMARKET_LIVE_CONFIRM=I_UNDERSTAND_TWAP_20_USD_LIVE_TEST
POLYMARKET_ACCOUNT_ELIGIBILITY_CONFIRMED=1
POLYMARKET_LIVE_FIXED_STAKE_USD=20
POLYMARKET_MAX_STAKE_USD=20
POLYMARKET_BANKROLL_USD=50
POLYMARKET_LIVE_MAX_ORDERS=5
POLYMARKET_DAILY_LOSS_STOP=1
POLYMARKET_AUTO_REDEEM=1
```

Review/deploy Variables là bước bật **tiền thật**. Đừng bật auto-deploy các
branch khác hoặc preview environments có cùng credentials live.

Live kiểm tra network/balance, chuẩn bị trading approvals nếu cần, rồi thu feeds.
$20 mục tiêu gồm fee, FOK, tối đa5 intent/lần thử trong journal, một vị thế chưa
xác nhận kết quả; daily stop theo ngày UTC. Không bảo đảm $20 là lỗ tối đa của
cả đợt. Giữ tới settlement, chưa có SELL tự cắt lỗ. Auto-redeem có thể gửi giao
dịch claim. $50 trong cấu hình không tự chuyển/nạp tiền; cần collateral khả dụng.

Bot BTC15m khóa tín hiệu Chainlink TWAP60+spot lúc14:00 và chỉ POST tới14:05.
Missing opening có thể chờ gần29 phút tới entry đầu; lọc giá/depth có thể chờ
lâu hơn. Không có bảo đảm win100% hoặc lời theo backtest.

## 6. Trạng thái và dừng

Trong deployment shell, journal live:

```bash
python -B manage_twap.py status --state /data/twap_state.sqlite3
```

Logs giao dịch `/data/twap_live_decisions.jsonl`, oracle
`/data/twap_live_oracle.jsonl`; paper dùng tên có `paper`. Log xoay vòng, vẫn
cần theo dõi dung lượng volume và thiết lập backups trên Railway.

Để dừng giao dịch mới: dùng Stop/Remove deployment đang chạy trên dashboard;
hoặc đổi ACTION sang `probe` và deploy. Việc dừng container không hủy lệnh đã
khớp/đã gửi, không bán vị thế; kiểm tra tài khoản Polymarket riêng.

Giữ volume khi cập nhật; không xóa journal để chạy lại. Nếu có process-lock
conflict, xác nhận worker cũ đã dừng thay vì xóa lock. Không scale lên nhiều
replica để tăng số lệnh. Không chạy đồng thời Oracle và Railway trên cùng ví.

## 7. Nguồn cấu hình Railway

- [Dockerfile và start command](https://docs.railway.com/builds/build-and-start-commands)
- [Variables](https://docs.railway.com/variables)
- [Regions](https://docs.railway.com/deployments/regions)
- [Volumes và mount lúc start, không phải build/pre-deploy](https://docs.railway.com/volumes)
- [Volume persistence/replicas/backups](https://docs.railway.com/volumes/reference)

Sử dụng Dockerfile auto-detect và dashboard, không phụ thuộc `railway.json`
legacy đang được Railway chuyển sang IaC. Chưa kiểm chứng Docker build và
network/account trên service của bạn; probe/check là các bước xác minh thực tế.
