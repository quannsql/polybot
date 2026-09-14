# Nghiên cứu phối hợp gate 12:30 — giai đoạn 2

Đã thử 57 biến thể + đối chứng trên cùng 410 lệnh. $20/lệnh, giữ Boll gốc và 12:30. Lưới được xây dựng sau khi đã xem 12 lệnh thua, nên mọi kết quả là thăm dò trên lịch sử đã biết.

Gate chọn bằng 86 ngày trước: `q1.75_z1.25_memory_old_signal_aux_shock`. Gate PnL cao nhất khi nhìn cả mẫu: `q1.5_z1.25_memory_old_signal_aux_shock`. Gate cân bằng trong mẫu (giữ>=50%, win>=98%, tăng PnL cả hai giai đoạn ở +1c/+2c): `q1.5_z0.75_memory_old_signal_aux_shock`.

## Diễn giải các ứng viên chính

Hướng thực dụng để tiếp tục thử là `q1.5_z1_memory`: chỉ hai điều kiện bổ sung. Đây là lựa chọn đánh giá thủ công sau khi xem bảng, ưu tiên đơn giản và giữ nhiều cơ hội, không phải gate đã được selector chọn trước khi biết kết quả.

1. Bỏ nếu std log-return1m của 5 phút / 60 phút >1,5.
2. Với nhánh main_5m, nếu Memory RSI ở tín hiệu gốc báo bất lợi, chỉ bỏ khi lead Z tại close T+12 <1. Nếu Memory RSI báo bất lợi nhưng giá đã đi đủ xa đúng hướng (Z>=1), cho đi tiếp. Lead Z = signed log(close T+12/open T) / [std30(log-return1m) × sqrt(3)].

Memory RSI là gate thuần của DCA: giữ cảnh báo early-direction gốc hoặc cảnh báo trong 120 phút khi DI/RSI vẫn bất lợi. Gate này áp riêng nhánh main, không thay hướng DCA đã chọn. Ý nghĩa là tránh loại máy móc một cơ hội mà giá đã hồi đúng hướng đủ xa.

| Ứng viên | Thắng/tổng | Win-rate | Tránh thua / bỏ thắng | PnL +1c | PnL/lệnh |
|---|---:|---:|---:|---:|---:|
| original | 398/410 | 97.07% | 0 / 0 | $+132.15 | $+0.322 |
| quiet_1.5 | 389/399 | 97.49% | 2 / 9 | $+168.38 | $+0.422 |
| q1.5_z1_memory | 365/372 | 98.12% | 5 / 33 | $+188.45 | $+0.507 |
| q1.5_z0.75_memory_old_signal_aux_shock | 356/363 | 98.07% | 5 / 42 | $+189.74 | $+0.523 |
| q1.5_z1.25_memory_old_signal_aux_shock | 297/300 | 99.00% | 9 / 101 | $+191.47 | $+0.638 |
| lead_1.5 | 137/137 | 100.00% | 12 / 261 | $+47.67 | $+0.348 |

Gate đơn giản tiết kiệm $100.00 thua nhưng bỏ $43.70 lãi thắng; tăng ròng $56.30. PnL trước/sau: $+103.28 / $+85.18.

Gate PnL cao nhất trong toàn mẫu còn 3 thua. Nó thêm điều kiện tuổi tín hiệu>=10 phút và aux shock, dùng Z<1,25 cho memory/tuổi tín hiệu. Giai đoạn sau đạt $+73.25, thấp hơn gốc $+75.63. Vì vậy PnL toàn mẫu cao nhất không đồng nghĩa cấu hình đáng tin nhất.

## Lân cận ngưỡng của ứng viên đơn giản

