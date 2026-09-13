# Nghiên cứu bổ sung tín hiệu DCA → Polymarket BTC 15 phút

Ngày: 13/09/2026. Chỉ nghiên cứu offline trong `D:/polybot`; không đổi Bot1, không đổi cấu hình bot chạy, không đặt lệnh.

## Kết luận chính

Có hướng đáng kiểm tra tiếp, đặc biệt **giới hạn giá mua và tránh biến động ngắn hạn tăng vọt**. Nhưng đợt nghiên cứu này **chưa xác nhận được cấu hình mới cải thiện ổn định đồng thời win-rate và PnL**. Không có cấu hình nào trong 33 thử nghiệm đạt đủ bộ tiêu chí đã ghi trước khi chạy: tối thiểu 100 lệnh ở giai đoạn chọn, win-rate ≥85%, PnL dương khi giá mua bằng giá tham chiếu +3 cent.

Đây không phải kết luận rằng Polymarket không thể có lợi thế. Nó cho thấy thêm indicator và tối ưu trên cùng một lịch sử chưa đủ để chứng minh lợi thế đó.

## Dữ liệu, giá và cách tính

- Giữ nguyên tập cơ hội và hướng của `dca_5m_plus_15m__15m`, không sinh tín hiệu cho toàn bộ thị trường.
- 1.413 dự đoán DCA có nhãn settlement chính thức trong nghiên cứu trước; 1.409 market có ít nhất một giá tham chiếu hợp lệ tại các mốc thử mới, tổng cộng 4.211 quan sát market/thời điểm. Một quan sát không đồng nghĩa một lệnh.
- Khoảng dữ liệu: 19/04/2026 00:30 UTC đến 03/09/2026 16:00 UTC, phủ 138 ngày lịch, ngày cuối chưa đủ. Giai đoạn chọn: 19/04–13/07, 86 ngày; giai đoạn sau: 14/07–03/09, 52 ngày.
- Bộ nến Lighter ghép từ ba file read-only trong `D:/backtest`: 421.485 vị trí phút, 54 phút thiếu. Không điền giá vào phút thiếu. Đây là dữ liệu đặc trưng, không phải nguồn settlement Chainlink.
- Settlement lấy từ cache Gamma/CLOB đã đối chiếu, không suy ra thắng từ giá token gần 1. Lịch sử giá token là giá tham chiếu, **không phải ask khớp được và không có bằng chứng độ sâu lịch sử**.
- Phí lấy theo từng market trong cache. Metadata được tải ở hiện tại, chưa chứng minh biểu phí tại thời điểm giao dịch lịch sử.
- Mỗi lệnh giả định ngân sách tổng $5, không tăng tiền sau thua, giữ đến settlement. Nếu `q` là giá mua giả định và `r` là fee rate, mô hình cash-equivalent dùng `c = q + r*q*(1-q)`; thắng lãi `5/c - 5`, thua mất `5`.
- Hai kịch bản độc lập: `q = reference + 0.01` và `q = reference + 0.03`. Kịch bản sau đắt thêm **2 cent so với kịch bản trước**, không cộng thêm 3 cent một lần nữa.
- Những hàng có `q >= 1` bị loại khỏi kịch bản tương ứng. Các challenger giới hạn reference ≤0.95 nên so sánh +1c/+3c trên đúng cùng tập lệnh. Baseline không có trần: chỉ đối chiếu hai kịch bản qua `paired_n` và `paired_pnl_1c` trong JSON, không so hai tổng khác tập lệnh.
- $5 là quy đổi toán học, chưa chứng minh vượt điều kiện khối lượng tối thiểu của mọi market. Chưa mô phỏng chính xác fee debit/net shares, độ trễ, khớp một phần, xếp hàng maker hoặc vốn bị giữ trong lúc chờ settlement.

Đã đối chiếu lại **2.805 hàng** ở hai mốc cũ 5m30 và 10m30: giá tham chiếu và PnL $5 trùng kết quả nghiên cứu trước trong sai số số học. Vì thế khác biệt ở đây không đến từ đổi công thức PnL baseline.

## Đã thử những gì?

Ba mốc vào: T+5m30, T+8m30, T+10m30; cả ba vẫn đáo hạn T+15m. Hướng DCA được giữ từ đầu market. Mỗi policy chỉ một lệnh mỗi market, không cộng lệnh của nhiều policy thành một danh mục.

