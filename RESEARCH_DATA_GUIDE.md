# Dữ liệu và backtest sát thực tế hơn

Ngày kiểm tra nguồn: 08/11/2026. Chỉ tải public GET/WSS, không gửi lệnh.
Kết quả thực thi lần này: [FRESH_BACKTEST_REPORT_20261108.md](FRESH_BACKTEST_REPORT_20261108.md).

## 1. Phân biệt bốn loại dữ liệu

| Dữ liệu | Nguồn / API | Dùng để làm gì | Không suy ra được |
|---|---|---|---|
| Nến BTC/ETH 1m | Lighter `/api/v1/candles` | Dựng lại đúng tín hiệu và bộ lọc B | Settlement Polymarket hoặc giá mua token |
| Metadata, outcome IDs, quy tắc | Gamma `/events/slug/{slug}` | Xác định hợp đồng 15m, hướng Up/Down, rule, fees | Ask/depth lúc vào lệnh |
| Lịch sử giá outcome | CLOB `/prices-history?market={outcome_asset_id}&startTs=...&endTs=...&fidelity=1` | Tái lập giá tham chiếu của bot | Một lệnh đã/mua được ở giá đó |
| Sổ lệnh và settlement | CLOB `/book?token_id=...`, WSS market; `/markets/{condition_id}` | Ask/depth tại lúc nhận; winner đối chiếu Gamma | Book hiện tại không thay thế book lịch sử |

`market` trong `prices-history` là ID của outcome, không phải slug hoặc condition ID.
Đối chiếu tên outcome trước khi ánh xạ ID: không giả định Up luôn nằm ở vị trí đầu.
Fidelity=1 là chuỗi giá theo phút, không đủ mô phỏng cửa sổ vào 5 giây.
Bot giữ giá mới nhất **không sau** T+750s, tuổi <=75s, rồi kiểm tra ref>=0,85.
Không lấy điểm gần nhất nếu điểm đó nằm trong tương lai. Không nội suy giá có thể mua.