| Cap biến động / Z | Lệnh | Thua | PnL trước | PnL sau | Tổng +1c |
|---|---:|---:|---:|---:|---:|
| q1.25_z1_memory | 351 | 7 | $+82.92 | $+82.97 | $+165.89 |
| q1.5_z1_memory | 372 | 7 | $+103.28 | $+85.18 | $+188.45 |
| q1.75_z1_memory | 379 | 8 | $+104.62 | $+65.74 | $+170.37 |
| q1.5_z0.75_memory | 390 | 9 | $+85.31 | $+90.70 | $+176.00 |
| q1.5_z1.25_memory | 354 | 7 | $+85.73 | $+82.93 | $+168.66 |

Khi vol cap=1,75, lệnh thua 11/08 với ratio~1,736 không bị chặn nữa. Các ngưỡng xung quanh vẫn tăng tổng PnL trong mẫu, nhưng cải thiện giai đoạn sau không đồng đều. Không tối ưu thành ngưỡng khớp riêng từng lệnh thua.

## Bảng đầy đủ

| Quy tắc | Thắng/tổng | Tránh thua / bỏ thắng | Win-rate | PnL trước | PnL sau | Tổng +1c | +2c | +3c |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| original | 398/410 | 0/0 | 97.07% | $+56.52 | $+75.63 | $+132.15 | $+57.97 | $+18.12 |
| quiet_1.25 | 368/378 | 2/30 | 97.35% | $+52.96 | $+92.86 | $+145.82 | $+77.17 | $+41.79 |
| quiet_1.5 | 389/399 | 2/9 | 97.49% | $+73.31 | $+95.07 | $+168.38 | $+95.65 | $+56.67 |
| quiet_1.75 | 395/406 | 1/3 | 97.29% | $+74.66 | $+75.63 | $+150.30 | $+76.61 | $+37.15 |
| veto_memory | 307/314 | 5/91 | 97.77% | $+72.70 | $+78.81 | $+151.51 | $+94.27 | $+67.45 |
| veto_early | 353/362 | 3/45 | 97.51% | $+87.30 | $+68.67 | $+155.97 | $+90.01 | $+56.53 |
| veto_aux_shock | 380/391 | 1/18 | 97.19% | $+65.51 | $+74.29 | $+139.80 | $+68.82 | $+11.37 |
| veto_old_signal | 309/316 | 5/89 | 97.78% | $+89.47 | $+56.37 | $+145.83 | $+88.35 | $+62.38 |
| veto_weak | 242/248 | 6/156 | 97.58% | $+53.77 | $+55.79 | $+109.56 | $+64.00 | $+47.12 |
| lead_0.75 | 358/365 | 5/40 | 98.08% | $+100.54 | $+56.72 | $+157.26 | $+92.02 | $+60.81 |
| lead_1 | 291/295 | 8/107 | 98.64% | $+65.18 | $+37.39 | $+102.57 | $+51.97 | $+14.90 |
| lead_1.25 | 211/213 | 10/187 | 99.06% | $+48.04 | $+13.68 | $+61.73 | $+27.19 | $+4.61 |
| lead_1.5 | 137/137 | 12/261 | 100.00% | $+32.91 | $+14.76 | $+47.67 | $+27.02 | $+15.41 |
| memory_if_zlt0.75 | 390/401 | 1/8 | 97.26% | $+68.51 | $+71.26 | $+139.77 | $+67.32 | $+29.16 |
| early_if_zlt0.75 | 394/405 | 1/4 | 97.28% | $+72.84 | $+73.68 | $+146.52 | $+73.19 | $+34.17 |
| old_signal_if_zlt0.75 | 389/400 | 1/9 | 97.25% | $+65.50 | $+69.03 | $+134.53 | $+62.38 | $+24.51 |
| weak_if_zlt0.75 | 386/396 | 2/12 | 97.47% | $+80.71 | $+68.96 | $+149.67 | $+78.17 | $+40.94 |
| memory_if_zlt1 | 374/383 | 3/24 | 97.65% | $+86.48 | $+65.74 | $+152.22 | $+83.20 | $+48.31 |
| early_if_zlt1 | 388/398 | 2/10 | 97.49% | $+80.70 | $+73.01 | $+153.70 | $+81.75 | $+44.08 |
| old_signal_if_zlt1 | 374/384 | 2/24 | 97.40% | $+59.95 | $+69.03 | $+128.97 | $+60.12 | $+25.47 |
| weak_if_zlt1 | 355/364 | 3/43 | 97.53% | $+64.04 | $+56.23 | $+120.27 | $+55.42 | $+24.60 |
| memory_if_zlt1.25 | 355/364 | 3/43 | 97.53% | $+68.45 | $+63.50 | $+131.95 | $+66.76 | $+35.42 |
| early_if_zlt1.25 | 376/386 | 2/22 | 97.41% | $+73.05 | $+70.83 | $+143.88 | $+74.30 | $+38.71 |
| old_signal_if_zlt1.25 | 354/362 | 4/44 | 97.79% | $+83.16 | $+63.79 | $+146.96 | $+82.24 | $+51.36 |
| weak_if_zlt1.25 | 319/327 | 4/79 | 97.55% | $+56.61 | $+45.82 | $+102.43 | $+44.80 | $+20.50 |
| q1.25_z0.75_memory | 360/369 | 3/38 | 97.56% | $+64.95 | $+88.48 | $+153.44 | $+86.52 | $+52.83 |
| q1.25_z0.75_memory_old_signal | 353/361 | 4/45 | 97.78% | $+75.23 | $+84.29 | $+159.53 | $+94.19 | $+62.05 |
| q1.25_z0.75_memory_old_signal_aux_shock | 335/342 | 5/63 | 97.95% | $+84.22 | $+82.95 | $+167.18 | $+105.04 | $+55.30 |
| q1.25_z1_memory | 344/351 | 5/54 | 98.01% | $+82.92 | $+82.97 | $+165.89 | $+102.40 | $+71.98 |
| q1.25_z1_memory_old_signal | 327/333 | 6/71 | 98.20% | $+76.87 | $+78.78 | $+155.65 | $+95.92 | $+69.18 |
| q1.25_z1_memory_old_signal_aux_shock | 309/314 | 7/89 | 98.41% | $+85.86 | $+77.44 | $+163.30 | $+106.77 | $+62.43 |
| q1.25_z1.25_memory | 327/334 | 5/71 | 97.90% | $+67.10 | $+80.72 | $+147.83 | $+87.75 | $+60.48 |
| q1.25_z1.25_memory_old_signal | 298/302 | 8/100 | 98.68% | $+91.56 | $+73.26 | $+164.82 | $+110.98 | $+89.63 |
| q1.25_z1.25_memory_old_signal_aux_shock | 280/283 | 9/118 | 98.94% | $+100.55 | $+71.92 | $+172.47 | $+121.83 | $+82.88 |
| q1.5_z0.75_memory | 381/390 | 3/17 | 97.69% | $+85.31 | $+90.70 | $+176.00 | $+105.00 | $+67.71 |
| q1.5_z0.75_memory_old_signal | 374/382 | 4/24 | 97.91% | $+95.58 | $+86.51 | $+182.09 | $+112.67 | $+76.93 |
| q1.5_z0.75_memory_old_signal_aux_shock | 356/363 | 5/42 | 98.07% | $+104.57 | $+85.17 | $+189.74 | $+123.52 | $+70.18 |
| q1.5_z1_memory | 365/372 | 5/33 | 98.12% | $+103.28 | $+85.18 | $+188.45 | $+120.88 | $+86.86 |
| q1.5_z1_memory_old_signal | 348/354 | 6/50 | 98.31% | $+97.22 | $+80.99 | $+178.21 | $+114.40 | $+84.06 |
| q1.5_z1_memory_old_signal_aux_shock | 330/335 | 7/68 | 98.51% | $+106.21 | $+79.65 | $+185.86 | $+125.25 | $+77.31 |
| q1.5_z1.25_memory | 347/354 | 5/51 | 98.02% | $+85.73 | $+82.93 | $+168.66 | $+104.72 | $+74.07 |
| q1.5_z1.25_memory_old_signal | 315/319 | 8/83 | 98.75% | $+109.23 | $+74.59 | $+183.82 | $+126.71 | $+102.45 |
| q1.5_z1.25_memory_old_signal_aux_shock | 297/300 | 9/101 | 99.00% | $+118.22 | $+73.25 | $+191.47 | $+137.55 | $+95.71 |
| q1.75_z0.75_memory | 387/397 | 2/11 | 97.48% | $+86.65 | $+71.26 | $+157.91 | $+85.96 | $+48.19 |
| q1.75_z0.75_memory_old_signal | 380/389 | 3/18 | 97.69% | $+96.93 | $+67.07 | $+164.00 | $+93.63 | $+57.41 |
| q1.75_z0.75_memory_old_signal_aux_shock | 362/370 | 4/36 | 97.84% | $+105.92 | $+65.73 | $+171.65 | $+104.47 | $+50.66 |
| q1.75_z1_memory | 371/379 | 4/27 | 97.89% | $+104.62 | $+65.74 | $+170.37 | $+101.84 | $+67.34 |
| q1.75_z1_memory_old_signal | 354/361 | 5/44 | 98.06% | $+98.57 | $+61.55 | $+160.12 | $+95.36 | $+64.54 |
| q1.75_z1_memory_old_signal_aux_shock | 336/342 | 6/62 | 98.25% | $+107.56 | $+60.21 | $+167.77 | $+106.21 | $+57.79 |
| q1.75_z1.25_memory | 353/361 | 4/45 | 97.78% | $+87.07 | $+63.50 | $+150.58 | $+85.68 | $+54.55 |
| q1.75_z1.25_memory_old_signal | 321/326 | 7/77 | 98.47% | $+110.58 | $+55.16 | $+165.73 | $+107.66 | $+82.93 |
| q1.75_z1.25_memory_old_signal_aux_shock | 303/307 | 8/95 | 98.70% | $+119.57 | $+53.82 | $+173.38 | $+118.51 | $+76.18 |
| q1.5_veto_memory | 302/309 | 5/96 | 97.73% | $+70.06 | $+78.81 | $+148.88 | $+92.41 | $+66.09 |
| q1.5_veto_early | 346/354 | 4/52 | 97.74% | $+84.67 | $+88.10 | $+172.77 | $+107.97 | $+75.18 |
| q1.5_veto_aux_shock | 371/380 | 3/27 | 97.63% | $+82.31 | $+93.73 | $+176.03 | $+106.50 | $+49.92 |
| q1.5_z0.75_memory_old_weak | 368/375 | 5/30 | 98.13% | $+104.97 | $+84.21 | $+189.18 | $+121.13 | $+86.74 |
| q1.5_z1_memory_old_weak | 329/334 | 7/69 | 98.50% | $+92.74 | $+71.48 | $+164.21 | $+104.62 | $+78.39 |
| q1.5_z1.25_memory_old_weak | 282/285 | 9/116 | 98.95% | $+96.30 | $+60.19 | $+156.49 | $+106.34 | $+88.63 |

