# Đổi khung Bollinger/DCA và thời hạn market

Đã khảo sát 108 tổ hợp, dựng lại tín hiệu gốc khớp hoàn toàn. Kiểm tra 5088 market trong nhóm chọn để đánh giá giá outcome và settlement.

## Kết luận

**Chưa xác nhận được biến thể nào tốt hơn một cách bền vững để thay cấu hình đang chạy.** Ứng viên được chọn bằng giai đoạn trước bị lỗ ở giai đoạn sau.
Hai hướng đáng nghiên cứu tiếp là market 5m với Boll chính/phụ 30m/30m và market 4h với Boll 1m/60m. Đây là nhận xét khám phá sau khi xem kết quả, không phải hai cấu hình đã vượt kiểm định độc lập.
Bản 5m có 98/101 lệnh thắng, nhưng giai đoạn trước lỗ khi giả định giá mua đắt thêm 3c. Bản 4h có 51/52 lệnh thắng và có lãi ở cả hai giai đoạn dưới stress 3c, nhưng chỉ có 39 lệnh giai đoạn trước, không đạt mức tối thiểu 50 đã định. Không có cơ sở gọi 100% của 13 hoặc 28 lệnh gần đây là tỷ lệ thắng thật.
Với ví chỉ $50 và stake $30, mô phỏng bản 5m dừng khả năng mua sau 41 lệnh, còn $17.34 và bỏ 60 cơ hội tiếp theo. Vì thế PnL toàn tập +$70.53 không phải lợi nhuận đạt được bằng ví $50 này.

## Quy tắc và cách chọn

- Nhánh chính: chạm Bollinger theo hướng router ngày. Nhánh phụ short: chạm dải trên và pump >=60bps trong 60 phút; nhánh phụ ưu tiên.
- Giữ Bollinger 20/2, SMA ngày 25, short depth 1,5%, phiên 24h. Chỉ dùng nến đã đóng. Khung thay đổi là độ dài mỗi nến, không đổi số kỳ hoặc độ lệch chuẩn.
- 18 cặp khung: main 1/3/5/10/15/30m và auxiliary 5/15/30/60m, chỉ nhận cặp mà auxiliary chia hết cho main. Mỗi cặp thử horizon 5/10/15/30/60/240m.
- Mỗi market lấy tín hiệu mới nhất trước đầu kỳ, tuổi tối đa 10 phút. Không có tín hiệu đủ mới thì bỏ market, kể cả với horizon dài.
- Giữ tỷ lệ vào muộn 11:30 trên 15m: market5m vào3:50, 10m vào7:40, 15m vào11:30, 30m vào23:00, 1h vào46:00, 4h vào3h04. Không vào lúc11:30 cho mọi horizon.
- Hai biến thể mỗi horizon được chọn bằng Wilson lower trên tín hiệu dự đoán giá Lighter ở 86 ngày trước (>=100 mẫu train và validation), cộng bản gốc làm đối chứng. Sau đó mới kiểm tra giá outcome của nhóm này. Đây là sàng lọc có giới hạn, không chứng minh tối ưu toàn bộ biến thể theo PnL.
- Trong nhóm có dữ liệu outcome, chọn theo PnL/lệnh của 86 ngày trước, tối thiểu50 lệnh và PnL dương ở cả +1c và +3c. Ghi lựa chọn trước khi báo cáo 52 ngày sau. Không chọn dựa vào kết quả của giai đoạn sau.

## Market thực tế

Danh mục đã kiểm tra có BTC 5m, 15m, 1h và 4h. Chưa xác minh được market chuẩn10m/30m tương ứng. Không thể thay bằng hai lệnh15m rồi gọi là cùng một hợp đồng30m.
Market1h được kiểm tra chốt theo Binance BTC/USDT 1h, trong khi market5m/15m/4h dùng Chainlink. Phần PnL dùng nhãn Gamma resolved và CLOB winner đồng thuận, không lấy giá Lighter làm settlement.

## Kết quả giá outcome, $30/lệnh

Giá mua giả định=tham chiếu+1c, tham chiếu>=0.85, tuổi<=75s; có phí theo metadata cache. Giả định luôn đủ vốn và depth. Các bảng này chưa chứng minh khả năng khớp lệnh thật.

