# Phân tích 12 lệnh thua tại 12:30

Đối chứng 410 lệnh, 398 thắng/12 thua; $20/lệnh, giá tham chiếu+1c và phí cash-equivalent. 138 ngày 19/04–03/09/2026, ngày cuối không đầy đủ. Không sửa cấu hình bot.

## Những gì dữ liệu đang gợi ý

Cả 12 lệnh thua đều đang dẫn đúng hướng theo snapshot Lighter tại T+12. 10/12 đổi sang phía thua trên Lighter lúc hết hạn; 2/12 Lighter vẫn cho phía thắng nhưng settlement Polymarket cho phía thua (08/07 và 11/08, giờ VN). Giá tham chiếu outcome cao không bảo đảm BTC không đảo chiều; khác biệt nguồn Lighter/Chainlink cũng phải được giữ nguyên khi chấm nhãn.

Khoảng cách giá tuyệt đối phân biệt kém: trung vị lead 9,11bp ở lệnh thua và 9,93bp ở lệnh thắng. Sau khi chuẩn hóa theo biến động, trung vị Z là 0,90 và 1,30. Cả 12 lệnh thua có Z<1,5; đây là mô tả trong mẫu, không có nghĩa Z>=1,5 bảo đảm thắng tương lai.

**Gate đáng thu thêm dữ liệu nhất: quiet_vol1_5.** Dùng log-return 1m đã đóng: std 5 return gần nhất / std 60 return gần nhất; bỏ lệnh nếu tỷ số >1,5 (hoặc thiếu đầu vào). Gate này đã có trong nghiên cứu Signal Extensions trước đây, là cách áp ý tưởng tránh shock vào cửa sổ settlement ngắn, không phải sao chép nguyên hàm aux_shock của Bot1. Nó bỏ lệnh thua 14/05 (ratio 1,83) và 11/08 (1,74), bỏ thêm 9 lệnh thắng. Tiết kiệm $40 thua, mất $3,77 lãi thắng, tăng ròng $36,23. Gate vẫn còn 10 lệnh thua; lợi ích hiện tại dựa vào chỉ hai trường hợp.

**Gate trực tiếp từ DCA đáng đối chiếu: memory_rsi tại tín hiệu gốc.** Chỉ main_5m: giữ điều kiện early-direction (ADX<25, DI ngược>=5, ETH 1h ngược>=30bp); hoặc trong 120 phút từng có điều kiện đó và DI/RSI hiện vẫn bất lợi. Nó tránh 5 thua nhưng bỏ 91 thắng; lãi ròng tăng $19,36, PnL sau chỉ tăng $3,18. EMA200 không loại được lệnh nào. Weak10/turn và adaptive band bỏ quá nhiều lệnh thắng ở +1c.

Bộ chọn chỉ xem 86 ngày đầu chọn early_direction_entry. Gate đó làm giai đoạn 52 ngày sau kém bản gốc $6,97. Chọn lại theo từng tháng từ dữ liệu đã kết thúc cho $90,61 so với gốc $91,09 trên cùng các tháng được chấm. Vì vậy chưa chứng minh được một quy trình chọn gate ổn định.

Khoảng bootstrap paired gain/lệnh gốc của quiet_vol là [-$0,0092; +$0,2334], của memory_rsi_signal là [-$0,1585; +$0,2828]; cả hai chứa 0 và chưa hiệu chỉnh 24 phép thử. Hướng tiếp theo là ghi shadow quyết định quiet_vol và memory_rsi theo dữ liệu nhận thực tế, giữ profile gốc làm đối chứng, rồi kiểm tra các lần skip mới. Không tự thêm gate vào live.

## Từng lệnh thua

Thời gian là giờ Việt Nam (UTC+7) tại lúc xét mua. Lead dương nghĩa giá Lighter đang đúng hướng so với mở cửa market. Lead Z chia khoảng cách theo biến động 30 phút và sqrt(3 phút còn lại từ close T+12); không phải xác suất đã hiệu chuẩn.

| Thời gian VN | Hướng / nhánh | Tuổi tín hiệu (phút) | Ref / tuổi (s) | Lead (bp) | Lead Z | Momentum 3m (bp) | Lighter cũng thua? |
|---|---|---:|---|---:|---:|---:|---|
| 20/04 13:57:30 | down / aux_short_15m | 0 | 0.965 / 38 | 3.83 | 0.40 | -3.96 | Có |
| 30/04 01:27:30 | up / main_5m | 0 | 0.915 / 23 | 13.05 | 0.48 | -2.94 | Có |
| 03/05 04:12:30 | up / main_5m | 10 | 0.958 / 26 | 2.88 | 1.05 | -2.09 | Có |
| 14/05 17:12:30 | up / main_5m | 10 | 0.925 / 26 | 10.15 | 1.44 | 16.60 | Có |
| 26/05 12:57:30 | down / main_5m | 10 | 0.865 / 26 | 2.84 | 0.64 | -4.75 | Có |
| 03/06 17:27:30 | down / main_5m | 5 | 0.935 / 25 | 12.15 | 0.95 | 7.22 | Có |
| 07/06 10:42:30 | down / main_5m | 10 | 0.965 / 27 | 13.38 | 0.99 | 5.13 | Có |
| 09/06 12:12:30 | down / main_5m | 10 | 0.955 / 26 | 13.99 | 1.21 | -2.31 | Có |
| 20/06 22:12:30 | down / aux_short_15m | 0 | 0.975 / 15 | 17.79 | 0.86 | 6.09 | Có |
| 08/07 09:27:30 | up / main_5m | 5 | 0.925 / 11 | 8.07 | 0.65 | 2.48 | Không |
| 09/07 13:42:30 | down / aux_short_15m | 0 | 0.855 / 26 | 7.29 | 0.72 | 5.83 | Có |
| 11/08 13:42:30 | up / main_5m | 0 | 0.875 / 22 | 4.63 | 1.39 | 5.12 | Không |