Nguồn: [price history](https://docs.polymarket.com/api-reference/markets/get-prices-history),
[market details](https://docs.polymarket.com/market-data/market-details),
[prices/order books](https://docs.polymarket.com/market-data/prices-order-books).
Market Protocol V2 có thể dùng `positionIds` thay `clobTokenIds`; script lần này
chặn market chưa hỗ trợ thay vì âm thầm dùng nhầm ID. Cả 289 market tải được là v1.

## 2. Phí và giá khớp

Phí taker phải đọc từ Gamma `feeSchedule` và đối chiếu CLOB `/clob-markets/{condition_id}`.
Không lấy `takerBaseFee=1000` rồi suy ra một mức phí toàn cục. Không suy diễn phí
trong quá khứ từ một bảng phí hiện tại nếu không lưu metadata đúng thời điểm đó.

Với curve exponent=1 được hỗ trợ trong repo:

```text
fee_cash = shares × feeRate × price × (1-price)
cost_per_share = price + feeRate × price × (1-price)
shares = budget_all_in / cost_per_share
PnL = shares × won - budget_all_in - other_costs
```

289 market mới đã đối chiếu đều trả rate=0,07, exponent=1. Đây là metadata
tải ngày 08/11, chưa phải chứng nhận curve tại từng fill lịch sử.
Giả sử $20 gồm phí, khớp toàn bộ ở một giá và giữ đến settlement:

| Giá mua | Phí trong $20 | Lãi nếu thắng | Lỗ nếu thua | Xác suất hòa vốn theo mô hình |
|---|---:|---:|---:|---:|
| 0,85 | $0,2078 | $3,2849 | -$20 | 85,8925% |
| 0,90 | $0,1390 | $2,0677 | -$20 | 90,6300% |
| 0,96 | $0,0558 | $0,7752 | -$20 | 96,2688% |
| 0,99 | $0,0140 | $0,1879 | -$20 | 99,0693% |

Nguồn công thức: [Polymarket fees](https://docs.polymarket.com/trading/fees).
Bảng không gồm gas/redemption, relayer, nạp/rút, vận hành; các khoản đó cần
đối soát giao dịch thực, không tự gán bằng 0 rồi gọi là chi phí thực tế.
Script báo thêm overhead $0,01/$0,05 mỗi fill như kịch bản độ nhạy, không coi là phí đã đo.
Không tính rebate khi chưa có bằng chứng đã nhận.

Đối với lệnh thật, cần đi qua từng mức ask để tính VWAP và phí, áp đúng tick,
min order và trần tổng chi. Không cộng spread lần nữa nếu đã dùng actual asks.
FOK không đủ depth trong trần giá => nonfill, không phải một lệnh thắng.

## 3. Cần gì để kiểm tra PnL thực thi

1. Tải đủ BTC/ETH 1m và 30 ngày warmup; kiểm tra trùng timestamp, OHLC sai, gap.
   Phút thiếu giữ thiếu, không forward-fill. Ghi đủ số market không thể đánh giá.
2. Khóa Variant B, thời gian, ngân sách và tiêu chí trước khi xem kết quả mới.
   Không chọn lại ngưỡng để loại các lệnh thua của lần kiểm tra mới.
3. Ghi full book snapshot + delta theo thời gian nhận, timestamp server, hash/seq,
   tick changes, disconnect/gap và phí đúng thời điểm. Sau gap phải đợi snapshot mới.
4. Dùng book tại thời điểm lệnh có thể đến nơi sau độ trễ; không dùng quote tương lai
   để quyết định tại quá khứ. Lưu thời gian feature sẵn sàng, request, response,
   quyết định và submit. RTT GET không phải độ trễ khớp lệnh.
5. Mô phỏng các mức thanh khoản/latency trên **cùng** tập cơ hội. Báo tỷ lệ đủ dữ liệu,
   số eligible, số không khớp, win-rate hướng, win-rate trong fill, PnL và drawdown riêng.
6. Chấm bằng settlement đã xác nhận, không chấm bằng Lighter/Binance proxy.
   TWAP và spot là hai quy tắc khác nhau; lưu rule hash và báo riêng khi rule đổi.
7. Replay ví $50 liên tục: tiền đang khóa không được dùng lại, redemption có độ trễ,
   không tự nạp thêm hoặc reset ví mỗi tháng. PnL giả định đủ vốn khác PnL ví.
8. Sau khi có đủ dữ liệu mới, báo theo tháng/nhánh và khoảng bất định theo block ngày;
   đối chứng với bản không B và chiến lược đơn giản cùng universe. Chạy shadow
   độc lập sau khi khóa cấu hình, rồi mới kiểm chứng với actual fill receipts nếu có.

Nguồn settlement và quy tắc: [resolution](https://docs.polymarket.com/concepts/resolution).
Trên chuỗi có thể kiểm tra trades/redeems nhưng không phục dựng được toàn bộ
ý định đặt lệnh off-chain chỉ từ các fill: [data resources](https://docs.polymarket.com/resources/blockchain-data).

## 4. Tải book lịch sử ở đâu

Đã tải và mở thực tế hai mẫu miễn phí:

| Nhà cung cấp | Mẫu local | Quy mô đã đọc | Điều kiện / giới hạn |
|---|---|---:|---|
| [Vike](https://vike.io/data/polymarket/historical-data) | `data/orderbook_samples/vike_book_events.parquet` | 518.581 events, 3.606 full snapshots | Mẫu không cần key; toàn archive cần free key; CC BY-NC 4.0, ghi công Vike; kiểm tra coverage market |
| [PMData](https://pmdata.dev/polymarket-historical-data) | `data/orderbook_samples/pmdata_l2.parquet` | 77.239 events, 1.236 full snapshots | Mẫu không cần key; archive cần tài khoản/API key, giới hạn theo gói |

Cả hai là **BTC 5m**, dùng để kiểm tra schema, không dùng làm PnL bot BTC 15m.
PMData mẫu tải thực tế là ngày 01/09/2026, khác slug minh họa trên trang web;
Vike mẫu là ngày 06/11/2026. Phải đọc nội dung và manifest thay vì tin ví dụ URL.
Full snapshots trong hai mẫu không có mức giá/size sai hoặc crossed book qua kiểm tra.
Điều này chưa xác nhận tính liên tục của delta hay độ phủ archive.

Để dùng archive BTC15m cần lọc đúng slug/outcome, ngày, giờ T+750..755,
kiểm tra gap/timestamps, đối chiếu metadata official và lưu license/provenance.
Chưa tạo tài khoản, chưa mua gói hoặc dùng key của người dùng.

## 5. Chạy lại các công cụ

Python 3.12; tạo môi trường riêng và cài `requirements-data-research.txt`.
Môi trường đã chuẩn bị trong workspace hiện tại: `.venv-research`.

```powershell
# Chạy lại offline đúng bộ dữ liệu đã cache; không gọi mạng
.\.venv-research\Scripts\python.exe -B research_fresh_data.py --offline

# Một đợt tải mới khi Lighter đã truy cập hợp lệ, dùng output mới
.\.venv-research\Scripts\python.exe -B research_fresh_data.py --start 2026-10-01 --end 2026-11-08 --output-dir data\fresh_complete

# Ghi dữ liệu hiện tại hữu hạn; mỗi lần dùng output mới
.\.venv-research\Scripts\python.exe -B capture_execution_data.py --duration-seconds 3600 --output-dir data\execution_next

# Kiểm tra hai mẫu Parquet đã tải
.\.venv-research\Scripts\python.exe -B inspect_orderbook_samples.py

$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
.\.venv-research\Scripts\python.exe -B -m pytest -q tests --basetemp=D:\polybot\data\pytest_next
```

`--end` là mốc UTC không bao gồm. Đợt tải ghi `protocol.json` trước khi chấm,
giữ checksum code/dữ liệu. Nếu code hoặc protocol đổi phải dùng output mới.
`data/` được gitignore để raw/capture lớn không vô tình vào Git.
Script không đọc `.env`, ví/private key, không import engine gửi lệnh, không đổi cấu hình live.
HTTP 403/405 challenge được giữ làm bằng chứng; không tự vượt xác minh hoặc dùng proxy.

`capture_execution_data.py` chỉ là acquisition probe hai outcome, không phải forward
Variant B hoàn chỉnh: không có tín hiệu DCA, oracle stream hoặc settlement join.
Collector lâu hơn cần ghép các thành phần đó trước khi tính win-rate/PnL B.
