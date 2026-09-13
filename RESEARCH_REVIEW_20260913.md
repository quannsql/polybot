# Đối chiếu Bot DCA và nghiên cứu Bot Polymarket — 13/09/2026

Có thể tái sử dụng tín hiệu hồi giá của DCA để nghiên cứu dự đoán cửa sổ BTC
15 phút. Kết quả hiện tại ủng hộ thử nghiệm paper, chưa chứng minh được lợi
nhuận giao dịch Polymarket. Số 301 lệnh cũ có thể tái lập; cách trình bày trước
đó đã làm lẫn số tín hiệu toàn kỳ với số lệnh sau các bước chọn mẫu.

## Logic được kiểm tra trực tiếp

Các đường dẫn bên dưới đều chỉ được đọc:

| Thành phần Bot1 | Hành vi trong code | Ý nghĩa khi chuyển sang Poly |
|---|---|---|
| `band_dca_lane.py:band_touch` | Close nến 5m đã đóng <= lower BB20/2 để LONG, >= upper để SHORT | Bắt hồi/đảo nhịp tại đuôi dải; không phải dự báo xu hướng liên tục |
| `daily_route` | Nếu bật router: close D-1 < SMA25 × 0,985 chọn SHORT; còn lại LONG | Là chế độ ngày, không phải dự báo độc lập mỗi 15m |
| `band_dca_bot.py:_selected_side` | Router tắt thì chọn LONG cho lệnh mới | Bản Poly trước luôn giả định router bật |
| `short_lane_15m_signal` | Close 15m >= upper BB20/2 và close/close cách 60 phút − 1 >= 0,006 | Lane SHORT phụ độc lập với route ngày |
| `_tick` / `_short_lane_15m` | Main xét mỗi 5m; auxiliary mỗi 15m, ưu tiên trước khi đang flat | Chỉ xét main ở biên 15m sẽ loại tín hiệu tại :05/:10 |
| `entry_decision` | Phiên 08–22 UTC; còn kiểm trạng thái vị thế, runner, số chân nhồi | Số chân DCA không đồng nghĩa số hợp đồng Poly |
| `_closed_bar`, `_closed_bar_15m` | Chỉ nến đóng; tối thiểu 30 nến mỗi khung; close 60 phút trước là `iloc[-5]` trên 15m | Đã đưa kiểm tra đủ lịch sử vào lõi dùng chung |

Các bộ lọc tùy chọn hiện có còn gồm: khoảng cách EMA21 15m; adaptive sigma khi
dải 5m mở rộng và slope 15m bất lợi; shock/weak10/momentum turn; early direction
với ADX/DI 15m và biến động coin kia; RSI memory; chữ ký SL; khóa hướng sau SL;
lọc tỷ lệ nến nằm trên dải giữa cho lane phụ. Một số dựa vào vị thế BTC/ETH và
lịch sử SL của chính DCA, nên không thể chuyển nguyên trạng sang hợp đồng 15m.

Local `.env` có phiên 08–22 UTC nhưng không có bộ biến `BOT_BAND_DCA_*` để
xác nhận cấu hình deployment. Code và `.env.example` đặt router/lane phụ mặc
định tắt. Vì thế nghiên cứu đo rõ ba cấu hình: router bật + auxiliary, router
tắt + auxiliary, và main LONG đơn thuần. Đây là tín hiệu hướng thô, chưa phải
replay chính xác toàn bộ lệnh của phiên bản Bot1 đang chạy trên server.

TP1 30bp, SL 200bp, nhồi giá bình quân, runner và giới hạn 12h giải thích vì
sao tỷ lệ thắng chu kỳ DCA không tương đương tỷ lệ đúng hướng sau 15 phút.
Con số ~92% trong phần chú thích Bot1 không được coi là bằng chứng về tỷ lệ
thắng Polymarket hoặc về kết quả deployment hiện tại.

## Vì sao trước đây chỉ báo vài trăm lệnh?

Tái lập trên đúng dữ liệu `data_lighter_240d`, thực tế gồm 241 ngày,
15/11/2025–13/07/2026:

