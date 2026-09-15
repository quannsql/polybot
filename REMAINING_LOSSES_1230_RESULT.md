# Ba lệnh thua còn lại: bộ lọc bổ sung ở 12:30

Giữ ngưỡng 0,85; DCA gốc + strong gate đã chọn; $20/lệnh. Đối chứng tái hiện 297 thắng/300 lệnh, PnL +$191,47. Chỉ nghiên cứu, chưa thay bot live.

Dữ liệu 19/04–03/09/2026 (138 ngày lịch; ngày cuối không đầy đủ). Cả ba lệnh thua đều ở giai đoạn trước; giai đoạn sau là 97/97 thắng. Mọi thử nghiệm ở đây đều dùng lại dữ liệu đã biết, không có holdout mới.

## Các lệnh thua

| Mốc mua giờ Việt Nam | Nhánh | Hướng | Giá tham chiếu | Z | Momentum 3m (bps log) | Tuổi giá (s) |
|---|---|---|---:|---:|---:|---:|
| 20/04/2026 13:57:30 | aux_short_15m | down | 0.965 | 0.403 | -3.962 | 38 |
| 30/04/2026 01:27:30 | main_5m | up | 0.915 | 0.483 | -2.936 | 23 |
| 09/07/2026 13:42:30 | aux_short_15m | down | 0.855 | 0.723 | +5.832 | 26 |

Z đo khoảng cách giá BTC theo hướng dự đoán so với biến động 30 phút, tính bằng nến đã đóng đến T+12. Z không phải xác suất thắng được hiệu chuẩn. Cả ba có khoảng dẫn dương rồi đảo chiều; dữ liệu cuối market chỉ dùng giải thích hậu nghiệm.


## Hai ứng viên đáng theo dõi

**A — `adverse_momentum_z0.5`: bỏ khi momentum 3m ngược hướng VÀ Z<0,5.** Momentum dùng signed log(close T+12 / close T+9), dấu dương là đi đúng hướng đã chọn. Không yêu cầu mọi lệnh phải có momentum dương. Z dùng sigma log-return 30 phút × sqrt(3).

**B — `against_slope_z0.75`: bỏ khi độ dốc đường giữa Bollinger 15m không cùng hướng VÀ Z<0,75.** Độ dốc là SMA20 của nến 15m đã đóng trừ giá trị của chính SMA đó 4 nến trước (60 phút). Không dùng nến 15m đang chạy; độ dốc 0 hoặc dữ liệu band không hợp lệ cũng không xác nhận cùng hướng.

| Đối chứng/ứng viên | Thắng/tổng | PnL +1c | PnL giai đoạn sau | Bỏ lãi thắng để tránh thua | PnL nếu thêm 1 thua* |
|---|---:|---:|---:|---:|---:|
| current | 297/300 | $+191.47 | $+73.25 | $0.00 | $+168.57 |
| adverse_momentum_z0.5 | 296/297 | $+229.96 | $+73.25 | $1.51 | $+207.06 |
| against_slope_z0.75 | 281/281 | $+218.90 | $+65.80 | $32.57 | $+196.00 |
| all_z0.75 | 273/273 | $+204.60 | $+62.90 | $46.87 | $+181.82 |

*Stress đổi lệnh thắng có payout lớn nhất thành thua trên tập giữ lại; không thêm cơ hội mới.

A tránh $40 tiền thua, bỏ $1,51 lãi của một lệnh thắng trong tháng 5; tăng ròng $38,49. 97/97 lệnh của giai đoạn sau đều giữ nguyên nên chưa có ví dụ giai đoạn sau để kiểm chứng tác dụng loại lệnh của A. B tránh $60 tiền thua nhưng bỏ $32,57 lãi thắng, tăng ròng $27,43. PnL giai đoạn sau giảm $7,45 (~10,2%).

Các gate DCA áp cứng không đạt đánh đổi tốt bằng A: adaptive_entry còn 2 thua, PnL $167,68; weak10_turn_entry còn 2 thua, PnL $131,92. Chúng loại được lệnh long ngày 30/04 nhưng loại nhiều lệnh thắng hơn.

## Độ nhạy và bằng chứng còn thiếu

| Ứng viên | Dữ liệu đúng T+12 | Cũ 1 phút: lệnh/thua/PnL | Cũ 2 phút: lệnh/thua/PnL | Khoảng 95% phần PnL tăng thêm |
|---|---:|---:|---:|---|
| adverse_momentum_z0.5 | $+229.96 | 286/3/$+163.98 | 272/3/$+154.91 | $-3.02..$+100.00 |
| against_slope_z0.75 | $+218.90 | 261/1/$+177.47 | 227/1/$+146.09 | $-34.30..$+109.02 |

Phép dữ liệu cũ chỉ thay Z/momentum/slope của gate mới; tập nền, gate DCA và giá mua giữ nguyên. Đây là độ nhạy thời điểm quan sát, không phải ước tính trượt giá mạng.

