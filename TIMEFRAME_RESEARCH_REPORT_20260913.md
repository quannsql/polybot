# DCA thắng >90% có chuyển sang dự đoán BTC 15 phút được không?

Ngày nghiên cứu: 13/09/2026. Mục tiêu chính là **15 phút**, không phải 15 giờ.
Chỉ đọc Bot1 tại `D:\backtest`; toàn bộ script và kết quả mới nằm tại `D:\polybot`.
Không đặt lệnh, không thay cấu hình runtime, không phê duyệt calibration.

## Kết luận

Có thể tái sử dụng tín hiệu DCA như một đặc trưng dự đoán, nhưng không thể
chuyển trực tiếp tỷ lệ chu kỳ có lãi thành xác suất đúng hướng lúc hết hạn.
Đổi khung trong phạm vi đã thử chưa tạo được độ chính xác gần 90%.
15 phút vẫn là đối chứng hợp lý; 1 giờ đáng thu thập thêm dữ liệu, chưa đủ
bằng chứng để chuyển bot sang khung đó. Đây là kết quả giá thay thế trên
Lighter, **không phải backtest khớp lệnh/settlement Polymarket**.

## 1. Bằng chứng trực tiếp từ chu kỳ DCA đã lưu

Nguồn: `D:\backtest\research_20260908\sl_campaign\all_trades_entry_features.csv`.
Đây là một bộ nghiên cứu cũ, chưa xác nhận trùng cấu hình bot đang chạy.
Thắng được định nghĩa là `realized_pnl > 0` trong file; không tái tính phí
hoặc chứng nhận bộ backtest DCA đó chính xác hoàn toàn.

Trong 1.217 chu kỳ BTC của file:

- 87,59% chu kỳ có lãi.
- Trung vị thời gian giữ: 67 phút; 82,99% giữ lâu hơn 15 phút.
- 66,15% có nhiều hơn một leg/vị thế thành phần.

627 chu kỳ có đầy đủ 12 giờ nến Lighter sau entry trong dữ liệu hiện có
(entry từ 15/11/2025 đến 14/08/2026). Giữ nguyên **cùng 627 entry và cùng hướng**:

| Cách đánh giá | Tỷ lệ thắng/đúng |
|---|---:|
| Kết quả cuối chu kỳ DCA đã ghi nhận | **90,75% — 569/627** |
| Giá sau 5 phút so với lúc entry | 58,37% |
| Giá sau 15 phút so với lúc entry | **56,46% — 354/627** |
| Giá sau 30 phút | 52,63% |
| Giá sau 1 giờ | 52,31% |
| Giá sau 4 giờ | 50,56% |
| Giá sau 12 giờ | 50,56% |

Có **231 chu kỳ DCA thắng nhưng nhãn hướng sau 15 phút sai**, tương đương
40,60% trong 569 chu kỳ thắng. Vì vậy, kết quả >90% và ~56% có thể đồng thời
đúng ngay trên cùng tập entry, không cần giả thiết tín hiệu bị viết sai.

Lưu ý: đây là nhãn rolling kể từ entry thực tế của DCA, không ép về biên
hợp đồng Poly. Giá entry proxy là open nến phút, không phải giá khớp thực tế
hay average sau DCA. Đây là chẩn đoán sự khác nhau giữa hai mục tiêu, không
phải kiểm định độc lập hay replay đầy đủ Bot1.

### Vì sao khác nhau?

Lõi Bollinger của Bot1 thiên về **hồi giá**: chạm/vượt biên dưới thì tìm LONG,
biên trên thì tìm SHORT tùy router. Đây không đơn thuần là bám xu hướng.
Các khung 5m/15m mô tả lúc phát tín hiệu, không quy định phải đóng sau 5/15 phút.

Bot1 còn có thêm vị thế làm đổi giá vốn, chốt/runner/trailing, dừng lỗ rộng hơn
mục tiêu lời và thời gian chờ hồi. Poly giữ tới settlement chỉ xét giá tại
mốc quy định; giá từng đi có lợi giữa chừng không biến một nhãn hết hạn sai
thành nhãn đúng. Mua thêm outcome cũng không thay đổi kết quả hợp đồng.

