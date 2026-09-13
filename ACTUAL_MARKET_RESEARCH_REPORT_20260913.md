# Bot2 — outcome, phí, settlement và entry muộn

Ngày 13/09/2026. Tất cả thay đổi trong `D:\polybot`; không sửa, dừng hay
chuyển Bot1 ở `D:\backtest`. Không đặt lệnh thật.

## Kết luận

Đã tìm được ứng viên **trên 90% outcome thắng trong nghiên cứu lịch sử dùng
settlement Polymarket**. Không phải chỉ đổi khung Bollinger: giữ hướng DCA
được xác định đầu kỳ, chờ đến phút 10:30, chỉ vào khi giá outcome cùng hướng
đủ cao. Hợp đồng vẫn hết hạn ở phút 15:00 — chỉ còn **4 phút 30 giây** từ
lúc mua, không phải dự đoán trọn 15 phút tiếp theo từ lúc mua.

Ứng viên nghiêm ngặt nhất đạt **119/125 = 95,20%** ở giai đoạn sau. Tuy nhiên,
giá vào giả định sau phí trung bình gần **94,18 cent/share**. Đây chưa phải
win-rate/PnL bot đã khớp lệnh. Lịch sử token là giá tham chiếu, không phải ask
có độ sâu chứng minh mua được. Kết quả đáng để chạy prospective paper,
chưa đủ để cấp vốn hoặc hứa hiệu quả ổn định.

## 1. Dữ liệu thực tế đã thu

Hai cấu hình hướng được cố định từ nghiên cứu trước:
`dca_5m_plus_15m__15m` và `daily_routed_reversion_15m__15m`.
Tín hiệu từ nến Lighter đóng, router bật, auxiliary bật ở baseline, phiên
24h, tuổi tín hiệu tối đa 10 phút. Không tái chọn hướng bằng nến tương lai.

Từ 19/04 đến 03/09/2026 có **1.598 market duy nhất**, tương ứng 2.029 dự đoán
vì hai chiến lược có thể cùng gặp một hợp đồng. Mỗi market lưu raw response:

- Gamma: slug, condition ID, token IDs theo tên Up/Down, rule, thời gian,
  trạng thái, fee schedule.
- CLOB market: closed và token `winner=true`.
- CLOB market info: đường cong phí `fd.r`, `fd.e`.
- `prices-history` riêng cả hai token, yêu cầu độ phân giải một phút.

**1.598/1.598** có Gamma `umaResolutionStatus=resolved`, outcome chính xác
0/1, CLOB closed và token winner đồng ý. Không dùng last trade, giá gần 1
hoặc closed đơn lẻ để suy ra winner. Proposed, void/50–50, token sai hoặc
bất đồng bị loại. Đây là settlement **API xác nhận**, không phải xác minh
onchain độc lập; Gamma/CLOB có thể cùng dựa trên một hệ thống.

Rule lưu được: 1.483 market Chainlink spot, 115 market Chainlink TWAP.
Không tự trộn spot/TWAP để dựng nhãn. Chưa lấy signed reports để tái tạo
mốc giá Chainlink lịch sử; nhãn dùng kết quả cuối của chính market.

## 2. Baseline với nhãn Poly thay cho Lighter

Giai đoạn sau 14/07–03/09/2026, giữ nguyên entry và hướng đã cố định:

| Tín hiệu | Số mẫu | Đúng theo Lighter | Thắng theo settlement Poly | Nhãn bất đồng |
|---|---:|---:|---:|---:|
| Main5m + auxiliary15m | 399 | 57,64% | **57,89% — 231 thắng** | 17 |
| BB15m + router | 176 | 57,95% | **55,11% — 97 thắng** | 9 |

Đổi nguồn nhãn có ảnh hưởng, nhưng không tự nâng dự đoán đầu kỳ lên 90%.
BB15m đơn lẻ chưa chứng minh tốt hơn baseline với nhãn thật.

## 3. Thiết kế entry muộn

