# Vào muộn hơn và triển khai oracle / edge / order flow

Ngày 13/09/2026. Bot1 tại `D:/backtest` chỉ đọc; mọi thay đổi trong Bot2. Không ký/gửi lệnh, không vượt chặn địa lý, không khởi động tiến trình chạy vô hạn.

## 1. Vào sau 10m30 có tăng win-rate không?

Có thể tăng **nhờ lọc lại cơ hội**, không phải chỉ nhờ đổi giờ mua. Cùng một market, cùng hướng và giữ tới settlement thì kết quả thắng/thua không đổi. Chờ thêm làm giá outcome và tập lệnh đủ điều kiện thay đổi.

Giữ hướng DCA đầu market; thử T+630, 690, 750, 810, 840, 870 giây. Tất cả đáo hạn T+900. Tại 14m30 chỉ còn 30 giây, không phải dự đoán thêm 15 phút kể từ lúc mua.

Dùng cùng dữ liệu 19/04–03/09/2026, 138 ngày lịch; 86 ngày trước và 52 ngày sau. Đây là lịch sử đã được nghiên cứu nhiều lần, **không phải holdout nguyên vẹn**. Không chọn rồi triển khai một mốc “tốt nhất” dựa trên bảng này.

### Giá tham chiếu ≥0.85: kết quả của toàn bộ các mốc

Ngân sách giả định $5/lệnh, mua tại reference+1c, phí per-market như nghiên cứu trước, giữ tới settlement. PnL là cash-equivalent, không phải thực thi xác nhận trên sàn.

| Mốc vào | Lệnh 86 ngày trước | Win trước | PnL trước | Lệnh 52 ngày sau | Win sau | PnL sau | PnL/lệnh sau |
|---|---:|---:|---:|---:|---:|---:|---:|
| 10:30 | 262 | 95.04% | +$12.15 | 125 | 95.20% | +$7.02 | +$0.056 |
| 11:30 | 288 | 94.79% | -$5.24 | 125 | 99.20% | +$27.53 | +$0.220 |
| 12:30 | 289 | 96.19% | +$14.13 | 121 | 99.17% | +$18.91 | +$0.156 |
| 13:30 | 261 | 95.40% | -$5.94 | 98 | 98.98% | +$13.18 | +$0.134 |
| 14:00 | 259 | 95.37% | -$5.67 | 98 | 98.98% | +$13.18 | +$0.134 |
| 14:30 | 191 | 95.81% | -$5.92 | 79 | 97.47% | +$3.43 | +$0.043 |

Không cộng các dòng: các market chồng lấn. Nếu mua tại các mốc khác nhau, ngay cả số lệnh bằng nhau cũng chưa chắc cùng market.

11:30 đạt 124/125 thắng ở giai đoạn sau nhưng lỗ ở giai đoạn trước. 12:30 có lãi ở cả hai giai đoạn với +1c, tuy nhiên khi chuyển sang +3c, giai đoạn trước trên **194 lệnh cùng đủ điều kiện** chuyển từ +$14.81 thành **-$4.62**. Vì vậy chưa chứng minh được một chiến lược lợi nhuận bền vững hoặc win thật 99%.

### Ngưỡng 0.65 cho thấy tăng thời gian không đồng nghĩa tăng win đều

| Mốc vào | Lệnh sau | Win sau | PnL sau (+1c) |
|---|---:|---:|---:|
| 10:30 | 189 | 92.59% | +$50.71 |
| 11:30 | 183 | 90.71% | +$6.55 |
| 12:30 | 156 | 92.95% | +$2.26 |
| 13:30 | 128 | 96.09% | +$29.31 |
| 14:00 | 128 | 96.09% | +$29.31 |
| 14:30 | 96 | 95.83% | +$14.63 |

### Giới hạn nghiêm trọng của lịch sử giá cuối market