q=vol cap; z=lead threshold dùng khi cờ DCA/tuổi tín hiệu bất lợi. memory đọc tại tín hiệu gốc; early/weak/aux_shock ở nến đóng T+10; old_signal=tuổi>=10 phút. Gate có blocks chỉ veto khi cờ bật VÀ Z dưới ngưỡng; aux_shock veto không phụ thuộc Z. vol luôn kiểm tra ở close1m cuối biết được T+12. Chi tiết công thức: protocol.json.

## Quy trình chọn theo thời gian

| Tháng kiểm tra | Gate chọn bằng dữ liệu cũ | PnL | PnL gốc |
|---|---|---:|---:|
| 2026-06-01 | q1.5_z0.75_memory_old_weak | $+10.06 | $+12.75 |
| 2026-07-01 | q1.75_z1.25_memory_old_signal_aux_shock | $+53.14 | $+57.26 |
| 2026-08-01 | q1.75_z0.75_memory_old_signal_aux_shock | $+13.24 | $+21.08 |
| 2026-09-01 | q1.5_z1.25_memory_old_signal_aux_shock | $+0.00 | $+0.00 |

Tổng walk-forward: $+76.44; đối chứng cùng tháng $+91.09. Đây là chấm theo thời gian trên một họ gate đã biết lịch sử; không phải bằng chứng triển khai ngoài mẫu.