72 tổ hợp: hai tín hiệu × thời điểm T+30s/T+330s/T+630s × sáu ngưỡng giá
outcome 0/0,55/0,65/0,75/0,85/0,90. Ngưỡng là **giá tham chiếu token theo
hướng DCA**, không phải xác suất được mô hình chứng nhận. DOWN dùng chính
giá token DOWN, không suy ra giá mua bằng `1 - giá UP`.

Giá tham chiếu mới nhất phải có timestamp **không muộn hơn quyết định**,
tuổi ≤75 giây. Không dùng mẫu gần nhất nếu nó ở tương lai. Vẫn có rủi ro
giá này đã thay đổi trước khi thực sự mua; không gọi đây là ask.

Chọn cấu hình bằng giai đoạn 19/04–13/07, sau đó giữ nguyên để kiểm tra
14/07–03/09. Điều kiện: ≥100 cơ hội, phí biết, reference+1c<1, ROI giả định
sau phí dương; lấy top 3 cận dưới Wilson. Dòng không định giá được hoặc giá
vượt 1 không được coi là entry thắng miễn phí. ID được lưu riêng.

Lịch sử liên quan đã được nghiên cứu nhiều lần. Không coi đây là holdout
hoàn toàn chưa từng xem hay kiểm định đã hiệu chỉnh 72 phép thử. Giá đắt
lọc bớt cơ hội, không đảm bảo thanh khoản hoặc tạo lợi thế riêng của DCA.

### Ba ứng viên được chọn

Đều dùng main5m + auxiliary15m, vào ở **T+10 phút 30 giây**:

| Ngưỡng reference cùng hướng | Tập trước | Tập sau | Win-rate sau | Chi phí/share giả định TB sau |
|---|---:|---:|---:|---:|
| ≥0,85 | 249/262 — 95,04% | **119/125** | **95,20%** | 0,94181 |
| ≥0,75 | 344/373 — 92,23% | **149/159** | **93,71%** | 0,91616 |
| ≥0,65 | 400/453 — 88,30% | **175/189** | **92,59%** | 0,88499 |

Chi phí giả định = mua reference+1c rồi cộng phí, không phải giá đã khớp.
Ngưỡng 0,85 chọn khoảng 31% trong 399 cơ hội baseline kỳ sau. Cận dưới
Wilson 95% của 119/125 là **89,92%**: chưa khẳng định xác suất thật luôn >90%.
Tháng 9 chỉ có một cơ hội baseline, không diễn giải thành kết quả cả tháng.

Đối chiếu phụ T+5:30, ngưỡng 0,75: trước 177/203 = 87,19%, sau 88/96 =
91,67%. Không thuộc top 3 cuối cùng; chỉ là nhánh shadow so sánh thêm,
không chọn thay thế vì nhìn thấy ROI kỳ sau cao hơn.

### Đối chứng outcome được thị trường ưu tiên

Trong cùng **tập hợp cửa sổ cơ hội của hai chiến lược**, chọn token có giá
cao hơn, không yêu cầu đồng thuận DCA. T+630, ngưỡng 0,85, kỳ sau:
**225/245 = 91,84% thắng**, nhưng reference+1c sau phí **âm 2,82%**.

Win-rate cao tự nó không đủ. 245 và 125 entry là tập khác nhau: chưa phải
kiểm định paired chứng minh DCA tạo alpha. Đối chứng không đại diện tất cả
market vì chỉ xét cửa sổ có cơ hội DCA, và không dùng để chọn cấu hình.

## 4. Phí và độ nhạy giá

1.598 market hiện trả Gamma rate=0,07, exponent=1, khớp CLOB `fd`.
Trong khi đó, trường base_fee/taker_base_fee có thể là 1000. **Không tự
chia 1000/10000 rồi coi là phí phẳng 10%.** Mã mới đọc curve từng market;
thiếu, không hỗ trợ hoặc bất đồng thì không mặc định phí.