Toàn bộ 12 lệnh thua mất $20/lệnh trong mô phỏng. Giá BTC ở đây là Lighter, không phải feed settlement Chainlink.

## Nhánh và tuổi tín hiệu: phải so cả thắng lẫn thua

| Nhóm | Lệnh | Thua | Win-rate | PnL +1c |
|---|---:|---:|---:|---:|
| source=aux_short_15m | 68 | 3 | 95.59% | $+2.32 |
| source=main_5m | 342 | 9 | 97.37% | $+129.83 |
| side=down | 187 | 7 | 96.26% | $+40.83 |
| side=up | 223 | 5 | 97.76% | $+91.32 |
| signal_age_minutes=0.0 | 231 | 5 | 97.84% | $+123.70 |
| signal_age_minutes=10.0 | 94 | 5 | 94.68% | $-13.68 |
| signal_age_minutes=5.0 | 85 | 2 | 97.65% | $+22.13 |
| route=long | 258 | 7 | 97.29% | $+82.14 |
| route=nan | 1 | 0 | 100.00% | $+0.28 |
| route=short | 151 | 5 | 96.69% | $+49.72 |

## Toàn bộ gate, không chỉ các gate có kết quả đẹp

signal = gate lúc tín hiệu gốc; entry = gate ở nến 5m đóng T+10. Các gate cùng tên trong hai thời điểm là hai biến thể độc lập. EMA chặn quá xa phía bất lợi 200bp; above-mid chỉ nhánh short phụ, ngưỡng 60%/12h. Các gate khác giữ tham số hàm thuần Bot1. Không khẳng định các cờ này đang bật trên Bot1.

| Gate | Thắng/tổng | Thua tránh / thắng bỏ | Win-rate | PnL trước | PnL sau | PnL tổng +1c | +2c | +3c |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| original | 398/410 | 0 / 0 | 97.07% | $+56.52 | $+75.63 | $+132.15 | $+57.97 | $+18.12 |
| dca_ema200_signal | 398/410 | 0 / 0 | 97.07% | $+56.52 | $+75.63 | $+132.15 | $+57.97 | $+18.12 |
| dca_ema200_entry | 398/410 | 0 / 0 | 97.07% | $+56.52 | $+75.63 | $+132.15 | $+57.97 | $+18.12 |
| dca_adaptive_signal | 331/341 | 2 / 67 | 97.07% | $+50.49 | $+62.86 | $+113.35 | $+51.87 | $+22.82 |
| dca_adaptive_entry | 339/349 | 2 / 59 | 97.13% | $+32.50 | $+77.61 | $+110.11 | $+47.01 | $+16.33 |
| dca_weak10_turn_signal | 246/254 | 4 / 152 | 96.85% | $+38.35 | $+36.64 | $+74.99 | $+28.77 | $+11.42 |
| dca_weak10_turn_entry | 242/248 | 6 / 156 | 97.58% | $+53.77 | $+55.79 | $+109.56 | $+64.00 | $+47.12 |
| dca_early_direction_signal | 340/349 | 3 / 58 | 97.42% | $+73.79 | $+66.35 | $+140.14 | $+76.60 | $+45.08 |
| dca_early_direction_entry | 353/362 | 3 / 45 | 97.51% | $+87.30 | $+68.67 | $+155.97 | $+90.01 | $+56.53 |
| dca_memory_rsi_signal | 307/314 | 5 / 91 | 97.77% | $+72.70 | $+78.81 | $+151.51 | $+94.27 | $+67.45 |
| dca_memory_rsi_entry | 299/306 | 5 / 99 | 97.71% | $+73.02 | $+74.80 | $+147.83 | $+92.09 | $+66.41 |
| dca_aux_shock_signal | 379/390 | 1 / 19 | 97.18% | $+65.41 | $+74.29 | $+139.71 | $+68.82 | $+11.37 |
| dca_aux_shock_entry | 380/391 | 1 / 18 | 97.19% | $+65.51 | $+74.29 | $+139.80 | $+68.82 | $+11.37 |
| dca_aux_above_mid60_signal | 380/392 | 0 / 18 | 96.94% | $+39.19 | $+74.38 | $+113.57 | $+42.91 | $+5.96 |
| dca_aux_above_mid60_entry | 380/391 | 1 / 18 | 97.19% | $+59.19 | $+74.38 | $+133.57 | $+62.91 | $+5.96 |
| spot_lead_positive | 397/409 | 0 / 1 | 97.07% | $+54.79 | $+75.63 | $+130.42 | $+56.47 | $+16.83 |
| lead_z1 | 291/295 | 8 / 107 | 98.64% | $+65.18 | $+37.39 | $+102.57 | $+51.97 | $+14.90 |
| lead_z1_5 | 137/137 | 12 / 261 | 100.00% | $+32.91 | $+14.76 | $+47.67 | $+27.02 | $+15.41 |
| momentum3_positive | 253/260 | 5 / 145 | 97.31% | $+44.72 | $+34.40 | $+79.12 | $+32.80 | $+16.29 |
| token_momentum_nonnegative | 364/374 | 2 / 34 | 97.33% | $+62.40 | $+61.11 | $+123.51 | $+56.56 | $+23.37 |
| quiet_vol1_5 | 389/399 | 2 / 9 | 97.49% | $+73.31 | $+95.07 | $+168.38 | $+95.65 | $+56.67 |
| bb_reclaim | 395/407 | 0 / 3 | 97.05% | $+53.71 | $+75.54 | $+129.25 | $+55.60 | $+16.16 |
| lead_z1_and_momentum3 | 195/197 | 10 / 203 | 98.98% | $+62.24 | $+14.32 | $+76.56 | $+43.06 | $+19.01 |
| ref_at_least90 | 330/339 | 3 / 68 | 97.35% | $-24.25 | $+55.15 | $+30.90 | $-27.36 | $-51.65 |
| ref_at_most95 | 176/183 | 5 / 222 | 96.17% | $+112.63 | $+48.45 | $+161.07 | $+122.40 | $+84.56 |