- Giữ max-age 75 giây để tương thích nghiên cứu cũ. Nhưng tại 14m30 chỉ còn 30 giây: giá cũ 40–70 giây không đủ để chứng minh khả năng khớp lệnh.
- Với ngưỡng ≥0.85, số lệnh giai đoạn sau có reference cũ không quá 15 giây lần lượt là **12, 9, 11, 5, 0, 5**. Không thể dùng bảng chính như một backtest chính xác mức tick.
- 13m30 và 14m00 cho kết quả giống nhau ở giai đoạn sau do dùng lại những điểm lịch sử as-of, không phải xác nhận độc lập rằng hai mốc tương đương.
- Các điểm reference+padding ≥1 bị loại khỏi kịch bản tương ứng; càng muộn nhiều token gần 1 càng bị loại. Việc giảm số lệnh không có nghĩa tín hiệu DCA xuất hiện ít đi.
- Một chẩn đoán giữ nguyên 83 market đủ giá ở mọi mốc cho win **83.13% ở tất cả các mốc**. Tập này được xác định bằng khả dụng giá tương lai nên chỉ dùng minh họa tính bất biến của nhãn, không dùng làm chiến lược giao dịch.

## 2. Bollinger có khác yêu cầu tham khảo DCA không?

Không. **Bollinger là chỉ báo; DCA của Bot1 là chiến lược và quản lý vị thế sử dụng chỉ báo đó.** Phần đã kế thừa trong nghiên cứu Poly:

| Phần Bot1 đã đọc | Phần tương ứng trong Poly |
|---|---|
| `band_touch` / `entry_decision`: nến 5m đóng ở dải dưới cho long hoặc dải trên cho short | Nhánh `main_5m`, Up/Down theo hướng đó |
| `daily_route`: ngày hoàn tất trước đó so SMA25, ngưỡng short 1.5% | Bộ chọn hướng ngày trong `signal_grid.features` |
| `short_lane_15m_signal`: close 15m ở dải trên và tăng tối thiểu 60 bps/60m khi nhánh được bật | Nhánh `aux_short_15m` |

Có kiểm thử `test_raw_direction_matches_readonly_dca_contract`: nhập module thuần Bot1 ở chế độ không ghi bytecode, so sánh hướng có/không tín hiệu giữa hai bộ code với cùng giả định. Kiểm thử này đạt trong bộ test hiện tại.

Điều **chưa** được sao chép nguyên trạng:

- Quản lý chu kỳ nhiều lần nhồi, giá vốn bình quân, trailing/runner, TP/SL và thời gian chờ của DCA.
- Toàn bộ các bộ lọc tùy chọn, trạng thái vị thế và cấu hình thật của tiến trình Bot1 đang chạy. Kiểm thử hàm tín hiệu không chứng minh parity toàn bộ runtime.
- Nghiên cứu chọn router+nhánh phụ bật và phiên 24h. `.env` Bot1 chỉ được đọc các khóa chiến lược được chỉ định và thấy phiên 08–22 UTC; không coi cấu hình nghiên cứu 24h là bản mirror của tiến trình đó.
- Dữ liệu lịch sử đặc trưng là Lighter; recorder mới dùng Binance để tạo tín hiệu mở market. Khác nguồn phải được theo dõi riêng trong hiệu chuẩn, không coi là cùng phân phối.

`bb_reclaim` và độ dốc Bollinger trong đợt 33 biến thể là **bộ lọc thêm**, không thay hướng DCA gốc. Recorder nâng cao mới chỉ xét hướng `dca`; không dùng nhánh nghiên cứu `bb15_open` để thay thế DCA.

## 3. Đã xây dựng ba hướng mới đến mức nào?

### Hướng 1 — Oracle đúng nguồn và đặc trưng xác suất settlement

Đã có `OracleBuffer` nhận Chainlink spot, TWAP30 và TWAP60, giữ số E18 khi có. Chọn nguồn theo rule/link của market; không đổi TWAP thành spot, không tự đoán window không được nhận diện.

Đặc trưng gồm khoảng cách có dấu tới price-to-beat, thời gian còn lại, biến động quan sát và khoảng cách chuẩn hóa. Với TWAP chồng lấn, chỉ coi giá trị chuẩn hóa là **đặc trưng**, không gán trực tiếp một xác suất Gaussian.

