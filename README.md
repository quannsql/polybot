# Bot 2 — nghiên cứu BTC Up/Down 15m

Bot2 nằm tại `D:\polybot`. Dữ liệu và code tham chiếu `D:\backtest` chỉ được đọc.
Runtime hiện là paper/prototype; mặc định không ký hoặc gửi lệnh.

## Deploy Railway từ repository này

Repository chứa cả code bot và bộ kiểm tra; **không có bản live đã hoàn thiện**.
Không thêm key để bật live: executor cũ đang bị khóa có chủ đích.

| Mục đích | Railway variable | Hành vi |
|---|---|---|
| Kiểm tra mạng Amsterdam trước | `RAILWAY_DOCKERFILE_PATH=Dockerfile.preflight` | Public GET một lần, in JSON, không giao dịch |
| Thu thập bot paper sau đó | `RAILWAY_DOCKERFILE_PATH=Dockerfile.bot` | Capture hữu hạn 1 giờ, $30 mỗi kịch bản độc lập, không gửi lệnh |

Cả hai: chọn region phù hợp sau khi xác minh điều kiện sử dụng, một replica,
Restart Policy **Never**, không cần domain/healthcheck hay secrets. Bản preflight
không cần volume. Capture cần lưu/export dữ liệu trước redeploy vì filesystem
container không bền vững; nếu dùng volume, mount dưới `/app` và chỉnh output-dir
tới thư mục con của `/app` (không mount đè toàn bộ `/app`).

Các file kết quả backtest, capture, môi trường Python và secrets không được đưa
lên Git. Script nghiên cứu lịch sử cần dữ liệu local riêng; chúng không tự tái
tạo đầy đủ kết quả trên Railway chỉ từ repository.

## Chuẩn bị thử $30 — chưa bật live

[Hướng dẫn $30, ví Google, API và Railway](TRIAL_30USD_READINESS.md).
Đã chuẩn bị preflight read-only và môi trường `.venv-trial`; đường gửi lệnh
live cũ đã vô hiệu hóa vì thiếu trần giá/đối soát fill. Không chỉ thêm khóa
rồi bật `POLYMARKET_MODE=live`. Bot1 không thay đổi.

```powershell
.\.venv-trial\Scripts\python.exe -B preflight_trial.py
.\.venv-trial\Scripts\python.exe -B collect_advanced_paper.py --duration-seconds 120 --budget-usd 30 --output-dir advanced_paper_capture_30usd
```

## Mới: vào muộn, oracle, edge và order flow

Đọc [báo cáo triển khai và giới hạn](LATE_ENTRY_AND_ADVANCED_PAPER_REPORT_20260913.md).
Đã thử thêm 11m30–14m30 và xây dựng collector/hiệu chuẩn/queue simulation
độc lập. Kết quả win lịch sử gần 99% không phải xác nhận win/PnL thực thi.
Collector hiện cần price-to-beat được xác minh và dữ liệu settlement mới;
thiếu đầu vào thì chỉ ghi public data, không tự tạo xác suất hay gửi lệnh.

```powershell
python -B research_late_entries.py
python -B collect_advanced_paper.py --duration-seconds 120 --output-dir advanced_paper_capture_v3
```

Các lệnh trên hữu hạn và không bật live. Bộ nghiên cứu 33 bộ lọc trước đó
ở [báo cáo tín hiệu bổ sung](SIGNAL_EXTENSIONS_REPORT_20260913.md).

## Outcome và settlement Polymarket thực tế — nghiên cứu mới nhất

[Báo cáo market và entry muộn](ACTUAL_MARKET_RESEARCH_REPORT_20260913.md):
đã kiểm tra 1.598 market bằng Gamma + CLOB. Ứng viên giữ hướng DCA đầu kỳ,
vào sau 10 phút 30 giây, đạt 119/125 outcome thắng ở giai đoạn sau.
**95,20% là kết quả nhãn của entry muộn, chưa phải win-rate/PnL khớp lệnh
thật**; giá tham chiếu sau phí cao và lợi thế mỏng.

```powershell
python -B research_polymarket_actual.py --offline
python -B collect_poly_paper.py --duration-seconds 120
python -B collect_poly_paper.py --settle-only
```

Recorder độc lập ghi orderbook, phí, TWAP và shadow ledger SQLite. Không đọc
private key, không gửi lệnh. Không ảnh hưởng Bot1 hay tự bật live ở runtime.
Lịch sử reference không được coi là ask có thể khớp.

## Nghiên cứu mở rộng khung thời gian

Đọc [báo cáo nhiều khung ngày 13/09/2026](TIMEFRAME_RESEARCH_REPORT_20260913.md).
Đã chạy 95 cấu hình và đối chiếu trực tiếp chu kỳ DCA: cùng 627 entry có
90,75% chu kỳ DCA lãi nhưng chỉ 56,46% đúng hướng sau 15 phút. Không có bằng
chứng đổi khung sẽ chuyển được win-rate >90% sang Polymarket.