Mô hình cash-equivalent:
`cost/share = q + 0,07 × q × (1-q)`.
Đây không phải 7% phẳng trên vốn.
[Phí chính thức](https://docs.polymarket.com/trading/fees),
[tham số CLOB](https://docs.polymarket.com/api-reference/markets/get-clob-market-info).

Schedule được tải hiện tại, chưa chứng thực phí as-of quá khứ hay khả năng
metadata bị sửa hồi tố. Cash-equivalent chưa đối soát debit tiền/token với
receipt giao dịch thật. Không tính rebate hoặc phí bán vì giữ đến settlement.

| Ngưỡng T+630 | ROI giả định tập trước, reference+1c | ROI giả định tập sau, reference+1c |
|---|---:|---:|
| 0,85 | +0,93% | **+1,12%** |
| 0,75 | +1,75% | +2,49% |
| 0,65 | +0,91% | +5,37% |

ROI là trung bình `payout/cost - 1` với vốn bằng nhau mỗi entry, **không
phải lợi nhuận tài khoản, backtest khớp lệnh hay dự báo tương lai**. Các cấu
hình chồng nhau không được cộng như danh mục độc lập.

Độ nhạy giá trên cùng tập đủ điều kiện cho cả reference+1c và reference+3c:

- Ngưỡng 0,85, tập trước 214 mẫu: +1,39% → **−0,62%**.
- Ngưỡng 0,85, tập sau 99 mẫu: +2,21% → **+0,18%**.
- Ngưỡng 0,75, tập trước 325 mẫu: +2,18% → +0,05%.

Vì vậy cấu hình win-rate cao nhất không đồng nghĩa lợi thế tốt nhất. Vài
kết quả thắng đổi thành thua cũng có thể xóa biên lợi nhuận mỏng.

## 5. Ask, lịch sử orderbook và recorder thực tế

Gamma/CLOB public GET, Binance và RTDS truy cập được. Geoblock endpoint
`polymarket.com/api/geoblock` vẫn lỗi phân giải tên miền: **chưa xác nhận
quyền giao dịch theo IP/địa điểm**. Không đổi DNS, dùng proxy/VPN hay đặt
lệnh để thử vượt hạn chế.

`/book` market đã đóng trả 404. Có `orderbook-history` được nhắc trong tài
liệu lỗi: đã thử bốn cửa sổ tháng 4, tháng 7, tháng 9 và đang mở; truy vấn
asset_id/startTs/endTs/limit trả count=0. Chỉ kết luận các truy vấn này
chưa cho dữ liệu, không khẳng định mọi nguồn lịch sử orderbook đều không có.
[Lịch sử giá](https://docs.polymarket.com/api-reference/markets/get-prices-history),
[mô tả orderbook-history](https://docs.polymarket.com/resources/error-codes).

Đã xây `collect_poly_paper.py`, nhánh recorder/shadow độc lập:

- Lưu raw rule/token mapping và phí Gamma/CLOB; toàn bộ bids/asks hai phía,
  timestamp, depth. Fill không dùng midpoint.
- Ghi Chainlink TWAP60s, timestamp quan sát và `full_accuracy_value` E18.
- Đóng băng tín hiệu Binance từ nến đã đóng đầu kỳ; nếu bắt đầu giữa kỳ
  không backfill một quyết định đầu kỳ đã bỏ lỡ.
- SQLite ledger theo từng cấu hình: skipped/pending/settled. Chưa final
  không chốt PnL; settlement chạy lại không ghi đôi.

Hai lượt chạy thành công, mỗi lượt 120 giây:

| Lượt | Snapshot orderbook | Cập nhật TWAP | Cost probe $10 | Paper order |
|---|---:|---:|---:|---:|
| `paper_market_capture` | 24 | 113 | 24 | 0 |
| `paper_market_capture_v2` | 24 | 118 | 24 | 0 |

Cost probe của cả hai phía không phải lệnh được chọn. Không có paper order
vì hai lượt không có tín hiệu đầu kỳ được ghi đúng lúc; chưa có sample paper
settled để báo win-rate. Ledger settlement đã kiểm thử bằng fixture, chưa
chứng minh PnL end-to-end trên fill paper thực tế.

Đồng hồ máy chậm khoảng **21,5 giây** so với CLOB; Binance cũng lệch khoảng
22 giây khi kiểm tra. Recorder lấy trung vị ba offset, yêu cầu RTT thấp và
ổn định, chỉ hiệu chỉnh trong tiến trình. Không sửa giờ Windows/Bot1.

Depth shadow từ chối book cũ >5s, tương lai/crossed, phí không biết, thiếu
depth trong price cap, spread cao và dưới minimum bảo thủ. Phí làm tròn lên.
Chưa mô phỏng queue, hủy lệnh/race, 250ms/latency, partial fill hay debit
token thật. Các thí nghiệm $10 độc lập chưa phải danh mục chung có bankroll.

RTDS không có replay sau reconnect; gap được ghi rõ, không tự dựng TWAP từ
nến phút. Settlement cuối vẫn theo API market.
[Tài liệu TWAP/RTDS](https://docs.polymarket.com/market-data/chainlink-twap).

## 6. Cách chạy và trạng thái

Không đưa ứng viên vào `run_bot.py`, không bật calibration approved/live.
Recorder không đọc private key và không có phương thức gửi lệnh.

```powershell
cd D:\polybot
pip install -r requirements-research.txt
python -B research_polymarket_actual.py --offline
python -B collect_poly_paper.py --duration-seconds 120
python -B collect_poly_paper.py --settle-only
```

Muốn tự chạy phiên thu bốn giờ rồi dừng:

```powershell
python -B collect_poly_paper.py --duration-seconds 14400
```

Không cài scheduler/tiến trình chạy vô hạn. Các lượt thử đã kết thúc.
Chạy settle-only cùng output-dir để đối chiếu pending của đúng ledger.

Shadow có ba ngưỡng được chọn, nhánh T+330 và hai baseline đầu kỳ. Tín hiệu
paper dùng Binance, khác Lighter lịch sử; không tái dùng xác suất cũ như
calibration đã duyệt. Reference lịch sử được thay bằng midpoint hiện tại
để lọc đồng thuận, cũng là khác biệt cần đo. Fill qua asks, nhánh muộn giới
hạn tối đa midpoint+1c và cap 0,99. Thí nghiệm không có cam kết EV dương.

## 7. Việc tiếp theo trước khi xem xét cấp vốn

Giữ nguyên ứng viên để thu mẫu prospective, không thay ngưỡng sau vài lệnh
thua. Đo win-rate/PnL trên fill đủ điều kiện cùng số skip, spread, quote age,
gap; so với market-favourite tại cùng timestamp. Kiểm tra phí net-token,
nguồn settlement, slippage 1–3c, delay 250ms/1s, drawdown và vốn bị khóa.
Cần nhiều trăm fill qua các tháng/chế độ giá; số lượng đó không bảo đảm có
lãi. Điều kiện địa lý/tài khoản phải được xác nhận trước mọi quyết định live.

## 8. Kiểm thử và file kết quả

**43 tests passed**: nến đóng/không nhìn tương lai, mapping token đảo thứ tự,
proposed/void/bất đồng settlement, phí thiếu/sai, stale/depth/price cap,
ledger idempotency. Test đổi tất cả nhãn giai đoạn sau không làm đổi ID
được chọn trên giai đoạn trước.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -B -m pytest -q
```

Tắt autoload để tránh plugin anchorpy toàn máy thiếu dependency; không sửa
môi trường toàn máy.

Trong `actual_market_research_20260913`:

- `raw/`: 1.598 bundle API, khoảng 27,4 MB.
- `plan.json`, `analysis_manifest.json`: cấu hình, SHA-256 source/input/raw.
- `selected_on_validation.json`, `summary.json`.
- `settlement_predictions.csv`, `historical_reference_predictions.csv`.
- `favorite_control.csv`, `capability_probes.json`.

Code mới: `polymarket_bot/actual_research.py`, `research_polymarket_actual.py`,
`collect_poly_paper.py`, `probe_poly_history.py`, `tests/test_actual_research.py`.
Hai thư mục paper có `capture.sqlite3` và `summary.json` riêng.
