# Polybot TWAP Monitor

Dashboard tiếng Việt theo dõi journal và dữ liệu Chainlink của bot đang chạy.
Giao diện hiển thị giờ Việt Nam, tự làm mới sau 10 giây và có nút làm mới ngay.

- Tổng lượt thử, vị thế mở, lệnh cần đối soát và kết quả đã xác nhận từ SQLite.
- Biểu đồ TWAP 60 giây và Spot, mốc opening, đếm ngược tới cửa sổ xét lệnh.
- Bảng lệnh tìm theo ID hoặc market và lọc theo trạng thái.
- Nhật ký sự kiện có bộ lọc cho tín hiệu bỏ qua, giao dịch và lỗi cần chú ý.

Số tiền trong cột Ngân sách là ngân sách của lượt thử. Kết quả thắng/thua lấy
từ journal sau khi market được phân giải. PnL thực cần dữ liệu khớp lệnh và phí.
Biểu đồ hiển thị tối đa 30 phút từ log oracle và lấy một mẫu gần nhất mỗi 5 giây.

## Cài trên VM Oracle

Chạy các lệnh sau trong cửa sổ SSH của VM.

```bash
cd ~/polybot-twap
git pull --ff-only origin codex/twap-railway
sudo bash deploy_twap_dashboard.sh start
sudo bash deploy_twap_dashboard.sh status
```

Script tìm volume `/data` của container `polybot-twap`, gắn vào container
`polybot-twap-dashboard` ở chế độ chỉ đọc và giữ cổng 8787 trên loopback.
Dashboard chạy riêng và chỉ nhận các đường dẫn dữ liệu cùng giới hạn của bot.
Bot có thể tiếp tục hoạt động trong lúc cài dashboard.

## Mở bằng URL trình duyệt với email OTP

Cloudflare Quick Tunnel tạo URL tạm dạng `https://….trycloudflare.com` và gửi
mã OTP tới `cryptq111222333@gmail.com` trước khi cho xem dashboard. Không cần
tên miền hay tài khoản Cloudflare. URL đổi khi tunnel được tạo lại, ví dụ sau
khi khởi động lại container. Cloudflare định vị Quick Tunnel cho thử nghiệm,
không cam kết uptime.

Trong SSH trên VM, cập nhật mã và khởi động tunnel:

```bash
cd ~/polybot-twap
git pull --ff-only origin codex/twap-railway
sudo bash deploy_twap_dashboard.sh start
sudo bash deploy_twap_cloudflare.sh start
```

Lệnh cuối hiển thị URL `trycloudflare.com`. Mở URL đó trong trình duyệt, nhập
`cryptq111222333@gmail.com`, rồi nhập OTP nhận qua email. Container tunnel chạy
ở nền nên có thể đóng SSH sau khi đã lấy URL. Nếu tunnel khởi động lại, lấy URL
mới bằng:

```bash
cd ~/polybot-twap
sudo bash deploy_twap_cloudflare.sh status
sudo bash deploy_twap_cloudflare.sh logs
```

Dừng URL công khai và thu hồi quyền truy cập tunnel:

```bash
sudo bash deploy_twap_cloudflare.sh stop
```

Tunnel chạy container riêng, chỉ kết nối tới dashboard trên loopback, không
publish cổng 8787 ra mạng. Khi tunnel được tạo lại, URL thay đổi. Cloudflare
Quick Tunnel không có bảo đảm uptime và chỉ phù hợp để thử nghiệm/theo dõi cá
nhân. Xem [giới hạn và email OTP của Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

## Mở từ Windows qua SSH

Mở cửa sổ PowerShell mới và chạy lệnh sau.

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:8787:127.0.0.1:8787 -i "$env:USERPROFILE\.ssh\polybot_oracle" ubuntu@IP_VM
```

Giữ cửa sổ PowerShell mở rồi vào [dashboard](http://127.0.0.1:8787) trong
trình duyệt. Thay `IP_VM` bằng public IP của máy Oracle đang chạy bot.
SSH xác thực bằng key của bạn và chuyển tiếp kết nối dashboard.

## Theo dõi và dừng dashboard

Các lệnh quản lý dưới đây chạy trong SSH Ubuntu.

```bash
cd ~/polybot-twap
sudo bash deploy_twap_dashboard.sh status
sudo bash deploy_twap_dashboard.sh logs
sudo bash deploy_twap_dashboard.sh stop
```

Heartbeat cũ hơn 130 giây được đánh dấu cần kiểm tra. Nếu journal tạm thời
không đọc được, giao diện hiển thị cảnh báo và để trống số liệu lệnh. SQLite
đọc WAL trên volume chỉ đọc khi các file `-wal` và `-shm` có sẵn, thường khi bot
đang mở journal. Giá và hoạt động vẫn đọc từ JSONL khi journal chưa sẵn sàng.

Có thể chạy dashboard cục bộ với đường dẫn tới các file dữ liệu đã sao lưu.

```bash
python twap_dashboard.py --db /path/twap_state.sqlite3 --decisions /path/twap_decisions.jsonl --oracle /path/twap_oracle.jsonl
```

Tài liệu tham khảo. [SQLite WAL](https://sqlite.org/wal.html),
[Docker host network](https://docs.docker.com/engine/network/drivers/host/).