Ngưỡng lân cận cũng cho thấy đánh đổi: A với Z<0,75 còn 1 thua nhưng PnL giảm còn $211,78; Z<1 còn $176,76. B với Z<0,5 giữ 1 thua và PnL $223,28; Z<1 hết thua nhưng PnL còn $176,63. Không nên chọn riêng mức 0,75 chỉ vì nó nằm ngay trên Z=0,723 của lệnh thua cuối.

Cả hai khoảng bootstrap đều chứa 0. Family max-t p xấp xỉ 0,485 (A) / 0,918 (B); không đủ bằng chứng thống kê về lợi thế bền vững. Bỏ lần lượt từng lệnh thua: selector đổi khỏi A khi bỏ lệnh long tháng 4, cho thấy lựa chọn phụ thuộc vào vài trường hợp.

Tôi ưu tiên A làm ứng viên xác nhận tiếp theo vì chỉ bỏ 3 cơ hội trong 300 và PnL mẫu cao nhất. B phục vụ mục tiêu ưu tiên ít thua hơn, nhưng 281/281 thắng là kết quả trong mẫu đã xem. Nếu triển khai sau này, cần có dữ liệu đúng T+12; không tự thay bằng nến cũ hơn. Hiện không sửa cấu hình, không push, không deploy và không gọi executor.

Đã tái tính 300/300 mẫu từ nến nguồn, đối chiếu Z/momentum/slope/volatility, giá tham chiếu, nhãn settlement và PnL +1/+2/+3c; tất cả khớp.

## Toàn bộ lưới cố định

41 biến thể bổ sung; selector dùng giai đoạn trước chọn `adverse_momentum_z0.5`. Selector và lưới được xây sau khi xem các lệnh thua nên không được xem là kiểm chứng độc lập.

| Bộ lọc thêm | Thắng/tổng | Bỏ thắng/thua | PnL trước | PnL sau | Tổng +1c | Tổng +2c | Tổng +3c |
|---|---:|---:|---:|---:|---:|---:|---:|
| current | 297/300 | 0/0 | $+118.22 | $+73.25 | $+191.47 | $+137.55 | $+95.71 |
| all_z0.5 | 292/293 | 5/2 | $+148.48 | $+72.38 | $+220.86 | $+168.08 | $+127.36 |
| aux_z0.5 | 296/298 | 1/1 | $+135.31 | $+73.25 | $+208.57 | $+154.89 | $+113.29 |
| adverse_momentum_z0.5 | 296/297 | 1/2 | $+156.71 | $+73.25 | $+229.96 | $+176.26 | $+134.62 |
| against_slope_z0.5 | 293/294 | 4/2 | $+150.90 | $+72.38 | $+223.28 | $+170.27 | $+129.31 |
| all_z0.75 | 273/273 | 24/3 | $+141.70 | $+62.90 | $+204.60 | $+156.09 | $+119.44 |
| aux_z0.75 | 288/289 | 9/2 | $+142.24 | $+69.27 | $+211.51 | $+159.67 | $+119.85 |
| adverse_momentum_z0.75 | 287/288 | 10/2 | $+141.43 | $+70.35 | $+211.78 | $+160.12 | $+120.48 |
| against_slope_z0.75 | 281/281 | 16/3 | $+153.10 | $+65.80 | $+218.90 | $+168.62 | $+130.23 |
| all_z1 | 236/236 | 61/3 | $+91.01 | $+49.09 | $+140.10 | $+99.74 | $+70.98 |
| aux_z1 | 279/280 | 18/2 | $+126.05 | $+68.59 | $+194.64 | $+144.81 | $+106.96 |
| adverse_momentum_z1 | 269/270 | 28/2 | $+113.50 | $+63.27 | $+176.76 | $+129.15 | $+93.37 |
| against_slope_z1 | 256/256 | 41/3 | $+117.88 | $+58.75 | $+176.63 | $+131.83 | $+98.81 |
| all_z1.25 | 194/194 | 103/3 | $+63.30 | $+32.35 | $+95.65 | $+63.81 | $+42.77 |
| aux_z1.25 | 272/273 | 25/2 | $+122.54 | $+65.45 | $+187.99 | $+139.59 | $+103.13 |
| adverse_momentum_z1.25 | 249/250 | 48/2 | $+102.58 | $+52.08 | $+154.66 | $+111.13 | $+79.04 |
| against_slope_z1.25 | 235/235 | 62/3 | $+102.19 | $+50.31 | $+152.51 | $+112.07 | $+83.23 |
| dca_adaptive_signal | 255/257 | 42/1 | $+117.28 | $+65.55 | $+182.83 | $+136.38 | $+100.50 |
| dca_adaptive_entry | 252/254 | 45/1 | $+107.44 | $+60.24 | $+167.68 | $+121.98 | $+86.68 |
| dca_weak10_turn_signal | 195/197 | 102/1 | $+87.88 | $+49.95 | $+137.83 | $+101.62 | $+72.90 |
| dca_weak10_turn_entry | 190/192 | 107/1 | $+82.82 | $+49.10 | $+131.92 | $+96.57 | $+68.50 |
| dca_early_direction_signal | 267/270 | 30/0 | $+105.40 | $+70.46 | $+175.86 | $+126.86 | $+88.11 |
| dca_early_direction_entry | 273/276 | 24/0 | $+111.48 | $+70.95 | $+182.43 | $+132.39 | $+92.85 |
| dca_memory_rsi_signal | 252/255 | 45/0 | $+102.55 | $+69.13 | $+171.69 | $+125.25 | $+87.73 |
| dca_memory_rsi_entry | 243/246 | 54/0 | $+97.45 | $+67.29 | $+164.75 | $+120.06 | $+83.94 |
| dca_aux_above_mid60_signal | 286/289 | 11/0 | $+106.25 | $+72.29 | $+178.55 | $+126.83 | $+86.77 |
| dca_aux_above_mid60_entry | 286/289 | 11/0 | $+106.25 | $+72.29 | $+178.55 | $+126.83 | $+86.77 |
| momentum_positive | 191/192 | 106/2 | $+82.00 | $+42.54 | $+124.54 | $+90.71 | $+65.34 |
| slope_agrees | 113/113 | 184/3 | $+64.91 | $+29.68 | $+94.59 | $+74.04 | $+58.23 |
| token_momentum_nonnegative | 269/272 | 28/0 | $+92.48 | $+60.68 | $+153.16 | $+105.15 | $+68.67 |
| giveback_max0.25 | 182/183 | 115/2 | $+59.15 | $+35.47 | $+94.62 | $+63.64 | $+41.86 |
| giveback_max0.5 | 277/279 | 20/1 | $+113.92 | $+65.41 | $+179.33 | $+129.77 | $+92.10 |
| giveback_max0.75 | 297/300 | 0/0 | $+118.22 | $+73.25 | $+191.47 | $+137.55 | $+95.71 |
| quote_age_max15 | 21/21 | 276/3 | $+12.06 | $+5.49 | $+17.55 | $+13.59 | $+10.37 |
| quote_age_max30 | 290/292 | 7/1 | $+134.88 | $+73.25 | $+208.13 | $+155.39 | $+114.32 |
| quote_age_max45 | 295/298 | 2/0 | $+117.46 | $+73.25 | $+190.71 | $+137.18 | $+95.61 |
| aux_z0.5_plus_dca_adaptive_entry | 251/252 | 46/2 | $+124.54 | $+60.24 | $+184.78 | $+139.32 | $+104.27 |
| aux_z0.5_plus_dca_weak10_turn_entry | 189/190 | 108/2 | $+99.92 | $+49.10 | $+149.02 | $+113.91 | $+86.08 |
| aux_z0.75_plus_dca_adaptive_entry | 243/243 | 54/3 | $+131.47 | $+56.25 | $+187.72 | $+144.10 | $+110.83 |
| aux_z0.75_plus_dca_weak10_turn_entry | 181/181 | 116/3 | $+106.85 | $+45.11 | $+151.96 | $+118.69 | $+92.65 |
| aux_z1_plus_dca_adaptive_entry | 234/234 | 63/3 | $+115.27 | $+55.58 | $+170.85 | $+129.24 | $+97.94 |
| aux_z1_plus_dca_weak10_turn_entry | 172/172 | 125/3 | $+90.66 | $+44.43 | $+135.09 | $+103.83 | $+79.76 |