Có kiểm tra tuổi giá, thời điểm nhận so với thời điểm quyết định, đủ tối thiểu 55 giây/30 quan sát, khoảng trống và giá trùng timestamp nhưng xung đột. Không dùng snapshot subscribe để backfill quyết định đã qua. [Tài liệu TWAP](https://docs.polymarket.com/market-data/chainlink-twap).

**Điểm chưa hoàn tất tự động:** Gamma đang mở trong các lần kiểm tra không trả `eventMetadata.priceToBeat`, dù metadata contract xác nhận `btc-15m-twap-60`. Không lấy `priceToBeat` trong cache market đã settlement rồi giả định đã biết lúc giao dịch. Có adapter `--verified-reference-file` để nhận giá mốc do người vận hành đã xác minh; thiếu giá mốc thì bỏ qua phần oracle/edge. Luồng oracle và sổ lệnh vẫn được ghi.

### Hướng 2 — Xác suất đã hiệu chuẩn và lợi thế sau giá vốn

Đã có bộ hiệu chuẩn thực nghiệm theo rule hash, nguồn oracle, mốc thời gian, khoảng giá và khoảng đặc trưng oracle:

- Chỉ học các hàng theo hướng DCA, có nhãn settlement API xác nhận và **đã nhận nhãn trước lúc fit**.
- Không dùng đặc trưng nhận sau thời điểm quyết định, không cho market hiện tại lọt vào tập nhãn học.
- Lặp polling không làm tăng số market độc lập. Mỗi ô cần ít nhất 50 market khác nhau; ít hơn thì không có xác suất mặc định.
- Dùng cận dưới Wilson để có đệm thống kê; không diễn giải thành bảo đảm xác suất. Chưa có kiểm chứng ngoại mẫu cho mô hình oracle mới.
- Tính giá khớp trung bình theo độ sâu ask, phí mỗi market, spread ≤0.03 và ngân sách paper $10. Chỉ tạo shadow fill khi `p_lower - giá_vốn/share ≥0.02`. Artifact chỉ mang nhãn `research_paper_only`, hết hạn sau 24 giờ.

Đã thử thêm hiệu chuẩn **chỉ theo giá lịch sử** từng tháng với khoảng cách một ngày khỏi mốc fit (không phải mô hình oracle mới). Một số mốc có 12–26 lệnh đều thắng, nhưng mẫu quá nhỏ: 26/26 vẫn chỉ có cận Wilson dưới khoảng 87.13%. Không coi các số 100% này là bằng chứng đủ để dùng tiền thật. Kết quả đầy đủ ở `late_entries_20260913/summary.json`.

### Hướng 3 — Order flow và mô phỏng maker

Đã thêm market WebSocket, ghi book/price changes/trades, tính spread, độ sâu quanh bid/ask 2 cent, mất cân bằng độ sâu và khối lượng giao dịch BUY/SELL được feed báo trong 30 giây. Khử trùng lặp giao dịch và không dùng trade tương lai. [Market stream](https://docs.polymarket.com/market-data/realtime-data).

Maker probe đặt **giả lập** tại best bid, giả định độ trễ 250 ms và hàng đợi trước mặt bằng khối lượng hiển thị tại giá đó. Chỉ trade SELL đúng giá mới làm giảm hàng đợi rồi khớp từng phần. Hủy/giảm size trên book không được tính là fill. Probe hết hạn sau 30 giây hoặc trước khi market hết 10 giây; stream gián đoạn thì vô hiệu hóa kịch bản. Không cộng rebate; giả định phí maker bằng 0 theo tài liệu hiện tại. [Phí](https://docs.polymarket.com/trading/fees).

Đây là probe độc lập trên cả hai outcome để nghiên cứu thực thi, **không phải lệnh chiến lược DCA**. Có bộ tổng hợp PnL giả định cho phần khớp khi có settlement xác nhận, nhưng không báo là fill/PnL thật. Vị trí hàng đợi thật và tác động của chính lệnh mình không được quan sát.

## 4. Kết quả chạy kiểm tra public feed

Lần chạy cuối 120 giây, đã dừng, dữ liệu tại `advanced_paper_capture_v3`:

- 25.273 market-stream events.
- 345 điểm oracle live được chấp nhận: spot 115, TWAP30 115, TWAP60 115; giữ thêm raw subscribe frames để kiểm toán.
- 48 ảnh chụp orderbook, 48 phép đo microstructure, 48 phép đo giá vốn theo độ sâu.
- 8 maker queue probes, không có khối lượng khớp giả lập trong mẫu ngắn này.
- 48 lần bỏ qua oracle/edge do thiếu price-to-beat đã kiểm chứng.
- **0 lệnh edge paper, 0 mẫu oracle đã settlement để học, 0 ô hiệu chuẩn đủ điều kiện.** Đây là thiếu đầu vào, không phải win-rate bằng 0.
- Không có lỗi tick, không có oracle reconnect gap trong lần cuối. Một market-gap event lúc dừng là đóng kết nối chủ động; probe còn dang dở được đánh dấu vô hiệu hóa.

Hai capture trước được giữ lại để truy vết kiểm tra: lần đầu gặp blank-frame parser/reconnect; lần sau đã sửa parser nhưng guard thời gian book quá chặt với `/time` độ chính xác giây. Đã sửa parser, batch ghi SQLite, thống nhất dung sai book tối đa 1 giây với phép tính depth hiện có. Oracle có timestamp nhỉnh hơn đồng hồ được giữ chờ, **chỉ dùng khi as-of clock đã tới timestamp đó**.

## 5. Chạy lại

Từ `D:/polybot`:

```powershell
python -B research_late_entries.py
python -B collect_advanced_paper.py --duration-seconds 120 --output-dir advanced_paper_capture_v3
python -B collect_advanced_paper.py --settle-only --output-dir advanced_paper_capture_v3
python -B fit_advanced_calibration.py --capture advanced_paper_capture_v3/capture.sqlite3 --output advanced_paper_capture_v3/calibration.json
python -B summarize_advanced_capture.py --capture advanced_paper_capture_v3/capture.sqlite3 --output advanced_paper_capture_v3/qa_summary.json
```

Nếu có giá mốc được người vận hành xác minh, truyền một file riêng bằng `--verified-reference-file`. Schema: `slug` chính xác của market, `price_to_beat` dạng chuỗi số, `observed_ms` là thời điểm thực sự đọc được giá đó, `source_url` để truy vết. Không dùng thời điểm giả hoặc giá kết thúc; collector kiểm tra slug và thời gian nhưng **không thể tự xác thực người vận hành đã nhập đúng giá**. Không dùng file này để bỏ qua chặn địa lý.

Khi có artifact đủ mẫu, truyền `--calibration advanced_paper_capture_v3/calibration.json`. File hiện tại rỗng nên vẫn không phát sinh edge entry. Không có lệnh nào trong các công cụ mới gọi API đặt lệnh hoặc đọc private key.

## 6. Trạng thái bàn giao và bước còn cần dữ liệu/đầu vào

Đã triển khai và kiểm thử các thành phần nghiên cứu của cả ba hướng, nhưng **chưa hoàn tất kiểm chứng lợi nhuận đầu-cuối của chúng**. Cần nguồn price-to-beat khả dụng lúc market đang mở hoặc đầu vào đã xác minh; tiếp đó cần thời gian thu thập các cơ hội DCA và settlement mới để hiệu chuẩn, kiểm tra khả năng khớp và forward-test. Không thể tạo những quan sát tương lai đó bằng một lần chạy hai phút.

Việc chạy dài hạn chưa được khởi động. Không thay chiến lược Bot1, không tự đổi Bot2 sang live, không cam kết 99% hay chọn cấu hình live từ dữ liệu lịch sử đã xem.

Tệp chính: `polymarket_bot/advanced_research.py`, `collect_advanced_paper.py`, `fit_advanced_calibration.py`, `summarize_advanced_capture.py`, `research_late_entries.py`, `tests/test_advanced_research.py`.

Kiểm tra cuối: **61 test đạt**, gồm parity hướng tín hiệu với hàm thuần Bot1, đặc trưng oracle không dùng dữ liệu tương lai, chọn đúng nguồn, loại nhãn tương lai, khử trùng lặp market trong calibration, phí/depth/edge và maker partial-fill/queue/expiry/gap. CLI collector và fitter đã được chạy kiểm tra; fitter thực tế trả 0 ô đủ mẫu, đúng với capture hiện có.