## Độ nhạy và vốn $50

| Gate | PnL +1c | Feature cũ thêm 1m / 2m | Ví50 cuối (trả tiền ngay hết hạn) | CI95 paired gain/lệnh gốc | p họ gate xấp xỉ |
|---|---:|---:|---:|---:|---:|
| original | $+132.15 | $+132.15 / $+132.15 | $182.15 | [+0.000;+0.000] | 1.000 |
| quiet_1.5 | $+168.38 | $+146.78 / $+140.80 | $218.38 | [-0.009;+0.233] | 0.589 |
| q1.5_z0.75_memory_old_signal_aux_shock | $+189.74 | $+178.57 / $+117.19 | $239.74 | [-0.044;+0.349] | 0.570 |
| q1.5_z1_memory | $+188.45 | $+155.61 / $+154.10 | $238.45 | [-0.051;+0.356] | 0.600 |
| q1.5_z1.25_memory_old_signal_aux_shock | $+191.47 | $+179.71 / $+116.53 | $241.47 | [-0.110;+0.419] | 0.720 |
| q1.75_z1.25_memory_old_signal_aux_shock | $+173.38 | $+182.36 / $+124.30 | $223.38 | [-0.139;+0.370] | 0.861 |

Thay độ mới feature không phải thay thời điểm khớp. Dữ liệu giá/book thật ở 12:30 chưa có trong archive. p được tính bằng centered max-t trên block3 ngày cho họ gate lần này; không sửa được việc dữ liệu đã được xem nhiều lần. CI và p chỉ chẩn đoán, không phải chứng nhận lợi nhuận.