Mỗi mốc có 11 bộ lọc; tất cả challenger dùng reference trong [0.65, 0.95], trừ hai trần thấp hơn:

| Mã bộ lọc | Điều kiện bổ sung |
|---|---|
| cap95 | Chỉ giới hạn giá tham chiếu tối đa 0.95 |
| cap90 | Giảm trần tham chiếu xuống 0.90 |
| cap85 | Giảm trần tham chiếu xuống 0.85 |
| spot_lead | BTC đang nằm phía có lợi so với giá mở market, theo hướng DCA |
| lead_z1 | Khoảng cách có lợi ≥1 lần độ bất định ước lượng cho thời gian còn lại |
| momentum3 | Lợi suất BTC 3 phút gần nhất cùng hướng DCA |
| bb_reclaim | Giá BTC gần nhất nằm trong dải Bollinger 5m đã đóng; không khẳng định có một sự kiện cắt lại dải chính xác |
| token_momentum2 | Giá tham chiếu outcome tăng so với điểm as-of trước đó 2 phút |
| quiet_vol | Độ lệch chuẩn lợi suất 1m trên 5 phút / trên 60 phút ≤1.5 |
| normal_edge3 | Xác suất từ mô hình Gaussian đơn giản vượt chi phí/share ít nhất 0.03; đây **không phải xác suất đã hiệu chuẩn** |
| slope15_agrees | Độ dốc đường giữa Bollinger 15m cùng hướng DCA |

Các bộ lọc thử riêng, không tìm toàn bộ tổ hợp. Nến chỉ được dùng sau khi đóng; giá token chỉ lấy timestamp không vượt thời điểm vào, tối đa cũ 75 giây. Các đặc trưng BTC được đo từ phút đã đóng gần nhất, nên có độ trễ khoảng 30 giây tại ba mốc này.

## Kết quả minh họa ở 52 ngày sau

Các challenger dưới đây được trình bày để giải thích kết quả, **không phải các cấu hình đã vượt bộ lọc chọn trước**. Việc thấy một dòng đẹp sau khi xem nhiều dòng không biến nó thành kiểm chứng độc lập.

Tất cả các dòng bảng này vào T+10m30, $5/lệnh, giá tham chiếu +1c và phí trong mô hình:

| Cấu hình | Số lệnh | Win-rate | Tổng PnL | PnL trung bình/lệnh |
|---|---:|---:|---:|---:|
| Baseline cũ, reference ≥0.65 | 189 | 92.59% | +$50.71 | +$0.268 |
| Baseline cũ, reference ≥0.85 | 125 | 95.20% | +$7.02 | +$0.056 |
| Giới hạn reference 0.65–0.95 | 142 | 90.85% | +$51.84 | +$0.365 |
| Giới hạn 0.65–0.95 + quiet_vol | 136 | 91.91% | +$59.89 | +$0.440 |

Không cộng các dòng: nhiều market trùng nhau. Đây là PnL mô phỏng giá tham chiếu, không phải tiền lãi thực hiện hay dự báo thu nhập.

### Vì sao chưa chọn quiet_vol dù PnL đẹp?

- 52 ngày sau: 125 thắng, 11 thua. Tổng lợi nhuận các lệnh thắng +$114.89, trừ $55 thua còn +$59.89. Thắng trung bình +$0.919, thua -$5. Mức sụt giảm PnL lũy kế lớn nhất khoảng $13.45.
- Nhưng ở 86 ngày trước: 334 lệnh, win chỉ **84.73%**; PnL +1c chỉ **+$7.07** và chuyển thành **-$30.33** ở +3c trên cùng 334 lệnh. Riêng tháng 5, +1c lỗ **$27.47**; drawdown cả giai đoạn trước khoảng **$44.88**.
- Chênh lệch PnL ở 52 ngày sau so baseline ≥0.65 chỉ **+$9.18**. Bootstrap ghép cặp theo tổng PnL tuần cho khoảng 95% thăm dò **[-$6.84, +$29.88]**, vẫn chứa 0; chỉ có 8 cụm tuần và chưa điều chỉnh thử nhiều giả thuyết.
- +3c ở giai đoạn sau còn +$43.39 trên cùng 136 lệnh, nhưng không xóa được thất bại ở giai đoạn trước.

Vậy đây là ứng viên để đo trên dữ liệu mới, không phải nâng cấp có thể khẳng định ngay.

### Những hướng không cho kết quả thuyết phục

