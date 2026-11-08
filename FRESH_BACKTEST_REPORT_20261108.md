# Kết quả nghiên cứu và tải thử 08/11/2026

## Kết quả quan trọng

Trên phần dữ liệu mới tải được, **bản gốc trước bộ lọc B** có 61 cơ hội đủ điều kiện,
57 thắng / 4 thua, win-rate **93,44%**, PnL giả định **-$28,9059** với $20/lệnh gồm phí.
**Chưa có kết quả Variant B mới**: thiếu ETH nên không tính bộ lọc một cách giả tạo.
PnL thực thi được để `null`, vì chưa có book lịch sử đúng các market BTC15m này.

Nguồn máy đọc: `data/research_20261108/summary.json`, `trades.csv`, `trades.json`.
Chi tiết từng request ở `raw/polymarket/{window_start}/`; checksum ở `file_manifest.json`.

## Phạm vi và dữ liệu thiếu

- Kế hoạch khóa trước: 01/10/2026 00:00 UTC tới 08/11/2026 00:00 UTC, end exclusive.
- Warmup từ 01/09. Tải được **79.000 phút BTC**, từ 01/09 00:00 tới 25/10 20:39 UTC.
- Thiếu 18.920 phút BTC so với toàn kế hoạch. ETH tải được 0/97.920 phút.
- Lighter trả HTTP 405, nội dung Human Verification. Không vượt challenge.
- Tất cả 289 tín hiệu có dữ liệu thuộc 01/10–25/10. Các ngày sau chưa được đánh giá,
  không được diễn giải thành ngày không có tín hiệu/lệnh hoặc lãi bằng 0.
- Kho GitHub dataset khác được kiểm tra có manifest dừng ở 02/08/2026; không tải
  archive 1,13GB vì không bổ sung được kỳ kiểm tra này.
- Download pipeline đã sửa để giữ manifest thiếu dữ liệu và chặn B khi thiếu peer.
  Protocol của lần download ban đầu vẫn được lưu trước khi chấm kết quả mới.

## Join dữ liệu official

289 tín hiệu DCA cố định `latest_5m`, 24h, vào T+750, ref>=0,85, ref tuổi<=75s.
Mỗi tín hiệu được tải event Gamma, CLOB market/winner, CLOB curve phí và lịch sử
hai outcome. Cả 289 market đều có settlement Gamma resolved và CLOB winner đồng ý;
đều có rule Chainlink TWAP và curve đối chiếu rate=0,07/exponent=1.

| Bước lọc | Số cơ hội |
|---|---:|
| Tín hiệu gốc có nến hợp lệ | 289 |
| Ref thấp hơn 0,85 | 185 |
| Ref+1c >=1 | 29 |
| Thiếu giá tham chiếu hoặc cũ quá 75s | 14 |
| Đủ điều kiện mô phỏng baseline | **61** |
| Variant B có đầy đủ BTC/ETH để đánh giá | **0 — chưa đánh giá được** |

Không tối ưu lại tham số theo bốn lệnh thua mới. Không sửa file triển khai, approval hoặc giới hạn ví.

## Kế toán và stress

Giá mua mặc định = ref+0,01, chưa có bằng chứng ask/depth lịch sử. Phí cash-equivalent
nằm trong $20. Chưa bao gồm gas/relayer, funding/nạp-rút/máy chủ; fee metadata là bản
tải hiện tại, không chứng nhận lịch sử match. PnL tổng giả định luôn có vốn.

| Giá giả định | Tập cơ hội cố định | Giả định mua được | Không mua vì giá>=1 | Win-rate trong nhóm mua | PnL |
|---|---:|---:|---:|---:|---:|
| Ref+1c | 61 | 61 | 0 | 93,44% | -$28,91 |
| Ref+2c | 61 | 50 | 11 | 94,00% | -$19,41 |
| Ref+3c | 61 | 39 | 22 | 94,87% | -$7,95 |