Ví dụ toán học đơn giản, không phải mô hình đầy đủ của Bot1: nếu mỗi thắng
kiếm 30 bp còn mỗi thua mất 200 bp trên cùng quy mô, tỷ lệ hòa vốn trước phí
đã là 200/(200+30) = 86,96%. Win-rate cao không tự nói lên độ chính xác dự báo
hay mức rủi ro; runner, DCA và quy mô thay đổi khiến PnL thật còn khác ví dụ này.

## 2. Thiết kế nghiên cứu nhiều khung

Script: [research_timeframes.py](research_timeframes.py).

- Khung tạo tín hiệu: 1m, 3m, 5m, 15m, 30m, 60m.
- Thời gian dự đoán: 5m, 15m, 30m, 60m, 240m.
- Ba họ tín hiệu: hồi giá hai phía BB; hồi giá được router daily cho phép;
  SHORT biên trên sau mức tăng ít nhất 60 bp trong 60 phút.
- BB20, độ lệch chuẩn 2, `ddof=0`, ít nhất 30 nến đóng hợp lệ.
- Cộng đối chứng main5m + auxiliary15m: tổng cộng 95 cấu hình định trước.
- Đối chứng bật router và auxiliary, phiên 24h. Đây là giả định nghiên cứu,
  không khẳng định giống cờ cấu hình Bot1 live; các gate nâng cao của Bot1
  chưa được replay toàn bộ.
- Một dự đoán mỗi cửa sổ cố định UTC, chỉ nhận tín hiệu đã đóng và không quá
  10 phút tuổi. Không kéo tín hiệu cũ hàng giờ để tăng số mẫu.
- Fit: 10/12/2025 đến trước 19/04/2026. Validation: 19/04 đến trước
  14/07/2026. Kiểm tra giai đoạn sau: 14/07 đến 03/09/2026 16:45 UTC.
- Loại nhãn đi xuyên qua ranh giới chia tập. Chọn tối đa ba cấu hình mỗi
  horizon bằng cận dưới Wilson trên validation, tối thiểu 100 train và
  200 validation, ghi ID trước khi tính điểm giai đoạn sau.
- Báo cáo cả baseline luôn Up/Down, kết quả từng tháng, Wilson và bootstrap
  theo cụm bảy ngày; phiên 08–22 UTC là phân tích độ nhạy, không chọn lại.

Dữ liệu Lighter ghép ba nguồn `data_lighter_240d`, `data_lighter_augall`,
`data_lighter_0903`: 421.485 phút trên lưới, 54 phút thiếu, 64.315 dòng trùng
giữa nguồn, không có xung đột OHLC trên timestamp trùng. Nguồn đầu được ưu
tiên; khoảng thiếu không được lấp bằng giá tương lai. Router cần 25 ngày đủ
dữ liệu, nên gap làm giảm đáng kể coverage cuối kỳ. Ví dụ baseline15m tháng
9 chỉ có một dự đoán; không diễn giải đây là thành tích bền vững cả tháng 9.

Lịch sử này từng được khảo sát trước, nên không gọi đây là holdout hoàn toàn
chưa nhìn thấy. 95 biến thể tạo rủi ro chọn trúng ngẫu nhiên; không tuyên bố
ý nghĩa thống kê đã hiệu chỉnh đa kiểm định. Chỉ có ít cụm tuần ở giai đoạn
sau nên khoảng bootstrap có thể quá lạc quan.

BB20 trên 1m và 60m có độ dài thời gian khác nhau; đây là so sánh chiến lược
đa khung, không cô lập riêng tác động resampling. Chính sách tuổi tối đa
10 phút cũng làm khác tập entry giữa các horizon. Bảng chu kỳ cùng entry
ở phần 1 và chẩn đoán cùng tín hiệu ở phần 4 giúp đối chiếu hạn chế này.

## 3. Kết quả kiểm tra giai đoạn sau

### Giữ nguyên họ tín hiệu main5m + auxiliary15m, đổi thời gian dự đoán

| Hết hạn | Validation: số mẫu / đúng | Giai đoạn sau: số mẫu / đúng |
|---|---:|---:|
| 5 phút | 1.509 / 55,33% | 618 / **52,10%** |
| 15 phút | 1.014 / 56,02% | 399 / **57,64%** |
| 30 phút | 493 / 55,98% | 196 / **56,63%** |
| 1 giờ | 225 / 56,89% | 88 / **60,23%** |
| 4 giờ | 49 / 51,02% | 19 / **52,63%** |