- Momentum BTC 3m tại T+10m30: giai đoạn trước -$13.37, sau +$11.12 ở +1c; không cải thiện tổng thể so baseline.
- Momentum giá token 2m tại T+10m30: giai đoạn trước -$2.28, sau +$15.02 ở +1c.
- Bắt độ dốc 15m đồng hướng tại T+10m30: giai đoạn trước -$32.09, sau +$8.43 ở +1c.
- Khoảng cách/biến động `lead_z1` tại T+10m30: giai đoạn sau win 92.86% nhưng chỉ 42 lệnh, +$1.66 ở +1c và -$2.58 ở +3c. Xác suất đúng cao không đồng nghĩa mua rẻ.
- Gaussian edge chưa hiệu chuẩn rất ít lệnh: tại T+10m30 chỉ 12 lệnh trước và 4 lệnh sau. Không dùng để tuyên bố đã tìm thấy lợi thế xác suất.
- Vào sớm không đương nhiên tốt: cap95 tại 5m30 có win 85.33%, +$44.46 ở giai đoạn sau; 8m30 win 86.21%, +$23.78; 10m30 win 90.85%, +$51.84. Tập lệnh khác nhau theo giá ở mỗi mốc, không phải thử nghiệm nhân quả của riêng thời gian vào.

Toàn bộ 33 kết quả, bao gồm các bộ thua, nằm trong `signal_extensions_20260913/summary.json`.

## Kiểm tra chọn lại cấu hình theo tháng

Mỗi đầu tháng chỉ chọn bằng các market đã hết hạn trước mốc đó; quy tắc chọn không đổi. Không dùng nhãn tương lai của tháng đang giao dịch. Thời điểm hết hạn chỉ là proxy khả dụng của nhãn trong nghiên cứu, không mô phỏng chính xác độ trễ resolution; các market cuối tập train thực tế cách mốc chọn ít nhất một giờ.

| Tháng | Policy chọn từ quá khứ | Lệnh | Win | PnL +1c | PnL +3c |
|---|---|---:|---:|---:|---:|
| 06/2026 | Không đủ điều kiện | 0 | — | $0 | $0 |
| 07/2026 | d630_cap90 | 98 | 81.63% | +$10.52 | -$1.31 |
| 08/2026 | d630_bb_reclaim | 75 | 90.67% | +$18.81 | +$10.26 |
| 09/2026 đến 03/09 | d630_quiet_vol | 0 | — | $0 | $0 |
| Tổng | Không chồng lệnh | 173 | 85.55% | +$29.33 | +$8.95 |

Drawdown +1c khoảng $24.35, chuỗi thua dài nhất 3. Baseline ≥0.65 trên cùng khoảng lịch 01/06–03/09 có 390 lệnh, win 90.77%, PnL +1c +$83.25. Baseline này đã được khảo sát/chọn trong nghiên cứu trước nên đây là mốc tham khảo hồi cứu, không phải đối thủ được chọn độc lập trước 01/06. Dù vậy, không có cơ sở nói cơ chế chọn lại hàng tháng đã vượt baseline.

## Hướng nên ưu tiên tiếp

### 1. Mô hình xác suất settlement đúng nguồn, thay cho chỉ dự đoán hướng BTC

Giữ DCA làm tín hiệu bối cảnh. Đo thêm khoảng cách giá **nguồn oracle đúng theo từng hợp đồng** so với price-to-beat, thời gian còn lại, biến động và động lượng. Phân tách contract Chainlink spot và contract TWAP, không trộn hai luật thành một nhãn từ nến Lighter.