| Biến thể | 86 ngày trước: thắng/tổng | Win-rate | PnL | 52 ngày sau: thắng/tổng | Win-rate | PnL |
|---|---:|---:|---:|---:|---:|---:|
| Boll 30m + short phụ 30m / market 5m | 70/73 | 95.89% | $+27.52 | 28/28 | 100.00% | $+43.01 |
| Boll 30m + short phụ 60m / market 5m | 66/69 | 95.65% | $+19.36 | 23/23 | 100.00% | $+36.73 |
| Boll 5m + short phụ 15m / market 5m | 338/364 | 92.86% | $-152.02 | 114/125 | 91.20% | $-114.07 |
| Boll 30m + short phụ 30m / market 15m | 71/73 | 97.26% | $+45.23 | 34/37 | 91.89% | $-45.11 |
| Boll 30m + short phụ 60m / market 15m | 65/67 | 97.01% | $+33.72 | 32/35 | 91.43% | $-49.10 |
| Boll 5m + short phụ 15m / market 15m | 273/288 | 94.79% | $-31.44 | 124/125 | 99.20% | $+165.16 |
| Boll 1m + short phụ 15m / market 60m | 152/160 | 95.00% | $-12.10 | 48/50 | 96.00% | $+14.34 |
| Boll 1m + short phụ 60m / market 60m | 150/159 | 94.34% | $-46.02 | 48/50 | 96.00% | $+14.34 |
| Boll 5m + short phụ 15m / market 60m | 66/69 | 95.65% | $-2.77 | 23/25 | 92.00% | $-30.77 |
| Boll 1m + short phụ 30m / market 240m | 39/40 | 97.50% | $+34.91 | 13/14 | 92.86% | $-13.73 |
| Boll 1m + short phụ 60m / market 240m | 38/39 | 97.44% | $+34.05 | 13/13 | 100.00% | $+16.27 |
| Boll 5m + short phụ 15m / market 240m | 16/16 | 100.00% | $+20.13 | 6/7 | 85.71% | $-23.07 |

## Biến thể được chọn bằng giai đoạn trước

Ứng viên theo quy tắc đã định: **Boll 30m + short phụ 30m / market 15m**.
Giai đoạn sau: 34/37 thắng, PnL +1c $-45.11, +3c $-61.68.
**Ứng viên này thất bại ở giai đoạn kiểm tra sau; không đề xuất chuyển bot sang cấu hình này.** Vị trí đứng đầu ở giai đoạn trước không phải bằng chứng tốt nhất trong tương lai.

## Độ nhạy chi phí và vốn toàn kỳ

| Biến thể | Số lệnh gốc | PnL +1c | PnL +2c | PnL +3c | Ví $50 cuối kỳ* |
|---|---:|---:|---:|---:|---:|
| Boll 1m + short phụ 15m / market 60m | 210 | $+2.24 | $-53.07 | $-68.31 | $8.24 |
| Boll 1m + short phụ 30m / market 240m | 54 | $+21.18 | $+6.98 | $-4.34 | $71.18 |
| Boll 1m + short phụ 60m / market 240m | 52 | $+50.32 | $+36.41 | $+25.38 | $100.32 |
| Boll 1m + short phụ 60m / market 60m | 209 | $-31.68 | $-86.38 | $-101.00 | $8.64 |
| Boll 30m + short phụ 30m / market 15m | 110 | $+0.13 | $-29.07 | $-53.24 | $50.13 |
| Boll 30m + short phụ 30m / market 5m | 101 | $+70.53 | $+42.07 | $+17.53 | $17.34 |
| Boll 30m + short phụ 60m / market 15m | 102 | $-15.37 | $-42.18 | $-64.15 | $29.09 |
| Boll 30m + short phụ 60m / market 5m | 92 | $+56.09 | $+30.27 | $+8.19 | $12.44 |
| Boll 5m + short phụ 15m / market 15m | 413 | $+133.72 | $+18.59 | $-20.10 | $18.03 |
| Boll 5m + short phụ 15m / market 240m | 23 | $-2.94 | $-8.69 | $-12.72 | $47.06 |
| Boll 5m + short phụ 15m / market 5m | 489 | $-266.09 | $-402.34 | $-493.29 | $20.00 |
| Boll 5m + short phụ 15m / market 60m | 94 | $-33.54 | $-57.33 | $-75.75 | $20.00 |

*Mỗi biến thể dùng ví riêng$50, stake$30, giả định tiền settlement về ngay lúc hết hạn. Khi không đủ$30 thì bỏ lệnh tiếp theo. Không cộng PnL của các biến thể thành một danh mục.
Stress giữ nguyên tập cơ hội +1c; giá+2/+3c >=1 được ghi không mua với PnL0. Có thể vô tình bỏ lệnh thua; JSON báo riêng số này. Chi phí là giả định, không phải trượt giá đã đo.

## Khả năng dự đoán khi chưa lọc giá outcome

Bảng dưới là hướng giá Lighter từ đầu đến cuối market, CHƯA lọc giá tham chiếu0.85 khi vào muộn. Không so trực tiếp các tỷ lệ này với99,20% của tập lệnh đã lọc giá.