**PnL ít âm hơn ở +2/+3c không có nghĩa chi phí tăng làm chiến lược tốt hơn.**
Các kịch bản đó bỏ cả những cơ hội thua vì giá >=1. Đây không phải FOK trần +1c
được phép tự khớp đắt hơn. Tỷ lệ đúng hướng trên 61 cơ hội gốc vẫn là 57/61.

Lãi trung bình một lệnh thắng: $0,8964; mỗi thua mất $20.
Overhead giả định thêm $0,01/fill => -$29,52; $0,05/fill => -$31,96.
Bootstrap block 3 ngày của tổng PnL: khoảng chẩn đoán 95% **[-$98,92; +$38,10]**.
Cỡ mẫu nhỏ, chưa chứng minh được dấu PnL bền vững.

Ví $50/stake $20 chạy liên tục thực hiện 58/61 cơ hội, bỏ 3 vì thiếu vốn,
kết thúc **$17,4993**, PnL -$32,5007. Drawdown realized tối đa $60,3038 tính từ
đỉnh ví, không phải tính từ vốn ban đầu. Redemption trễ 0/300/1800s cho cùng kết quả
trên tập này; không khẳng định tiền settlement thật về ngay hoặc trễ đúng các mốc đó.

## Dữ liệu thực thi đã ghi

- Probe 120 giây: **220 REST books**, **21.802 WSS frames** của hai outcome trong một market.
  Clock parser ban đầu chưa đọc được `/time` text/plain: log giữ nguyên, không gọi
  các depth-probe bị chặn clock là lệnh không khớp của chiến lược.
- Probe sau sửa parser, 30 giây: **48 REST books**, **2.397 WSS frames**, clock kiểm tra
  ba lần; RTT REST book trung vị **250ms**, tối đa **2.656ms** ở môi trường hiện tại.
- `/time` có độ phân giải giây nên quote age hiệu chỉnh có thể âm vài trăm ms;
  số đo này không phải độ chính xác đồng hồ microsecond hoặc latency match.
- Đây là acquisition probe trên **một** market, không phải 220/48 lệnh độc lập,
  không phải forward win-rate Variant B, không có lệnh thật hoặc PnL thực thi.

Log: `data/execution_probe_20261108/` và `data/execution_probe_verified_20261108/`.

## Dataset L2 ngoài sàn đã tải

- Vike: 8.792.043 bytes, 518.581 events, 3.606 full snapshots; market BTC5m ngày 06/11.
- PMData: 712.216 bytes, 77.239 events, 1.236 full snapshots; BTC5m ngày 01/09.
- Đã đọc Parquet, kiểm tra giá/size và crossed full snapshots: 0 sai ở cả hai mẫu.
- Mẫu 5m không bổ sung book cho 61 cơ hội BTC15m; cần đúng market/day/outcome.
- Attribution/license và nguồn tải trong [RESEARCH_DATA_GUIDE.md](RESEARCH_DATA_GUIDE.md).

## Kiểm chứng và phần còn thiếu

Suite đã chạy: **131 passed, 14 skipped**. Tests mới kiểm tra phí trong budget,
nonfill khi giá >=1, không dùng giá tương lai, reference age, settlement chưa final,
tick cap khác giá mô phỏng cũ, khóa vốn và dữ liệu nến lỗi. Một số tests cũ phụ thuộc
source Bot1/archive lịch sử riêng không có trong checkout nên bị skip; không coi là đã pass.

Để hoàn tất đánh giá B: cần bổ sung ETH cùng nguồn và BTC còn thiếu qua truy cập
Lighter hợp lệ hoặc archive có provenance, rồi dùng output mới chạy lại B cố định.
Để kiểm chứng PnL có thể thực thi: cần archive L2 đúng BTC15m hoặc forward collector
có quyết định B, book lúc có thể gửi, phí/tick, gap và settlement nhận thực tế.
Không thể khôi phục các phần đó từ `prices-history` hoặc lấy sample 5m thay thế.