## Giới hạn và cách đọc

- PnL tổng giả định có đủ vốn và khớp ở giá tham chiếu + padding, phí cash-equivalent nằm trong $20. Sổ lệnh, spread, độ trễ và giá khớp lịch sử chưa được xác minh; chưa trừ gas/máy chủ/nạp rút.
- Stress +2/+3c giữ nguyên tập 300 cơ hội: giá >=1 được coi không khớp (PnL 0), JSON ghi riêng số nonfill. Đây không phải bằng chứng lệnh FOK với trần +1c sẽ khớp ở +2c.
- Chỉ 21/300 giá tham chiếu mới trong 15 giây. Gate quote_age là điều kiện chất lượng dữ liệu; không được diễn giải như một tín hiệu thị trường loại thua.
- Tất cả kết quả theo nhãn settlement Polymarket đã lưu. Chỉ báo dùng Lighter, không phải Chainlink. Quy tắc spot/TWAP và các giá trị phí trong cache có thể khác market hiện tại.
- Bootstrap khối 3 ngày và family max-t chỉ là chẩn đoán trong lưới này, không sửa được việc thử nhiều vòng trước.
- Chi tiết JSON gồm PnL từng tháng, wallet50 với trì hoãn redemption 0/300/1800s, stress một lệnh thắng thành thua, bỏ từng lệnh thua và chọn lại trên phần trước.
- API lịch sử giá và sổ lệnh là nguồn khác nhau: [Polymarket prices-history](https://docs.polymarket.com/api-reference/markets/get-prices-history), [Polymarket order book](https://docs.polymarket.com/api-reference/market-data/get-order-book).

Chạy lại: `python -B research_remaining_losses_1230.py`. Chi tiết: `logs/remaining_losses_1230/summary.json`.
