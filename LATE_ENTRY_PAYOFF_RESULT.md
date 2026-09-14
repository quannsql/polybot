# Bản gốc 15m: chờ thêm có đủ lãi bù lỗ?

Giữ nguyên hướng DCA/Boll chính 5m và short phụ 15m đã chọn ở đầu market; chỉ đổi thời gian mua. Ngưỡng tham chiếu >=0.85, giá tham chiếu không quá 75 giây, $30/lệnh gồm phí cash-equivalent. Không tính lại hướng trước khi mua. Mọi mốc đều settlement ở phút 15.

86 ngày trước: 19/04–13/07/2026; 52 ngày sau: 14/07–03/09/2026 (ngày cuối dữ liệu không đầy đủ). Lịch sử đã được xem nhiều lần; không phải holdout mới.

## Kết luận trên tập dữ liệu này

12:30 có PnL +1c toàn kỳ cao nhất trong 8 mốc thử, không phải cấu hình đã chứng minh tối ưu cho tương lai. Có 398 lệnh thắng và 12 lệnh thua: tổng lãi các lệnh thắng $558.22 trừ $360 lỗ = $198.22. Lãi bình quân lệnh thắng $1.403; cần khoảng 22 lệnh thắng như mức trung bình này để bù một lệnh thua $30. Tỷ lệ hòa vốn tính từ mức lãi thắng quan sát là 95.53%, so với tỷ lệ thắng mẫu 97.07%.

Ở +2c, 12:30 còn lãi $86.96 toàn kỳ, trong đó giai đoạn trước chỉ +$6.58. Ở +3c, toàn kỳ +$27.18 nhưng giai đoạn trước lỗ $27.69; 145 cơ hội không mua vì giá >=1, gồm 1 lệnh vốn sẽ thua. Chỉ 34/410 tham chiếu mới trong 15 giây; khoảng bootstrap PnL trung bình vẫn chứa 0. Do đó chưa đủ bằng chứng để xác nhận khả năng bù chi phí live.

Ví $50/stake $30 ở 12:30 chỉ đi được 8 lệnh rồi còn $26.49, bỏ 402 cơ hội tiếp theo. Con số +$198.22 giả định luôn đủ vốn, không đạt được bằng cách chạy liên tục ví $50 này. Không đổi mức vốn hoặc tự nạp tiền trong mô phỏng.

## Giá mua giả định +1 cent

| Mốc vào | Trước: thắng/tổng | PnL trước | Sau: thắng/tổng | PnL sau | PnL toàn kỳ | PnL/lệnh | Lãi TB lệnh thắng | Số thắng TB bù 1 thua |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 11:30 | 273/288 | $-31.44 | 124/125 | $+165.16 | $+133.72 | $+0.324 | $1.546 | 19.4 |
| 12:00 | 272/287 | $-46.42 | 124/125 | $+165.16 | $+118.74 | $+0.288 | $1.512 | 19.8 |
| 12:30 | 278/289 | $+84.77 | 120/121 | $+113.45 | $+198.22 | $+0.483 | $1.403 | 21.4 |
| 13:00 | 275/286 | $+75.34 | 120/121 | $+113.45 | $+188.79 | $+0.464 | $1.389 | 21.6 |
| 13:30 | 249/261 | $-35.66 | 97/98 | $+79.07 | $+43.41 | $+0.121 | $1.253 | 23.9 |
| 14:00 | 247/259 | $-34.04 | 97/98 | $+79.07 | $+45.03 | $+0.126 | $1.265 | 23.7 |
| 14:30 | 183/191 | $-35.53 | 77/79 | $+20.58 | $-14.95 | $-0.055 | $1.096 | 27.4 |
| 14:45 | 181/189 | $-38.43 | 77/79 | $+20.58 | $-17.85 | $-0.067 | $1.094 | 27.4 |

Mỗi lệnh thua mất $30. Số thắng bù lỗ dùng mức lãi trung bình các lệnh thắng đã quan sát; không phải cam kết những lệnh thắng tiếp theo có cùng lợi nhuận.

## Stress chi phí, độ mới dữ liệu và ví $50

| Mốc | PnL +2c | PnL +3c | +3c trước / sau | Giá mới <=15s | Ví $50 cuối kỳ | Khoảng bootstrap 95% PnL/lệnh |
|---|---:|---:|---:|---:|---:|---:|
| 11:30 | $+18.59 | $-20.10 | $-150.44 / $+130.34 | 26/413 | $18.03 | $-0.297 đến $+0.855 |
| 12:00 | $+4.34 | $-33.35 | $-163.69 / $+130.34 | 10/412 | $26.49 | $-0.334 đến $+0.829 |
| 12:30 | $+86.96 | $+27.18 | $-27.69 / $+54.87 | 34/410 | $26.49 | $-0.024 đến $+0.931 |
| 13:00 | $+78.69 | $+20.16 | $-34.71 / $+54.87 | 5/407 | $22.14 | $-0.057 đến $+0.916 |
| 13:30 | $-52.11 | $-127.07 | $-160.57 / $+33.50 | 20/359 | $22.14 | $-0.551 đến $+0.653 |
| 14:00 | $-50.25 | $-125.39 | $-158.88 / $+33.50 | 6/357 | $23.75 | $-0.553 đến $+0.658 |
| 14:30 | $-82.52 | $-131.24 | $-119.92 / $-11.32 | 13/270 | $23.75 | $-0.870 đến $+0.651 |
| 14:45 | $-84.82 | $-132.84 | $-121.51 / $-11.32 | 2/268 | $21.56 | $-0.899 đến $+0.649 |

Giả định +1/+2/+3c không phải spread hoặc slippage đã đo. Stress giữ tập ứng viên +1c; khi giá >=1 thì không mua, PnL=0, có thể bỏ cả lệnh thua. JSON lưu số nonfill và số would-lose. Ví $50 chạy liên tục cả hai giai đoạn, không tự nạp lại; settlement được giả định trả tiền ngay hết hạn.

Các mốc lọc ra tập lệnh khác nhau; không thể diễn giải rằng chờ thêm tự biến cùng một lệnh thua thành thắng. Vào 14:45 chỉ còn 15 giây nhưng dữ liệu được phép cũ 75 giây, nên đặc biệt không đủ kiểm chứng khớp live. Chưa có sổ lệnh lịch sử, độ trễ và phí lịch sử được xác nhận; chưa trừ gas, nạp/rút hay máy chủ. Bootstrap chỉ chẩn đoán, chưa hiệu chỉnh thử nhiều mốc.

Chạy lại: `python -B research_late_entry_payoff.py`. Dữ liệu chi tiết: `logs/late_entry_payoff/`. Đối chứng 11:30 được kiểm tra tái hiện kết quả cũ. Không sửa Bot1 hay cấu hình paper/live.
