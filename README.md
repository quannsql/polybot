# BTC15m live — Chainlink TWAP60 + spot

Runtime mới thay thế luồng Bollinger/Variant B tại `run_bot.py` và script deploy.
Tín hiệu khóa ở phút14:00: TWAP dẫn mốc đầu>=0,05%; Up cần spot>=TWAP, Down cần
spot<=TWAP. Cả hai giá từ Chainlink; không dùng nến Lighter/Binance để chọn hướng.

[Hướng dẫn Oracle Cloud từng command](ORACLE_TWAP_LIVE_GUIDE.md), đã điền server
Ubuntu `SERVER_PUBLIC_IP`, gồm tạo SSH key mới, thêm key vào VM cũ, SCP release,
build/check/start và quản lý state của lần chạy trước.

[Chi tiết tích hợp và kiểm chứng](TWAP_LIVE_INTEGRATION.md).

[Dashboard TWAP trên Oracle](TWAP_DASHBOARD.md) hiển thị biểu đồ Chainlink,
trạng thái bot, lịch sử lệnh và nhật ký quyết định qua SSH.

## Railway từ GitHub

[Hướng dẫn Railway và Variables](RAILWAY_DEPLOY.md). Dockerfile ở root tự chạy
worker Railway, mặc định `probe` chỉ kiểm tra public API, không cần key ví.
Sau đó dùng `check` để xác minh account/feed, rồi `run` với mode paper/live.
Cần persistent volume `/data` khi chạy bot. Secret chỉ nhập trong dashboard.
Hà Lan được phân loại frontend-only theo tài liệu API ngày09/11/2026;
endpoint thực tế vẫn phải trả `blocked=false`, eligibility tài khoản kiểm tra riêng.

- Mục tiêu$20/lệnh gồm fee metadata; SDK để dư1cent, FOK và cap giá.
- Tối đa5 intent/lần gửi mặc định trong journal mới; một lần/market.
- Dừng entry sau một outcome thua đã biết trong ngày UTC; giữ tới settlement.
- Opening phải được nhận đúng hạn; missing/stale/gap/source khác đều bỏ qua.
- Ref>=.85, tuổi<=75s, cap ref+.01<1, tick-round-down, trần.99. Book thật quyết
  định ask/depth; không gọi reference là giá đã khớp.
- Journal SQLite bền vững, process lock, import state legacy; không reset khi restart.
- Claim vị thế mới thắng nếu cấu hình cho phép; không có stop-loss SELL tự động.

Mặc định chạy paper; live cần đúng cấu hình và account secrets. User đã yêu cầu
thử live; không dùng approval/calibration cũ để gán xác suất cho chiến lược mới.
Win66/66 trong nghiên cứu là post-hoc, không bảo đảm lợi nhuận hoặc tỷ lệ live.

## Oracle deployment

Sau khi vào đúng thư mục release trên VM:

```bash
python3 verify_release.py
sudo bash deploy_twap_oracle.sh init
sudo bash deploy_twap_oracle.sh build
sudo bash deploy_twap_oracle.sh public-check
sudo bash deploy_twap_oracle.sh check
sudo bash deploy_twap_oracle.sh start
sudo bash deploy_twap_oracle.sh logs
```

`check` không đặt BUY/SELL; `start` sẽ chạy live theo runtime env. SDK dùng
PolyBolt có xác thực; cần ví/key ở Oracle Vault cũ hoặc file account ngoài repo.
Chạy theo guide để giữ đúng data volume cũ và dừng container cũ trước khi thay.

## Nghiên cứu được giữ lại

- [Phân tích3 lệnh thua và bán sớm](TWAP_LOSS_ANALYSIS_20261108.md).
- [14 ngày TWAP, tuần hiệu chuẩn/đánh giá](TWAP_STABILITY_REPORT_20261108.md).
- [TWAP so với complete-set](STRATEGY_COMPARISON_20261108.md).
- [Mua muộn và lợi nhuận nhỏ](HIGH_CONFIDENCE_RESEARCH_20261108.md).
- [Hướng dẫn data/backtest](RESEARCH_DATA_GUIDE.md).
- [Đợt tải dữ liệu mới](FRESH_BACKTEST_REPORT_20261108.md).
- [README commit gốc](README_LEGACY_46fdc6f.md).

Các module/approval/báo cáo Variant B được giữ để đối chiếu lịch sử. Chúng không
điều khiển runtime mới. `LIVE_TRIAL_GUIDE.md` là tài liệu triển khai cũ.

## Kiểm thử và đóng gói tại PC

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv-research\Scripts\python.exe -B -m pytest -q --basetemp='D:\polybot\data\pytest_manual_new_run'
.\.venv-research\Scripts\python.exe -B audit_twap_runtime_parity.py
.\.venv-research\Scripts\python.exe -B make_twap_release.py
```

Dùng một basetemp mới, vì pytest xóa nội dung basetemp khi chạy. Release nằm
trong `data/releases`, được tạo từ allowlist, kèm SHA256 và manifest từng file.
Gói này bao gồm cả code local chưa push; không gồm secret, key, data hoặc journal.
