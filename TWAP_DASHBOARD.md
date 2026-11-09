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

## Mở từ Windows

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