```powershell
pip install -r requirements-research.txt
python -B research_timeframes.py
python -B research_dca_cycles.py
```

Đầu ra ở `timeframe_research_20260913`; đây là nghiên cứu nhãn giá thay thế,
chưa phải backtest khớp lệnh Polymarket. Không thay đổi cấu hình runtime.

## Kết quả kiểm tra lại ngày 13/09/2026

Đọc [báo cáo đầy đủ](RESEARCH_REVIEW_20260913.md). Đã tái lập số cũ:
2.450 tín hiệu thô → 1.024 tại biên 15m → 614 training + 410 test →
301 sau lọc ask/edge. Sanity script trước đó có lỗi gán LONG khi chưa đủ SMA25;
lỗi này đã sửa. Các con số 1.113 / 54,99% trong báo cáo cũ đã bị thay thế.

Nghiên cứu mới dùng nến đóng, warmup chung, split theo lịch, calibration cập
nhật hàng tháng từ các nhãn đã hết hạn, kiểm tra gap và bootstrap theo ngày.
Trên bộ 240d, router bật + auxiliary + latest_5m + 24h có 2.668 dự đoán,
1.014 mẫu kiểm tra đạt 56,02% đúng hướng. Nhãn là proxy Lighter; giá ask và
PnL chỉ là kịch bản giả định. Đây chưa phải win-rate/PnL Polymarket thực tế.

## Chạy nghiên cứu

```powershell
cd D:\polybot
pip install -r requirements.txt
python -B audit_poly_research.py --output-dir research_audit_20260913\original_240d
python -B audit_poly_research.py --data-dirs D:\backtest\data_lighter_240d D:\backtest\data_lighter_augall D:\backtest\data_lighter_0903 --output-dir research_audit_20260913\through_sep03
```

Mỗi thư mục kết quả có `summary.json` và `predictions.csv`. JSON ghi manifest,
hash dữ liệu, dữ liệu thiếu, số mẫu qua từng bước, tỷ lệ đúng hướng, đối chứng,
bootstrap theo ngày và kịch bản ask. Dự đoán lưu `signal_at`, `decision_at`,
`end_at`, `fit_at` để kiểm tra thời điểm.

Các chính sách:

- `boundary`: chỉ tín hiệu vừa đóng đúng biên 15m.
- `latest_5m`: lấy tín hiệu gần nhất trong ba lần đóng 5m tới biên; tuổi tối
  đa 10 phút, một dự đoán/hợp đồng.
- `rolling_15m`: chẩn đoán hướng sau 15 phút tính từ mỗi tín hiệu 5m.
  Có cửa sổ chồng lấn, không phải hợp đồng cố định; không tính PnL Poly.

`backtest_polymarket_btc15m.py` giữ vai trò mô phỏng holdout đơn giản, nay dùng
cùng lõi tín hiệu. Mặc định xuất `backtest_results_revised` để giữ kết quả cũ
phục vụ đối chiếu. Script này không phải walk-forward; dùng
`audit_poly_research.py` cho nghiên cứu chính.

## Paper runtime

```powershell
Copy-Item .env.example .env
python run_bot.py --once
python run_bot.py
```

Chỉ copy mẫu nếu chưa có `.env` riêng. Mặc định phiên 08–22 UTC, router và
auxiliary bật, `POLYMARKET_SIGNAL_POLICY=boundary`. Có thể chọn `latest_5m`;
24h dùng giờ bắt đầu/kết thúc cùng bằng 0. Đây là lựa chọn nghiên cứu, chưa
xác nhận trùng cấu hình Bot1 trên server.

Engine dùng lõi `polymarket_bot/signal_grid.py` chung với nghiên cứu. Đợi 20
giây sau biên để nến đóng được công bố, chỉ nhận entry trong 45 giây đầu.
Log nằm tại `logs/decisions.jsonl`; state tại `logs/paper_state.json`.

Thiếu calibration hoặc `approved` chưa true thì chỉ ghi tín hiệu/quyết định.
Không dùng calibration của policy/phiên/nguồn giá khác mà chưa kiểm định lại.
Chưa có paper ledger settlement đầy đủ hoặc đối soát lệnh live hoàn chỉnh.
Live adapter cần kiểm chứng thêm trước triển khai; nghiên cứu không bật live.

## Kiểm thử

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -B -m pytest -q tests
```

Tests đối chiếu trực tiếp các hàm thuần DCA (nếu có source local), tắt ghi
bytecode vào Bot1; kiểm tra tương lai không làm đổi tín hiệu quá khứ, mapping
cửa sổ, thiếu dữ liệu, warmup và tập học chỉ chứa nhãn đã hết hạn.