| Bước chọn mẫu cũ | Số lượng |
|---|---:|
| Tín hiệu main mỗi 5m + auxiliary mỗi 15m sau phiên/route/ưu tiên | 2.450 |
| Giữ tín hiệu xuất hiện đúng biên hợp đồng 15m | 1.024 |
| 60% tín hiệu đầu dùng ước lượng xác suất | 614 |
| 40% tín hiệu cuối để kiểm tra | 410 |
| Sau bộ lọc xác suất − ask − phí >= 0,03 tại ask 0,50 | 301 |

Vậy 301 không phải số tín hiệu trong toàn bộ 241 ngày. Chính sách xét tại biên
15m là một lựa chọn hợp lệ cho hợp đồng cố định, nhưng trước đó chưa được so
sánh với việc lưu tín hiệu ở hai nến 5m còn lại.

Các điểm sai/thiếu đã xác định:

- Sanity script ban đầu gán LONG khi SMA25 chưa đủ lịch sử: 1.113 mẫu trước đó
  bao gồm mẫu không đủ warmup. Đã sửa lỗi này trong script cũ.
- Bản được gọi là “walk-forward” chỉ chia một lần theo số tín hiệu. Nghiên cứu
  mới chia theo lịch và cập nhật calibration hàng tháng bằng nhãn đã kết thúc.
- Backtest cũ dùng phiên 08–22 UTC, runtime Poly mặc định 24h. Mặc định đã đồng
  bộ về 08–22; thử nghiệm 24h được ghi thành biến thể riêng.
- $1/lệnh cũ có thể nhỏ hơn minimum 5 shares. Kịch bản nghiên cứu mới dùng ngân
  sách giả lập $5 gồm phí, kiểm tra minimum 5 shares.
- Spread cũ là điều kiện lọc, không phải lịch sử giá; `fill_rate` chỉ nhân khối
  lượng. Không thể từ đó khẳng định đã mô phỏng queue/fill thực tế.
- Runtime cũ có thể xử lý biên cũ khi khởi động giữa cửa sổ. Nay có giới hạn
  trễ đầu vào 45 giây; mặc định chờ dữ liệu 20 giây sau biên.
- Công thức Kelly trong script PnL cũ lẫn số shares/vốn với tỷ lệ vốn chi ra;
  đã sửa thành `(p - cost)/(1 - cost)` cho ngân sách gồm phí.

## Cách ánh xạ tín hiệu 5m sang cửa sổ 15m

`boundary`: tại 10:15 chỉ xét tín hiệu vừa đóng lúc 10:15, dự đoán 10:15–10:30.

`latest_5m`: tại 10:15 lấy tín hiệu gần nhất có trong các mốc 10:05, 10:10,
10:15. Nếu có tín hiệu mới ở 10:15 thì ưu tiên tín hiệu đó, bao gồm auxiliary.
Tín hiệu cũ nhất được giữ 10 phút; mỗi hợp đồng tối đa một dự đoán. Cả thời
điểm tín hiệu và thời điểm vào đều phải nằm trong phiên đã chọn.

`rolling_15m`: tín hiệu lúc 10:05 dự đoán 10:05–10:20. Đây chỉ là phép đo tác
dụng sau 15 phút, có cửa sổ chồng lấn và không đại diện hợp đồng Polymarket
10:00–10:15 hoặc 10:15–10:30. Không tính PnL hợp đồng cho biến thể này.

## Kết quả trên cùng dữ liệu cũ, đã chuẩn hóa warmup

Bỏ 25 ngày đầu cho tất cả biến thể để cùng thời gian quan sát. Khoảng đo:
10/12/2025–13/07/2026; phần kiểm tra từ 19/04/2026. Xác suất được ước lượng lại
đầu mỗi tháng từ dữ liệu trước tháng đó, chỉ dùng nhãn đã hết hạn.