Các dòng không cùng tập entry. 1 giờ có tỷ lệ cao nhất trong bảng này nhưng
chỉ 88 mẫu; cận dưới Wilson 95% là 49,78%, chưa đủ để kết luận vượt 50% chắc
chắn. Baseline 15m có 399 mẫu và cận dưới 52,75%; luôn Up trên chính các
timestamp đó cũng đạt 54,64%, nên lợi thế so với đối chứng này chỉ khoảng
3 điểm phần trăm, không phải 7,64 điểm. Chưa có kiểm định paired với luôn Up.

### Đổi cả khung tín hiệu: những ứng viên được chọn từ validation

| Tín hiệu → hết hạn | Validation | Giai đoạn sau |
|---|---:|---:|
| BB30m + router → 15m | 210 / 63,33% | 99 / 55,56% |
| BB15m + router → 15m | 440 / 58,64% | 176 / 57,95% |
| BB15m hai phía → 15m | 1.003 / 56,93% | 397 / 55,92% |
| BB15m + router → 30m | 209 / 59,81% | 83 / 55,42% |
| BB15m hai phía → 1h | 232 / 58,62% | 85 / 50,59% |
| BB5m + router → 1h | 200 / 57,50% | 76 / 60,53% |
| BB1m hai phía → 4h | 256 / 56,64% | 126 / 57,14% |

Đây là các ví dụ đáng chú ý, không phải toàn bộ bảng 95 cấu hình. Toàn bộ
kết quả và danh sách chọn cố định nằm trong JSON. BB30m→15m là ví dụ rõ về
63,33% trên validation không giữ được ở giai đoạn sau.

BB15m + router →15m chỉ nhỉnh 0,31 điểm so với baseline, với ít mẫu hơn.
Trên 119 cửa sổ mà hai bot cùng dự đoán, hướng hoàn toàn giống nhau, cả hai
đúng 58,82%. Chưa có bằng chứng đổi sang BB15m cải thiện chất lượng dự đoán
trên cùng cơ hội; phần khác biệt là chọn thời điểm giao dịch khác.

## 4. Chạm mục tiêu không đồng nghĩa đúng lúc hết hạn

Lấy cùng 2.114 tín hiệu thô baseline từ 19/04, mỗi tín hiệu có đủ 12 giờ nến;
không DCA, không mô phỏng khớp lệnh:

| Thời gian quan sát | Đúng hướng tại cuối kỳ | Từng chạm lời 30 bp |
|---|---:|---:|
| 5 phút | 54,30% | 2,93% |
| 15 phút | 54,92% | 11,16% |
| 30 phút | 56,10% | 21,24% |
| 1 giờ | 55,01% | 34,86% |
| 4 giờ | 55,68% | 65,33% |
| 12 giờ | 54,45% | 81,27% |

Chờ lâu tăng xác suất **từng có cơ hội hồi**, nhưng độ đúng ở điểm kết thúc
vẫn quanh 55%. Có 28,19% tín hiệu chạm +30 bp trong 12h nhưng kết thúc 12h
sai hướng. Chẩn đoán TP30 trước SL200 dùng OHLC phút và giả định SL trước nếu
cả hai chạm trong cùng phút; không xác nhận có thể khớp giá mục tiêu.

Ví dụ tín hiệu DOWN 04/05/2026 02:00 UTC: giá đầu 79.742,2, chạm mục tiêu
giảm 30 bp ở phút thứ ba, nhưng đóng 15m ở 79.880,1. SHORT có thể đã có cơ hội
chốt, trong khi hợp đồng DOWN giữ tới hết hạn vẫn thua theo nhãn giá này.

![Chạm mục tiêu và giá cuối kỳ](timeframe_research_20260913/touch_vs_expiry.png)

## 5. Ràng buộc riêng của Polymarket

Không thể chỉ thay `15` thành `60` trong bot rồi xem như thị trường giống nhau:

