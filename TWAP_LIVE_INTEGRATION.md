# Tích hợp live TWAP60 + spot Chainlink

`run_bot.py` hiện khởi chạy `TwapBot`, không khởi chạy engine nến cũ. Các module
legacy giữ lại cho nghiên cứu/test lịch sử; entrypoint và script deploy cũ đã
chuyển sang TWAP. Hướng dẫn chạy tại [ORACLE_TWAP_LIVE_GUIDE.md](ORACLE_TWAP_LIVE_GUIDE.md).

**Quy tắc entry:** BTC Up/Down15m, đúng Chainlink60s trong metadata từng market,
chốt tại T+840s; khoảng dẫn>=5bp và spot cùng nguồn không yếu hơn TWAP theo phía
mua. Up khi spot>=TWAP, Down khi spot<=TWAP. Không dùng Bollinger, SMA25, ETH,
Binance, DCA direction hoặc Z-score cũ.

Opening phải có đúng source timestamp đầu market và nhận trong5s; lưu SQLite.
Cả spot và TWAP phải mới<=3s, đủ>=30 observations/phút, gap<=5s; sau snapshot/
reconnect/provider fallback cần lại một phút khỏe. Giá PolyBolt đã là Decimal
USD, không chia E18; chỉ file archive nghiên cứu dùng E18. Không dùng snapshot
nhận muộn để giả định đã biết opening. Conflicting revisions không được sửa
lại lịch sử như đã nhận trước đó.

**Parity với nghiên cứu:** vẫn cần ref>=.85, tuổi<=75s, cap ref+.01<1, round-down
tick; live maxcap.99. Ref chỉ đặt điều kiện/trần, không phải giá khớp. Đọc lại
tick/fee tại entry thay vì dùng metadata14 phút trước. Kiểm tra actual ask và
toàn bộ depth trong cap, haircut50%, book timestamp và request RTT<=1,5s. Tính
margin nếu thắng theo fee thật, không tạo một xác suất thắng hoặc EV giả định.

**Luồng live:** SDK0.17 `create_market_order` chỉ ký trước. Sau đó đọc lại geo,
balance, market/fee và REST book cuối; kiểm tra lại oracle, hướng cố định và
deadline. Kiểm tra token/maker/FOK, signed price và notional+fee, để dư1cent từ
mục tiêu20. Ghi intent SQLite FULL trước `post_order`. Nếu commit/chờ làm quote
cũ hoặc quá T+845s, không POST. SDK có thể xử lý lệnh sau thời điểm gửi; FOK,
latency và displayed depth không phải bảo đảm khớp.

`max_spend` của SDK là mục tiêu theo fee metadata, không phải cam kết phí venue
không đổi tại match. Không có builder fee được phép trong signed order của bot.
Trading allowance được chuẩn bị trước cửa sổ entry, không tự post lại sau lỗi
allowance ở thời điểm mua.

**Journal:** process lock cộng transaction/unique slug; một POST tối đa/market,
5 intent/lần thử mới mặc định, một vị thế chưa biết outcome; dừng sau một outcome
thua đã biết trong ngày UTC. Restart giữ bộ đếm và pending. State gắn wallet;
không dùng journal của ví khác. File/lock JSON legacy được giữ và import các
market từng thử; không đặt lại state của lần thử cũ để đổi chiến lược.

Mất phản hồi POST giữ ambiguous và chặn mua mới. Chỉ confirmed trade receipts
mới coi fill đã lên chain. Outcome cần Gamma/CLOB explicit winner cùng đồng ý,
không dùng lastPrice gần1. Auto-redeem vị thế mới thắng có journal trạng thái;
redemption mơ hồ không được lặp mù. Không có SELL/stop-loss tự động trong bản này.

**Kiểm chứng:** `audit_twap_runtime_parity.py` dùng exact Decimal trên tất cả222
cơ hội của hai tuần; giữ61/103 calibration và66/119 evaluation,0 mismatch với
rule nghiên cứu. Live thêm price/depth/account guards có thể loại thêm cơ hội.
66/66 là phát hiện post-hoc, không phải100% trong tương lai hay PnL khớp thật.

`tests/test_twap_live.py` kiểm tra cả no-post paths, stale/future/late receipt,
source fallback, sửa mốc đầu, signing trễ, final book, fee drift, wrong wallet,
FOK amount cap, journal restart, old state và chế độ paper không ký/gửi lệnh.
Các kết quả kiểm tra cuối cùng lưu trong `data/twap_live_validation_20261109`.

**Giới hạn xác minh môi trường:** metadata/fee/clock public được đọc; geography
PC lỗi DNS. Chưa có SSH credential để đăng nhập server hoặc wallet secret để
test authenticated PolyBolt. PC không có Docker daemon. Gói release và hướng
dẫn có các command kiểm tra trực tiếp từ VM trước khi chạy live.

Nguồn chuẩn: [Polymarket feed](https://docs.polymarket.com/market-data/realtime-data),
[fees](https://docs.polymarket.com/trading/fees),
[order lifecycle](https://docs.polymarket.com/concepts/order-lifecycle).
