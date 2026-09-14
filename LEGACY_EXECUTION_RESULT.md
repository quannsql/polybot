# Kiểm chứng cấu hình backtest CŨ — 14/09/2026

Không tối ưu lại chiến lược. Kết quả 124/125 = **99,20%** đã được tái lập,
nhưng chưa phải bằng chứng rằng sàn sẽ khớp đủ những lệnh đó.

## Cấu hình được khóa

Hồ sơ: `legacy_protocol.json`, mã `dca_legacy_1130_ref85_v1`.

- Tín hiệu Lighter BTC, dữ liệu 1m ghép thành 5m; Bollinger 20/2,
  bộ chọn hướng ngày SMA25 và nhánh short phụ 15m như nghiên cứu cũ.
- Lấy tín hiệu gần nhất tại đầu market T, tuổi tín hiệu 0/5/10 phút;
  chạy 24 giờ. Không thêm giới hạn 08–22 UTC, không ép age=0.
- Xét tại T+690 giây (11:30), hết hạn T+900, không dự đoán thêm 15 phút từ lúc mua.
- Giá tham chiếu `prices-history` gần nhất không sau 11:30, tuổi tối đa 75 giây,
  tham chiếu >=0.85 và tham chiếu+0.01<1. Đây không phải bộ lọc giá ask.
- Không thêm trần 0.97, không thay hướng theo market-favourite, không tối ưu lại mốc vào.

## Tái lập lịch sử

Giá mua **giả định** = tham chiếu+1c; phí theo đường cong đã cache, cash-equivalent.
Chưa có order book lịch sử để xác nhận các giá này mua được với đủ khối lượng.

| Giai đoạn | Thắng / số cơ hội | Win-rate hướng | PnL $5/lệnh | PnL $30/lệnh* |
|---|---:|---:|---:|---:|
| 19/04–13/07: 86 ngày | 273/288 | 94,79% | -$5,24 | -$31,44 |
| 14/07–03/09: 52 ngày | 124/125 | 99,20% | +$27,53 | +$165,16 |
| Toàn bộ: 138 ngày | 397/413 | 96,13% | +$22,29 | +$133,72 |

*Giả định luôn có đủ vốn và thanh khoản; KHÔNG phải lợi nhuận của ví khởi đầu $50.
Chỉ 9/125 tham chiếu ở giai đoạn sau có tuổi <=15 giây; không có điểm nào <=1,5 giây.
Lịch sử này đã được khảo sát trước, không còn là tập kiểm chứng chưa từng xem.

## Stress chi phí, giữ nguyên 413 cơ hội

| Giá giả định | Cơ hội cũ | Giả định mua được dưới $1 | Không mua vì giá >=$1 | PnL toàn kỳ $30/lệnh* |
|---|---:|---:|---:|---:|
| Tham chiếu+1c | 413 | 413 | 0 | +$133,72 |
| Tham chiếu+2c | 413 | 364 | 49 | +$18,59 |
| Tham chiếu+3c | 413 | 306 | 107 | -$20,10 |

Đây là phân tích độ nhạy chi phí, **không phải đổi trần giá của bot paper sang +2/+3c**.
Mọi cơ hội vẫn nằm trong báo cáo; trường hợp không mua có cost=0, PnL=0.
Độ đúng hướng trên tập gốc không thay đổi. Đặc biệt +3c không mua lệnh thua duy nhất
trong 52 ngày sau; vì vậy tỷ lệ thắng trong nhóm còn mua được lên 100% không có
nghĩa tín hiệu tốt hơn. File JSON báo riêng cả số lệnh thắng/thua bị không mua.

## Ví $50, mỗi lệnh $30

Với giả định +1c và chạy toàn bộ lịch sử từ 19/04, ví chỉ thực hiện được 173/413
lệnh rồi còn **$18,03**, không đủ cho lệnh $30 tiếp theo. 240 lệnh còn lại bị bỏ
vì thiếu vốn, dù bảng giả định luôn đủ vốn cho tổng PnL dương.

Nếu bắt đầu mới ở 14/07 với $50 thì mô phỏng kết thúc ở $215,16, nhưng đó là
một thời điểm khởi đầu khác, không được ghép với ví đã cạn vốn trước đó.
Giả định tiền về ngay khi hết hạn hoặc trễ 5 phút cho cùng số trên; trễ 30 phút
là kịch bản khác, có trong JSON. Đây chưa phải thời gian redemption đã đo trên sàn.