| Horizon | Khung | 86 ngày trước: n / đúng | 52 ngày sau: n / đúng |
|---|---|---:|---:|
| 5m | Boll 5m + short phụ 15m / market 5m | 1509 / 55.33% | 618 / 52.10% |
| 5m | Boll 30m + short phụ 30m / market 5m | 250 / 63.20% | 123 / 56.91% |
| 10m | Boll 5m + short phụ 15m / market 10m | 1163 / 54.60% | 468 / 51.50% |
| 10m | Boll 15m + short phụ 15m / market 10m | 530 / 59.43% | 228 / 49.12% |
| 15m | Boll 5m + short phụ 15m / market 15m | 1014 / 56.02% | 399 / 57.64% |
| 15m | Boll 30m + short phụ 60m / market 15m | 232 / 62.07% | 107 / 57.01% |
| 30m | Boll 5m + short phụ 15m / market 30m | 493 / 55.98% | 196 / 56.63% |
| 30m | Boll 10m + short phụ 60m / market 30m | 355 / 60.00% | 146 / 52.05% |
| 60m | Boll 5m + short phụ 15m / market 60m | 225 / 56.89% | 88 / 60.23% |
| 60m | Boll 1m + short phụ 60m / market 60m | 556 / 56.12% | 220 / 54.09% |
| 240m | Boll 5m + short phụ 15m / market 240m | 49 / 51.02% | 19 / 52.63% |
| 240m | Boll 1m + short phụ 60m / market 240m | 136 / 59.56% | 56 / 50.00% |

## Chất lượng bằng chứng của các ứng viên đáng chú ý

| Biến thể | Giá tham chiếu không quá 15 giây | Lệnh theo Chainlink TWAP | Khoảng bootstrap 95% PnL trung bình/lệnh |
|---|---:|---:|---:|
| Boll 5m + short phụ 15m / market 15m | 26/413 | 38/413 | $-0.30 đến $+0.85 |
| Boll 30m + short phụ 30m / market 5m | 2/101 | 9/101 | $-0.51 đến $+1.58 |
| Boll 1m + short phụ 60m / market 240m | 0/52 | 3/52 | $-0.49 đến $+1.95 |

Cả ba khoảng bootstrap đều chứa 0; đây chỉ là chẩn đoán, chưa hiệu chỉnh việc thử nhiều cấu hình. Phần lớn kết quả lịch sử là quy tắc Chainlink spot, không phải TWAP đang thấy ở market hiện tại. Đặc biệt bản 4h chỉ có 3 lệnh TWAP và không có tham chiếu nào mới trong 15 giây. Chưa đủ để kết luận phù hợp live hiện tại.

## Giới hạn và bằng chứng

Tình trạng fetch: `{'confirmed': 5086, 'not_final': 2}`. Chỉ ghi PnL khi có nhãn cuối, phí biết được và tham chiếu hợp lệ. Thiếu dữ liệu không được coi là lệnh thắng hay giả lập giá mua.
Các khung có thể có khác biệt ngày niêm yết và độ phủ dữ liệu. Số tín hiệu, lý do loại, kết quả theo tháng và theo quy tắc settlement có trong JSON để kiểm tra.
Lịch sử đã được nghiên cứu nhiều lần. Chọn trên giai đoạn trước rồi kiểm tra giai đoạn sau giảm việc nhìn trước, nhưng không biến lịch sử cũ thành holdout mới. Không có bảo đảm108 phép thử sẽ tìm ra lợi thế bền vững.
Metadata phí được đọc khi thu thập, không chứng thực mức phí tại đúng ngày lịch sử. Chưa có depth, spread và độ trễ khớp thật cho các market này. Không gồm gas, phí trung gian nạp/rút hay máy chủ.
Cấu hình paper đang chạy và Bot1 được giữ nguyên. Chỉ bổ sung code nghiên cứu.

Chạy lại: `python -B research_timeframe_expansion.py screen`, rồi `fetch`, rồi `analyze`, cuối cùng `python -B report_timeframe_expansion.py`.
Dữ liệu trong `logs/timeframe_expansion`: proxy_summary.json, selected_predictions.json, venue_summary.json, venue_trades.json và raw/. Các snapshot được cache và có SHA256; không push archive lên GitHub.

Nguồn: [danh mục Bitcoin](https://polymarket.com/crypto/bitcoin), [quy tắc1h](https://polymarket.com/event/bitcoin-up-or-down-august-30-2026-12pm-et), [quy tắc4h](https://polymarket.com/event/btc-updown-4h-1789372800), [lịch sử giá](https://docs.polymarket.com/api-reference/markets/get-prices-history).
