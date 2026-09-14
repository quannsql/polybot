# Kiểm tra lại tín hiệu trước khi vào ở 11:30

## Kết luận

Có thể thực hiện, nhưng các cách xác nhận đã thử **chưa cải thiện đồng thời tỷ lệ
thắng và tổng PnL trên toàn bộ 138 ngày**. Không thay cấu hình bot đang chạy.

Giữ nguyên 413 cơ hội của backtest cũ, hướng ban đầu, mốc 11:30, ngưỡng tham chiếu
0.85 và settlement Polymarket. Điều kiện mới chỉ quyết định giữ hay bỏ lệnh,
không đảo hướng hoặc bổ sung market. Nguồn Lighter được kiểm tra SHA256 trùng
nghiên cứu trước; dựng lại hướng ban đầu khớp cả 413/413 market.

## Kết quả toàn bộ 138 ngày

Giả định $30/lệnh, mua tại tham chiếu+1 cent, phí cash-equivalent theo cache,
luôn đủ vốn và thanh khoản. Không phải khớp lệnh thật.

| Cách kiểm tra | Thắng/thua | Số lệnh | Win-rate | Tổng PnL |
|---|---:|---:|---:|---:|
| Không kiểm tra lại — bản cũ | 397/16 | 413 | 96,13% | +$133,72 |
| Chặn nếu xuất hiện tín hiệu mới ngược hướng | 397/16 | 413 | 96,13% | +$133,72 |
| Yêu cầu tín hiệu mới cùng hướng | 46/3 | 49 | 93,88% | -$20,16 |
| Điều kiện Bollinger của nhánh ban đầu vẫn đúng | 72/3 | 75 | 96,00% | +$26,09 |
| Như trên, nhưng short phụ dùng nến 15m đang chạy* | 13/1 | 14 | 92,86% | -$6,83 |

*Thử nghiệm phụ dùng dữ liệu đến 11:00, không phải giá tick đúng 11:30.

“Có tín hiệu mới” ở đây là DCA kích hoạt tại một trong hai nến 5m mới đóng
ở phút 5 và phút 10, không phải chỉ BTC đang tăng/giảm. Cách chặn ngược hướng
không loại lệnh nào trong tập 413 cơ hội đã lọc theo giá này.

## Tách hai giai đoạn, tránh chỉ nhìn nhóm 100%

| Cách kiểm tra | 86 ngày trước: thắng/tổng | PnL | 52 ngày sau: thắng/tổng | PnL |
|---|---:|---:|---:|---:|
| Bản cũ / chặn tín hiệu ngược | 273/288 | -$31,44 | 124/125 | +$165,16 |
| Tín hiệu mới cùng hướng | 32/35 | -$40,68 | 14/14 | +$20,52 |
| Điều kiện nhánh cũ vẫn đúng | 54/57 | -$1,33 | 18/18 | +$27,41 |
| Nến 15m đang chạy, proxy | 11/12 | -$8,29 | 2/2 | +$1,46 |

Nhóm 18/18 ở giai đoạn sau bỏ được một lệnh thua nhưng bỏ cả **106 lệnh thắng**.
Trên toàn kỳ cách này bỏ 13 lệnh thua và 325 lệnh thắng. Vì vậy 100% trên nhóm
nhỏ không chứng minh bot đã đạt 100% hay tốt hơn bản gốc.

## Ý nghĩa của nến 5m và 15m

Tại T+11:30, nến 5m mới nhất đã đóng tại T+10. Nến 15m mới nhất đã đóng tại T,
không có nến 15m mới đóng để xác nhận lần nữa trước khi market hết hạn tại T+15.

Trong backtest cũ đang làm đối chứng, có **231 Long từ nhánh 5m, 108 Short từ
nhánh 5m theo router ngày, và 74 Short từ nhánh phụ 15m**. Không phải toàn bộ
Short đều xuất phát từ 15m. Nghiên cứu này giữ nguyên cách đó để so sánh công bằng,
không khẳng định đây là mọi cờ cấu hình của Bot1 đang chạy thực tế.