| Router + auxiliary | Phiên UTC | Cách chọn | Tổng dự đoán | Mẫu kiểm tra | Đúng hướng |
|---|---|---|---:|---:|---:|
| Bật | 08–22 | boundary | 970 | 357 | 54,62% |
| Bật | 08–22 | latest_5m | 1.589 | 587 | 54,17% |
| Bật | 24h | boundary | 1.554 | 581 | 55,94% |
| Bật | 24h | latest_5m | 2.668 | 1.014 | 56,02% |
| Router tắt, auxiliary bật | 08–22 | boundary | 1.124 | 426 | 57,51% |
| Router tắt, auxiliary bật | 24h | latest_5m | 3.059 | 1.210 | 55,45% |

Đây là tất cả dự đoán hợp lệ trước lọc ask/edge. Khoảng bootstrap 95% lấy mẫu
theo ngày của router bật/latest_5m/24h là 53,35–58,49%; luôn dự đoán Up trên
cùng mẫu đạt 49,21%. Với latest_5m/08–22, khoảng là 50,00–57,91%, bằng chứng
yếu hơn. Nhiều tín hiệu trong cùng ngày có tương quan nên không coi mỗi lệnh
là một quan sát hoàn toàn độc lập.

Đối chứng mới “5m và 15m cùng phía dải giữa, slope 15m cùng chiều” tạo 4.513
mẫu kiểm tra 24h nhưng chỉ đúng 46,04%. Đây là một giả thuyết đơn giản được
đo thêm, không phải logic entry DCA. Tăng tần suất bằng cách buộc dự báo xu
hướng thường xuyên không tự tạo ra lợi thế. Không đảo chiều đối chứng sau khi
nhìn kết quả để chọn một chiến lược mới.

Số 970 khác 1.024 ở bảng cũ vì phép so sánh mới bỏ warmup chung cho cả lane
phụ; bảng tái lập cũ giữ nguyên lịch sử lane phụ từ đầu để truy ra số 301.

## Kiểm tra thêm dữ liệu đến 03/09/2026

Ghép nguồn Lighter 240d + augall + 0903, ưu tiên file đầu ở vùng trùng nhau:
64.315 hàng trùng, không có xung đột OHLC, thiếu 54 phút. Không tự điền giá;
nến 5m, cửa sổ kết quả và lịch sử chỉ báo bị ảnh hưởng sẽ không được dùng.
Một ngày thiếu dữ liệu cũng làm mất khả năng dựng SMA25 ngày từ nến nhỏ trong
25 ngày tiếp theo. Đây là lựa chọn thận trọng và làm giảm số tín hiệu router;
nến ngày riêng của sàn có thể khôi phục coverage trong một nghiên cứu sau.

Phần kiểm tra từ 20/05 đến 03/09/2026 16:45 UTC:

| Cấu hình | Tổng dự đoán | Mẫu kiểm tra | Đúng hướng |
|---|---:|---:|---:|
| Router bật, boundary, 08–22 | 1.088 | 337 | 55,79% |
| Router bật, latest_5m, 08–22 | 1.810 | 564 | 56,38% |
| Router bật, latest_5m, 24h | 3.067 | 987 | 56,53% |
| Router tắt + auxiliary, latest_5m, 24h | 3.578 | 1.298 | 56,01% |

Đây là kiểm tra nhạy cảm có phần lịch sử trùng bộ đầu, không phải một tập
kiểm định độc lập. Đã chạy thêm dữ liệu 01/02/2025–03/09/2026 trong `extended`;
bộ này thiếu 876 phút, chỉ 71.712/166.953 mốc 5m dựng được route ngày đầy đủ.
Vì coverage khác đáng kể giữa các cấu hình, không dùng bảng dài nhất để chọn
“cấu hình thắng”. Manifest, hashes, coverage và kết quả mọi biến thể có trong
JSON tương ứng. Không tải lại hoặc ghi đè dữ liệu Bot1.

Đối chiếu nến 5m lưu sẵn với nến dựng từ 1m trong bộ 240d: chỉ một open lệch
0,4 USD tại 30/05/2026 13:10 UTC; close/high/low giống nhau, không đổi trigger
Bollinger dựa trên close.