- Hợp đồng hourly đã kiểm tra dùng nến Binance BTC/USDT 1h open/close.
  [Quy tắc hợp đồng 22/07/2026 4AM ET](https://polymarket.com/event/bitcoin-up-or-down-july-22-2026-4am-et).
- Hợp đồng 15m tháng 9 đã kiểm tra chỉ định Chainlink BTC/USD TWAP 60s, không
  phải giá Lighter. Phải đọc rule từng market và đúng phiên bản lịch sử.
  [Quy tắc hợp đồng 15m](https://polymarket.com/event/btc-updown-15m-1789020900).
- Chưa xác nhận hợp đồng BTC30m tiêu chuẩn trong phạm vi tra cứu; 30m hiện là
  horizon nghiên cứu. Lưới UTC4h chưa được ghép với lịch market thực tế.

Đối chiếu nguồn giá trên các timestamp chung với file Binance 30 ngày:
baseline15m có 337 mẫu, đúng 56,97% theo Lighter và 58,16% theo Binance;
10 nhãn khác nhau. Đây là **cùng tín hiệu Lighter được gán lại nhãn**, không
phải chiến lược Binance độc lập, cũng không thay thế nhãn Chainlink.

Win-rate phải đi kèm giá mua: với giả định phí crypto hiện tại
`fee/share = 0,07 × q × (1-q)`, mua giá 0,50 cần đúng trên 51,75% để hòa vốn
trước trượt giá; mua 0,55 cần trên 56,7325%. Đây là phép tính chi phí cộng
thêm đơn giản, không replay cơ chế giao nhận token. Phải đọc fee parameters
của market thực tế, không áp thông số hiện tại ngược toàn lịch sử.
[Tài liệu phí chính thức](https://docs.polymarket.com/trading/fees).

JSON có độ nhạy ask 0,48/0,50/0,52/0,55, không phải PnL có thể thực hiện.
Chưa có orderbook lịch sử, bid/ask, độ sâu, thời điểm công bố nến, latency,
fill, giá vào sau 20–45 giây, và settlement Chainlink. Không dùng các tỷ suất
giả định đó để cấp vốn hay bật live. Việc đọc tài liệu không chứng minh tài
khoản/IP Việt Nam được phép giao dịch; nghiên cứu offline không cần vượt chặn.

## 6. Hướng tiếp theo đề xuất

1. Giữ baseline 5m+15m→15m để đối chứng; BB15m+router→15m là ứng viên song
   song, không tự thay thế. Giữ cấu hình cố định trước khi thu mẫu mới.
2. Ghi nhận thêm baseline→1h và BB5m+router→1h với đúng nhãn Binance theo
   market. Không kết luận 60% từ 76–88 mẫu là chiến lược thắng đã xác nhận.
3. Thu dữ liệu market ID, rule, mốc giá, giá nguồn settlement, bid/ask, độ sâu,
   phí và paper fill tại thời điểm quyết định. Chỉ đánh giá EV trên giá có
   thể mua, kèm drawdown và độ bất định, không chỉ tối đa hóa win-rate.
4. Nếu muốn bám cơ chế DCA hơn, nghiên cứu mua/bán outcome trước hết hạn là
   một chiến lược khác cần lịch sử orderbook và cả chi phí vào/ra. BTC từng
   chạm TP không đảm bảo outcome có thể bán có lãi. Không suy ra từ OHLC hiện tại.
5. Tập tiếp theo chưa dùng để chọn tham số, ít nhất vài trăm cơ hội mỗi ứng
   viên qua nhiều tháng/chế độ giá. Mốc số lượng không bảo đảm hiệu quả;
   kiểm tra tương quan, độ ổn định từng tháng và so sánh cùng timestamp.

## 7. Tái lập và kiểm thử

```powershell
cd D:\polybot
pip install -r requirements-research.txt
python -B research_timeframes.py
python -B research_dca_cycles.py
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -B -m pytest -q
```

Kết quả kiểm thử: **17 passed**. Tắt autoload vì plugin `anchorpy` toàn máy
đang thiếu `pytest_xprocess`; không sửa môi trường toàn máy. Các test mới
kiểm tra nến đóng/prefix invariance, tuổi tín hiệu, gap, tie Up, purge nhãn
qua split, và chạm TP rồi kết thúc sai hướng/same-minute SL-first.

Các file đầu ra nằm trong `timeframe_research_20260913`: `plan.json`,
`selected_on_validation.json`, `summary.json`, `predictions.csv`,
`path_cohort.csv`, `dca_cycles.json`, `dca_cycles_comparison.csv`,
`timeframe_matrix.png`, `touch_vs_expiry.png`. Manifest dữ liệu có SHA-256.

Chưa triển khai chiến lược mới vào runtime. Không có lệnh thử hoặc lệnh thật.