## Phần mô phỏng gần live

`Dockerfile.legacy-paper` dùng collector public-only, không đọc ví/secret và không đặt lệnh:

- Thu 28 ngày Lighter 1m để làm warmup; thiếu phút/ngày không được nội suy.
  Tín hiệu đóng băng đầu market và lưu nguyên dữ liệu đầu vào.
- Gọi đúng `prices-history` tại 11:30. Không lấy dữ liệu về sau rồi giả vờ đã biết
  tại thời điểm quyết định; không thay tham chiếu bằng ask hay midpoint.
- Kiểm tra khớp trên asks thực tế sau độ trễ mục tiêu 250/500/1000ms; ghi cả RTT
  thực đo và tuổi snapshot. Lưu thêm WebSocket thô có dấu thời gian nhận.
- Thử 100% và 50% depth hiển thị, phí theo metadata market hiện tại, làm tròn phí
  lên để tránh thiếu ngân sách. Mỗi kịch bản độc lập, không cộng chung PnL/số mẫu.
- Để kiểm chứng giả định +1c, giữ limit không quá tham chiếu+1c, làm tròn xuống
  theo tick. Nếu đủ depth trong limit thì mô phỏng mua hết ngân sách $30;
  không đủ thì ghi không khớp. Đây là giả định thực thi FOK-like được công khai,
  không phải loại lệnh mà backtest cũ từng xác nhận đã khớp.
- Lưu cơ hội đủ điều kiện trước khi kiểm tra khớp. Dashboard so sánh PnL theo
  giả định cũ và theo depth trên chính cùng tập cơ hội có settlement xác nhận.
- Ví mô phỏng giữ vốn chờ nhãn settlement được quan sát; không tự cộng tiền từ
  một kết quả dự đoán. Redemption ngay khi nhãn xác nhận vẫn là giả định.

Sổ lệnh hiển thị không bảo đảm lệnh thật khớp: chưa chứng minh matching-engine
acceptance, cancellation race, số dư/allowance, rounding thực tế trên ví, gas,
phí trung gian nạp/rút, hay chi phí máy chủ. Không có maker rebate giả định.
Những khoản đó không được tuyên bố là đã tính đầy đủ.

Đã probe 5 market cũ qua `orderbook-history` (gồm lệnh thua duy nhất của giai đoạn
sau): API trả HTTP 200 nhưng data rỗng. Chỉ là kiểm tra mẫu, không khẳng định mọi
nguồn trên thị trường đều thiếu dữ liệu. Không thay bằng book hiện tại để lấp lịch sử.

## Chạy lại và đọc kết quả

```powershell
.venv-trial\Scripts\python.exe -B backtest_legacy_execution.py
.venv-trial\Scripts\python.exe -B probe_legacy_book_history.py
.venv-trial\Scripts\python.exe -B -m pytest -q tests
```

Kết quả chi tiết tại `logs/legacy_execution/summary.json`, danh sách đúng 413 cơ hội
tại `original_candidates.json`, bằng chứng GET tại `book_history_probe.json`.
Không push archive lớn hoặc thông tin nhạy cảm lên GitHub.

Collector mới phải dùng volume riêng; không trộn dữ liệu với thí nghiệm
`dca_boundary_1130_ask85_v1` trước đó. Hồ sơ, code và dependency được fingerprint;
đổi hồ sơ phải mở một tập dữ liệu mới.

**Trạng thái: tái lập chiến lược đạt; bằng chứng thực thi live chưa đạt.**
Các kiểm thử kiểm tra đúng chương trình, không xác nhận khả năng sinh lời.
Bot live hiện tại còn có bộ lọc/cổng calibration khác; báo cáo này không chứng minh
parity của luồng live đó. Không sửa calibration, bật live hay giao dịch tiền thật.
Ngày đánh giá 28 ngày là lịch xem lại dữ liệu, không phải tự động đủ điều kiện live.

Tài liệu nguồn: [Polymarket prices-history](https://docs.polymarket.com/api-reference/markets/get-prices-history),
[phí](https://docs.polymarket.com/trading/fees),
[WebSocket market](https://docs.polymarket.com/api-reference/wss/market),
[Lighter Candlestick API](https://github.com/elliottech/lighter-python/blob/main/docs/CandlestickApi.md).