## Ý nghĩa với bot Polymarket

Ứng viên đáng paper-test là `latest_5m` trên cửa sổ cố định, với đối chứng
`boundary` và phân nhóm router bật/tắt. Chưa tự đổi bot sang cấu hình có điểm
cao nhất: các thử nghiệm dùng lại dữ liệu từng phục vụ nghiên cứu Bot1, không
phải kiểm định hoàn toàn mới; nhiều biến thể cũng làm tăng rủi ro chọn theo mẫu.

Giá Lighter đầu/cuối cửa sổ hiện chỉ là nhãn thay thế. Market thực tế được
kiểm tra qua Gamma ngày 13/09/2026 xác định nguồn Chainlink BTC/USD TWAP 60s:
[market đã kiểm tra](https://polymarket.com/event/btc-updown-15m-1789265700).
Phải đọc rules từng market và kết quả resolve chính thức; không tự đồng nhất
close Lighter với TWAP. RTDS TWAP không có replay/history khi reconnect theo
[tài liệu chính thức](https://docs.polymarket.com/market-data/chainlink-twap).

JSON có các kịch bản giá ask 0,45/0,50/0,55 để xem độ nhạy. Hệ số phí 0,07
trong `shares × rate × price × (1-price)` không có nghĩa trừ 7% mọi lệnh.
Ở ask 0,50, mô hình phí cộng riêng cho cost/share 0,5175, cần >51,75% đúng để
hòa vốn. Ask đã là giá mua qua spread, không cộng spread lần nữa. Tham khảo
[phí Polymarket](https://docs.polymarket.com/trading/fees).

PnL giả lập còn giả định khớp đủ, không trượt thêm và nhận payout ngay khi hết
cửa sổ. Chưa có book lịch sử, phí lịch sử từng market, thời gian khóa vốn chờ
resolve hoặc market availability thời đó. Dữ liệu giá BTC có trước cả thời
điểm tồn tại một số series nên không được gọi là giao dịch lịch sử của series.

Runtime hiện vẫn là bản paper/prototype: ghi tín hiệu/quote/quyết định; chưa
hoàn chỉnh đối soát fill, ledger tiền mặt và settlement. Live adapter vẫn cần
xác minh SDK, price cap và reconciliation. Nghiên cứu này không tự duyệt
calibration và không gửi lệnh thật.

## Files và tái lập

- `audit_poly_research.py`: kiểm tra dữ liệu, đếm từng bước, so sánh mapping,
  fit hàng tháng, bootstrap theo ngày, kịch bản giá, xuất từng dự đoán.
- `polymarket_bot/signal_grid.py`: lõi closed-candle dùng chung với runtime.
- `polymarket_bot/signal.py`: snapshot dự đoán `boundary` hoặc `latest_5m`.
- `research_audit_20260913/{original_240d,through_sep03,extended}`: mỗi thư mục
  có `summary.json` và `predictions.csv` với thời điểm tín hiệu/market/fit.
- Tests kiểm tra parity với hàm DCA đọc-only, tương lai không thay kết quả
  quá khứ, warmup, gap, cửa sổ, nhãn hết hạn và parity runtime/batch.

```powershell
cd D:\polybot
python -B audit_poly_research.py --output-dir research_audit_20260913\original_240d
python -B audit_poly_research.py --data-dirs D:\backtest\data_lighter_240d D:\backtest\data_lighter_augall D:\backtest\data_lighter_0903 --output-dir research_audit_20260913\through_sep03
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -B -m pytest -q tests
```

Để nghiên cứu paper chính sách giữ tín hiệu, đặt `POLYMARKET_SIGNAL_POLICY=latest_5m`.
Mặc định vẫn `boundary`, router/auxiliary bật, phiên 08–22 UTC. Không coi
calibration của boundary là xác suất đã kiểm định cho latest_5m; cần fit và
theo dõi riêng theo policy, source, side, tuổi tín hiệu, nguồn giá và phiên.