Đáng chú ý: trong 75 lệnh giữ lại khi kiểm tra điều kiện nhánh cũ, **74 lệnh
là nhánh phụ 15m**. Điều kiện trên nến 15m đã đóng không thay đổi từ T đến 11:30.
Toàn bộ 18 lệnh của nhóm 18/18 cũng thuộc nhánh này. Đây chủ yếu là thay đổi
thành phần tập lệnh, không phải thu được thông tin mới từ nến 15m.

Chạm dải Bollinger của DCA là điều kiện vào kiểu hồi giá. Nếu giá đã hồi đúng
hướng trong thời gian chờ, nó thường không còn chạm dải ban đầu. Bắt chạm dải
lần nữa có thể loại chính những giao dịch đã đi đúng hướng. Đây là cách giải
thích phù hợp với số lệnh bị loại trong thử nghiệm, không phải quy luật chắc chắn.

## Phương pháp và giới hạn

- Ba cách dùng nến đóng và một thử nghiệm nến đang chạy được xác định trong
  `recheck_1130_protocol.json` trước khi chấm điểm lần này. Không dò thêm ngưỡng
  để chọn một bảng đẹp hơn.
- Tín hiệu cùng hướng: lấy sự kiện mới gần nhất trong hai mốc T+5 và T+10.
  Không có sự kiện thì bỏ. Veto ngược hướng: chỉ cần một sự kiện ngược ở hai mốc
  đó là bỏ, kể cả sau đó có tín hiệu cùng hướng.
- Nhánh 15m đang chạy: 19 giá đóng 15m trước T cộng với giá đóng 1m mới nhất
  biết được tại T+11. Tính lại Bollinger 20/2 và so sánh pump bốn bar như cấu trúc
  cũ. Khi bar chưa đủ 15 phút, đó không còn là cửa sổ đúng 60 phút thực thời gian.
- Không đọc nến 1m bắt đầu tại T+11: nến đó chưa hoàn tất ở 11:30. Không đọc
  giá đóng market hoặc nhãn settlement để quyết định giữ/bỏ.
- Thiếu dữ liệu không được coi là xác nhận. Kiểm thử thay đổi dữ liệu tương lai
  cho kết quả quyết định không đổi.
- Stress chi phí toàn kỳ +2c/+3c: bản cũ +$18,59/-$20,10; cách điều kiện nhánh
  cũ vẫn đúng +$5,52/-$11,78. Các trường hợp giá giả định >=$1 được ghi không mua,
  không âm thầm xóa khỏi tập cơ hội.
- Mỗi bảng giả định đủ vốn. File JSON có ví $50 riêng, giữ stake $30. Các cách
  thử đều có thể xuống dưới mức tiền đủ đặt lệnh; không suy ra lợi nhuận ví từ
  bảng PnL luôn đủ vốn.
- Thiếu sổ lệnh lịch sử và thời điểm nến thực sự được nhận. Phí/slippage còn
  là giả định, không gồm mọi chi phí vận hành/nạp rút. Lịch sử đã khảo sát nhiều
  lần; các khoảng bootstrap chỉ là chẩn đoán, không xác nhận cải thiện ngoài mẫu.

## Tái chạy

Chạy `python -B research_recheck_1130.py`. Đầu ra:
`logs/recheck_1130/summary.json` và `candidate_audit.json` (413 dòng đối chiếu).
Kiểm thử: `python -B -m pytest -q tests` — 100 bài đạt sau lần bổ sung này.

Không sửa Bot1, `legacy_protocol.json`, paper đang chạy, calibration hoặc luồng live.
Skill xử lý dữ liệu bảng được dùng để đối chiếu nguồn, giữ tập đối chứng và tách
nhất quán số cơ hội, số lệnh giữ lại, lệnh thắng bị bỏ và lệnh thua tránh được.