## Bỏ từng lệnh thua khỏi training rồi chọn lại

- `q1.75_z1.25_memory_old_signal_aux_shock`: 3/11 lần.
- `q1.75_z1_memory_old_signal_aux_shock`: 2/11 lần.
- `lead_0.75`: 1/11 lần.
- `q1.75_z1_memory`: 1/11 lần.
- `q1.75_z0.75_memory_old_signal_aux_shock`: 3/11 lần.
- `q1.75_z1.25_memory_old_signal`: 1/11 lần.

## Giới hạn

- Không thay nguyên tắc cố định hướng Boll, không chọn gate theo ngày hoặc slug. Mọi phép loại đều chấm cả thắng bị bỏ và thua tránh được.
- Pad1/2/3c và phí cash-equivalent cache là giả định. Không có historical depth/ask thực thi; giá>=1 là nonfill có ghi rõ, giữ tập ứng viên cố định. Gas/vận hành/nạp-rút chưa tính.
- Một vài gate DCA thiếu dữ liệu peer/indicator thì giữ cơ chế cho qua của Bot1; JSON ghi chẩn đoán. Các kiểm tra Z/vol thiếu số liệu thì không cấp phép dựa trên số liệu đó.
- Các nhãn theo settlement cache Polymarket. Nguồn tín hiệu Lighter không luôn trùng Chainlink.
- Ví50 giả định redemption0/5/30 phút sau hết hạn; không suy ra timing on-chain đã được đo.
- Không đổi config live/paper, không deploy. Scripts và artifacts chỉ nằm trong polybot.

Tái chạy: `python -B research_gate_combinations_1230.py`. JSON: `logs/gate_combinations_1230/{summary,candidates,protocol}.json`.