## Chọn trên giai đoạn trước, kiểm tra giai đoạn sau

Quy tắc chọn: Among gates retaining >=50% and >=100 training candidates, choose highest +2c PnL gain with positive gain also at +1c; otherwise keep original. Stable ID tie-break.

Gate được chọn: **dca_early_direction_entry**.

| Tháng | Gate chọn chỉ bằng dữ liệu trước | Thắng/tổng | PnL gate | PnL gốc |
|---|---|---:|---:|---:|
| 2026-06-01 | token_momentum_nonnegative | 81/85 | $+0.95 | $+12.75 |
| 2026-07-01 | dca_early_direction_entry | 90/91 | $+71.11 | $+57.26 |
| 2026-08-01 | dca_early_direction_entry | 58/59 | $+18.56 | $+21.08 |
| 2026-09-01 | quiet_vol1_5 | 0/0 | $+0.00 | $+0.00 |

## Độ phủ dữ liệu khi gọi gate DCA

Các hàm Bot1 giữ nguyên quy ước fail-open khi thiếu/không hợp lệ: cho qua và lưu lý do. Đây không phải gate đã được kiểm chứng ở những lượt thiếu dữ liệu. Gate ngoại suy theo lead/vol chỉ giữ khi có đủ số đo cần thiết.

| Gate | Lượt thiếu/không hợp lệ, cho qua |
|---|---:|
| dca_early_direction_signal | 23 |
| dca_early_direction_entry | 20 |
| dca_memory_rsi_signal | 14 |
| dca_memory_rsi_entry | 16 |
| dca_aux_shock_signal | 1 |
| dca_aux_shock_entry | 1 |

## Giới hạn cần giữ khi diễn giải

- 12 thất bại rất ít. Nghiên cứu 24 gate, lịch sử đã khảo sát: cải thiện là giả thuyết, chưa là xác nhận ngoài mẫu. Không đặt gate riêng theo ngày/giờ của lệnh thua, không tối ưu lại ngưỡng sau khi xem bảng.
- Giá outcome là điểm lịch sử gần nhất trước quyết định, tối đa 75s; chỉ 34/410 điểm mới trong 15s. Thiếu historical asks/depth và actual fills. +1/2/3c là giả định, phí cache không chứng minh đúng phí tại ngày giao dịch.
- Stress +2/+3c giữ 410 ứng viên; giá>=1 ghi nonfill, có thể loại cả lệnh vốn sẽ thua. Không coi win-rate tăng do nonfill là tín hiệu tốt hơn.
- Dữ liệu 1m chỉ biết close T+12; 30 giây trước quyết định chưa quan sát được. Không dùng close T+13 hoặc T+15 để lọc. Cột Lighter cuối market chỉ để chẩn đoán khác nguồn settlement.
- Bootstrap trong JSON là paired delta theo block 3 ngày, có ngày không giao dịch, chưa hiệu chỉnh nhiều phép thử. Ví $50 ghi nhận redemption giả định ngay hết hạn; gas/nạp-rút/vận hành chưa tính.
- Không sao chép TP/trailing/nhồi DCA vì quyền chọn hết hạn cố định có payout khác. Gate tương quan ETH-BTC dành riêng ETH không áp vào BTC.

Tái chạy: `python -B research_loss_gates_1230.py`. Chi tiết JSON: `logs/loss_gates_1230/summary.json`, `candidates.json`, `losses.json`, `protocol.json`.