Polymarket cung cấp TWAP Chainlink qua RTDS không cần credentials; luồng không có lịch sử/replay khi ngắt kết nối. Vì vậy phải tự ghi từ trước, không thể giả lập rằng đã có TWAP lịch sử bằng close 1m. [Tài liệu Chainlink TWAP](https://docs.polymarket.com/market-data/chainlink-twap).

Phải hiệu chuẩn xác suất bằng dữ liệu quá khứ đã settlement, đánh giá riêng từng luật và các khoảng giá. Mô hình Gaussian proxy đã thử ở trên chưa đạt tiêu chuẩn; không đem xác suất của nó đặt tiền thật.

### 2. Chỉ mua khi lợi thế vượt chi phí thực

Điều kiện cần là xác suất thắng ước lượng đủ tin cậy lớn hơn **giá vốn/share sau phí**, có thêm khoảng đệm cho sai số mô hình. Không dùng `reference ≥0.85` thay cho điều kiện đó.

Giá hiển thị có thể là midpoint hoặc giá giao dịch cuối; mua ngay phải xét ask và độ sâu. Nên thu thập cả hai outcome, spread, giá khớp trung bình theo ngân sách, tuổi quote và độ trễ. [Giá và order book](https://docs.polymarket.com/concepts/prices-orderbook).

Trần 0.95 trong nghiên cứu là trần **tham chiếu**. Trong bot tương lai phải dùng trần **giá khớp thực** suy ra từ xác suất/chi phí, không copy nguyên số 0.95 sang limit price.

### 3. Order flow và maker: có tiềm năng nhưng cần dữ liệu mới

- Thử mất cân bằng độ sâu bid/ask và dòng giao dịch chủ động, kết hợp thay đổi oracle để phân biệt một cú hồi được duy trì với tín hiệu đang bị đảo ngược. Đây là giả thuyết, chưa có PnL kiểm chứng trong bộ dữ liệu này. Market stream có book, price change và last trade để ghi lại. [Real-time data](https://docs.polymarket.com/market-data/realtime-data).
- Thử đặt maker/post-only để giảm phí và cải thiện giá, nhưng mô phỏng riêng xác suất không khớp, khớp một phần, vị trí hàng đợi và việc dễ được khớp ngay lúc giá bắt đầu đi bất lợi. Không giả định mọi limit order đều khớp ở giá mong muốn. Theo tài liệu hiện tại maker không chịu trading fee; taker crypto dùng đường phí theo giá. Không cộng rebate giả định vào PnL. [Phí Polymarket](https://docs.polymarket.com/trading/fees).

### 4. Cách thử tiếp để tránh tối ưu quá khứ

Đề xuất giữ một baseline ≥0.65 và tối đa hai challenger đã chốt: trần giá + quiet_vol, và mô hình oracle/giá vốn khi đủ dữ liệu hiệu chuẩn. Thu thập toàn bộ market BTC 15m trong thời gian mới, không chỉ những market có tín hiệu DCA, để có đối chứng thị trường và không bỏ sót cơ hội ngoài tập cũ.

Ghi paper shadow độc lập, không tăng tiền theo kết quả, không đổi tham số giữa đợt. Báo cáo cả tín hiệu bị bỏ, tỷ lệ có giá đủ sâu, số khớp giả lập, tỷ lệ thắng, PnL thực thi giả lập, PnL/lệnh, drawdown và kết quả từng tuần. Chỉ kết luận cải tiến sau kiểm tra dữ liệu mới; không cam kết rằng đủ một số ngày/lệnh nhất định sẽ chứng minh được lợi thế.

Không chạy giao dịch thật hoặc vượt hạn chế địa lý. Đợt này không khởi động collector chạy nền; muốn dữ liệu tương lai cần một đợt thu thập được cấu hình và vận hành riêng.

## Giới hạn và trạng thái bàn giao

- 52 ngày sau **đã được xem trong các lần nghiên cứu trước**, không phải holdout nguyên vẹn. Bộ quy tắc mới được ghi trước lần chạy này không xóa được thiên lệch do tái sử dụng lịch sử.
- Các thống kê confidence ở đây có tính thăm dò, chưa hiệu chỉnh 33 phép thử, và mẫu theo luật TWAP còn nhỏ.
- Win-rate DCA cao đến từ cả cơ chế bình quân giá/thoát lệnh và phân bố thắng nhỏ-thua lớn; không có nguyên lý đảm bảo chỉ đổi config là giữ được tỷ lệ đó với payout và deadline khác.
- **Không cấu hình mới nào được phê duyệt live.** Chỉ thêm script, test và kết quả nghiên cứu trong `D:/polybot`.
- Test: **49 passed**, gồm kiểm tra không đọc nến tương lai/nến chưa đóng, gap dữ liệu, không chọn bằng nhãn giai đoạn sau, trần giá không phụ thuộc thắng thua, công thức PnL/drawdown.

Tệp liên quan: `research_signal_extensions.py`, `tests/test_signal_extensions.py`, `signal_extensions_20260913/protocol.json`, `selected_before_later_scoring.json`, `manifest.json`, `summary.json`, `feature_observations.csv`, `walk_forward_trades.csv`.

Chạy lại từ `D:/polybot`:

```powershell
python -B research_signal_extensions.py
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -B -m pytest -q
```
