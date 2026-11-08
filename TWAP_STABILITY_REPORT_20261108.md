# TWAP BTC15m: 14 ngày dữ liệu, 7 ngày hiệu chuẩn + 7 ngày đánh giá

Ngày hoàn tất: 08/11/2026. Chỉ nghiên cứu; không sửa bot live, không gửi lệnh,
không mua dữ liệu hoặc tạo tài khoản.

## Kết luận

Đã mở rộng từ một ngày lên **14 ngày TWAP thực**, đối chiếu **1.344 market
BTC15m**. Mô hình chọn hướng có tín hiệu hữu ích, nhưng **chưa có bằng chứng
đủ mạnh để kỳ vọng $10–15/ngày ổn định** với vốn $50.

Ở cấu hình chính đã khóa trước khi chấm kỳ này, mô phỏng giá tham chiếu với
$15/lệnh và dừng sau một lệnh thua trong ngày cho **+$10,70 CẢ TUẦN**, không
phải mỗi ngày. Tuần vẫn có một ngày -$13,19, drawdown realized $15.

Khi kiểm tra ask/size thực đã ghi, phần dữ liệu đủ điều kiện rất nhỏ và thiếu
ngày có lệnh thua. Chưa thể xác nhận PnL thực thi cả tuần. Chấp nhận lãi mỗi
lệnh nhỏ hơn làm tăng một số cơ hội mua nhưng không tạo ra bằng chứng ổn định.

## Dữ liệu và độ tin cậy

| Thành phần | Phạm vi đã kiểm tra |
|---|---|
| TWAP BTC/USD 60 giây | 08–21/08/2026 UTC, 14 ngày liên tục |
| Reports thô / unique usable | 1.151.543 / 1.151.511; 0 timestamp xung đột giá |
| Hiệu chuẩn | 08–14/08, 672 cửa sổ BTC15m |
| Đánh giá | 15–21/08, 672 cửa sổ BTC15m |
| Settlement official | 1.344/1.344 Gamma resolved + CLOB winner đồng ý |
| Đối chiếu giá đầu/cuối có report | 2.526/2.526 khớp; không nội suy các biên thiếu |
| Oracle hợp lệ tại 14:00 | 645/672 kỳ hiệu chuẩn, 629/672 kỳ đánh giá |

Stream TWAP lấy từ [mileswangs/PMData](https://huggingface.co/datasets/mileswangs/polymarket-btc-updown-5m-orderbook-tick-data),
CC BY 4.0, pin revision và kiểm tra checksum. Tên dataset có “5m” nhưng ở đây
**chỉ dùng stream TWAP BTC**, rồi tải metadata/settlement/giá riêng cho **BTC15m**.
Không chuyển PnL sổ lệnh 5m thành PnL hợp đồng 15m.

Phí theo metadata từng market, đối chiếu Gamma/CLOB. Đây là metadata tải hiện
tại, chưa phải chứng nhận phí tại match lịch sử; chưa có gas/hosting/nạp-rút đã đo.

Không thay spot bằng TWAP tự tính từ nến. Nguồn settlement phải đúng TWAP60s
trong rule của market. [Polymarket resolution](https://docs.polymarket.com/concepts/resolution).

## Thiết kế cố định, không ép PnL về một mục tiêu

- Hướng = TWAP hiện đã nhận so với report đúng đầu market.
- Opening report phải được nhận trong 5 giây đầu; current report tuổi<=3s.
- Trong phút gần nhất cần >=30 observations, không gap>5s.
- Bốn cấu hình: 14:00/buffer5bp đối chứng; **14:00/buffer10bp chính**;
  14:30/buffer10bp; và buffer theo đuôi biến động hiệu chuẩn tại14:00.
- Buffer10bp = khoảng dẫn0,10%. Không coi đó là xác suất thắng đã hiệu chuẩn.
- Buffer đuôi chỉ dùng 620 final reports **đã nhận trước mốc fit**: q99 của
  độ dịch chuyển TWAP còn lại=8,8279bp; cộng2bp, buffer=10,8279bp. Không dùng tuần
  đánh giá để chọn ngưỡng này.
- Nghiên cứu vốn $10/$15/$20 mỗi lệnh, ví khởi đầu$50; có/không dừng sau một
  lệnh thua/ngày; redemption giả định trễ0/5/30 phút. Đây là các scenario riêng.
- Không chọn stake/buffer theo cấu hình có test PnL cao nhất hoặc để đạt$10–15.

Đây là **kiểm tra hồi cứu có chia thời gian nội bộ**, chưa phải tiền cứu hoàn
toàn độc lập: họ tham số đã được hình thành qua nghiên cứu ngày01/09, muộn hơn
kỳ dữ liệu tháng08 này. Protocol của lần này được khóa trước khi chấm, nhưng
không thể gọi toàn bộ quá trình là chưa từng xem dữ liệu tương lai. Cần kiểm
chứng mới sau ngày khóa cấu hình trước khi gọi là forward validation.

## Kết quả giá tham chiếu — không phải fill đã xác nhận

Giả định ref>=0,85, ref không sau quyết định và tuổi<=75s; mua ref+1 cent<1,
curve phí nằm trong ngân sách. Các hàng dưới **cùng $20/lệnh, giả định luôn đủ
vốn và chưa áp daily stop** để so sánh rule:

| Rule | Thắng/tổng | Win-rate | PnL 7 ngày | Trung bình/ngày |
|---|---:|---:|---:|---:|
| 14:00, buffer5bp | 116/119 | 97,48% | +$22,56 | +$3,22 |
| **14:00, buffer10bp** | **53/54** | **98,15%** | **+$15,79** | **+$2,26** |
| 14:30, buffer10bp | 7/7 | 100% trong mẫu | +$2,79 | +$0,40 |
| 14:00, buffer10,8279bp | 50/51 | 98,04% | +$13,30 | +$1,90 |

Không cộng các hàng: dùng nhiều market trùng nhau.

Rule chính có 217 dự đoán vượt buffer trong tuần, đúng215/217. Sau lọc giá chỉ
còn54 cơ hội và53/54 thắng. **Tỷ lệ đúng hướng khác tỷ lệ thắng/PnL nhóm mua.**
160 cơ hội vượt buffer có ref+1c>=1 nên không được coi là mua được.

Khi yêu cầu ref mới trong15s, tại14:00 không có điểm lịch sử đủ mới để tính PnL.
Không thể coi kết quả ref75s là đã đo được giá ask có thể khớp. Source price
history là chuỗi reference theo phút. [API price history](https://docs.polymarket.com/api-reference/markets/get-prices-history).

## Ví $50, $15/lệnh, dừng sau một thua/ngày

Quy tắc dừng tác động sau khi outcome được mô hình coi là đã biết. Tiền pending
không được dùng lại; ví không tự nạp/reset mỗi ngày. Redemption giả định trễ5 phút.

| Rule | Thắng/thua đã lấy | Lãi cả tuần | Ví cuối | Max realized drawdown |
|---|---:|---:|---:|---:|
| 14:00, buffer5bp | 98/2 | +$23,03 | $73,03 | $19,14 |
| **14:00, buffer10bp** | **49/1** | **+$10,70** | **$60,70** | **$15,00** |
| 14:30, buffer10bp | 7/0 | +$2,09 | $52,09 | $0,00 trong mẫu |
| 14:00, buffer10,8279bp | 46/1 | +$8,83 | $58,83 | $15,00 |

Rule14:30 có ít giao dịch; DD0 trên7 mẫu không phải không rủi ro. Rule chính
vẫn DD30% vốn ban đầu. Dừng sớm có thể bỏ lệnh thắng sau đó; không mặc định là
cách tăng PnL. Chi tiết rule chính, $15/lệnh:

| Ngày UTC | PnL tham chiếu |
|---|---:|
| 15/08 | $0,00 |
| 16/08 | $0,00 |
| 17/08 | +$0,57 |
| 18/08 | +$0,36 |
| 19/08 | **-$13,19** |
| 20/08 | +$7,86 |
| 21/08 | +$15,10 |
| **Tổng 7 ngày** | **+$10,70** |

Ngày0 không có lệnh reference đủ điều kiện, không chứng minh ngoài thị trường
không có cơ hội. Bỏ ngày lãi lớn nhất21/08, tổng còn **-$4,40**. Đây chưa phải
chuỗi lãi đều. Khoảng bootstrap theo ngày của PnL luôn đủ vốn$20/lệnh là
**[-$36,94; +$66,05]**; chỉ có7 ngày nên khoảng này mang tính chẩn đoán.

### Giảm stake giảm mức tiền chịu rủi ro, không tăng xác suất đúng

Rule chính, cùng daily stop/redemption5m:

| Stake | PnL tuần | Max realized DD |
|---|---:|---:|
| $10 | +$7,13 | $10 |
| $15 | +$10,70 | $15 |
| $20 | +$14,26 | $20 |

### Stress chi phí trên cùng tập cơ hội gốc

Rule chính $15/stake, daily stop:

| Scenario | PnL tuần | Số lệnh lấy |
|---|---:|---:|
| Ref+1c | +$10,70 | 50 |
| Thêm overhead giả định$0,01/fill | +$10,20 | 50 |
| Thêm overhead giả định$0,05/fill | +$8,20 | 50 |
| Ref+2c, giữ tập gốc | +$4,20 | 39 |
| Ref+2c và overhead$0,05/fill | +$2,25 | 39 |

Ở ref+2c,11 cơ hội gốc bị ghi nonfill vì giá>=1. Không phải bot trần+1c có thể
tự khớp+2c. Overhead là kịch bản, không phải chi phí vận hành đã đo.

## Kiểm tra ask/size thực đã ghi

Đã tải thêm nguồn BTC15m công khai:

- [gensx-x1](https://github.com/gensx-x1/polymarket-btc-eth-updown-data):
  1.014.783 rows BTC15m cho06–18/08; trong tuần đánh giá có337 market với ít
  nhất một snapshot, từ15/08 tới trưa18/08. Chỉ top-of-book; không có timestamp
  exchange/request/response tách riêng để chứng nhận độ mới quote.
- [PolyOrderbooks](https://huggingface.co/datasets/polyorderbooks/polymarket-crypto-updown-orderbooks-l2),
  CC BY4.0: phần trùng tuần có8 market BTC15m ngày21/08, ladder sampled theo thời gian.
  Token ID được đối chiếu official; không tin trực tiếp cột winner của dataset.
- 5 file nén GitHub đều khớp Git blob hash của revision đã pin. Database mở
  read-only; chỉ xuất BTC15m. Không dùng book5m thay thế.

Các ngày19–20/08 chưa có book trùng kỳ từ những nguồn đã lấy. **Lệnh thua của
rule chính nằm ngày19/08, ngoài độ phủ sổ lệnh.** Không được giả định nó không
khớp hoặc coi ngày thiếu dữ liệu là PnL0. Oracle còn một dự đoán sai vượt buffer
khác không lọt tập ref+1c; cả hai đều thiếu book trong kiểm tra quote.

### Replay có giới hạn giá, arrival latency và depth haircut

Sub-study thực thi riêng, khóa trước khi chấm quote: cần ask ở thời điểm quyết
định và quote mới trong khoảng tới lúc lệnh giả định đến nơi; không lấy book
tương lai. Main scenario500ms, tuổi capture<=1,5s, chỉ dùng50% depth hiển thị,
$15 gồm phí venue. Giá phải0,85..0,99, trần đóng băng ask ban đầu+0,001 tối đa0,99.
Chỉ dùng top-of-book ở cả hai nguồn, không tự bịa depth ngoài ảnh chụp.

- Rule chính14:00/buffer10bp: **0 trường hợp có đủ điều kiện quan sát** ở scenario chính.
- Đây không phải bằng chứng strategy chắc chắn không khớp; phần lớn là thiếu
  coverage, book one-sided/crossed, giá quá cao hoặc không quan sát được arrival.
- Daily cash không đổi khi không có lệnh mô phỏng không phải chứng nhận PnL
  thực thi$0. `certified_week_execution_pnl` vẫn để `null`.

### Chấp nhận giá cao hơn và lãi thấp hơn

Sensitivity sau nghiên cứu chính: trần0,99 / 0,995 / 0,999, lãi tiềm năng nếu
thắng tối thiểu$0,05 hoặc$0,01, latency500/1000ms. Đây là thăm dò bổ sung, không
phải holdout mới. Cùng50% depth, tuổi capture1,5s, giả định thêm$0,01/fill.

Rule chính14:00/buffer10bp, latency500ms, min-winning-margin$0,01:

| Trần giá | Mẫu quote đủ điều kiện | Kết quả nhóm quan sát | PnL nhóm quan sát |
|---|---:|---:|---:|
| 0,99 | 0 | Chưa có mẫu | Không có PnL để đánh giá |
| 0,995 | 1 | 1 thắng | +$0,0883 |
| 0,999 | 7 | 7 thắng | +$0,1397 |

**Không gọi +$0,1397 là PnL cả tuần.** Nhóm rất nhỏ, thiếu ngày có lệnh thua,
clock alignment giữa các nhà cung cấp chưa chứng nhận và displayed depth
không bảo đảm fill. Không có giao dịch thật hoặc fill acknowledgment.

## Vì sao lãi nhỏ hơn chưa đồng nghĩa ổn định hơn

Một lệnh thua$15 có thể xóa rất nhiều lần thắng vài cent. Ngay cả giả định
cực mạnh mua được toàn bộ96 hợp đồng/ngày, cùng giá và đều thắng:

| Giá thực mua giả định | Lãi/thắng với$15 gồm phí | Trần số học/ngày, chưa chi phí khác |
|---|---:|---:|
| 0,99 | $0,1409 | $13,53 |
| 0,995 | $0,0701 | $6,73 |
| 0,999 | $0,0140 | $1,34 |

Đây là trần số học **nếu mọi fill đều ở đúng mức giá trong hàng**, không phải
giới hạn của chiến lược cho phép mua rẻ hơn, không phải dự báo hoặc thanh khoản
sẵn có. Ví dụ khi mua chủ yếu quanh0,995–0,999 thì mục tiêu$10–15/ngày với$15/lệnh
rất khó về mặt kinh tế ngay cả trước khi xét lệnh thua/gap/nonfill.

Phí dùng công thức [Polymarket](https://docs.polymarket.com/trading/fees);
giá outcome cao là giá thị trường, không phải xác suất mô hình đã kiểm chứng.

## Quyết định hiện tại và bước tiếp

1. **Chưa có cấu hình nào đủ bằng chứng gọi là lợi nhuận ổn định.** Không triển
   khai dựa trên việc một nhóm nhỏ có100% thắng hoặc PnL số học gần$10–15.
2. Có thể giữ14:00/buffer10bp và14:30/buffer10bp làm hai đối chứng shadow cố
   định. Không thêm ngưỡng để loại riêng lệnh thua19/08 đã biết.
3. Ưu tiên lấy **L2 BTC15m đầy đủ, đặc biệt các ngày thua**, cùng TWAP theo thời
   gian nhận, tick/fee và latency, trước khi nâng kết quả ref lên kết quả thực thi.
4. Để lên một tháng, cần cùng các đầu vào đó cho30 ngày; không kéo dài chuỗi
   reference rồi gọi là backtest khớp lệnh một tháng. Bộ miễn phí hiện có14 ngày
   TWAP, book chỉ phủ một phần. Chưa mua hoặc dùng credential trả phí.
5. Thử nghiệm mới sau ngày khóa cấu hình sẽ mạnh hơn validation hồi cứu này.
   Báo PnL từng ngày, DD, loss streak, số cơ hội thiếu data, capacity, cost stress
   và vốn liên tục; không chỉ win-rate hoặc tổng PnL.

## Artifacts và tái lập

```powershell
# Mọi lệnh nghiên cứu dưới đây chạy offline sau khi dữ liệu đã cache
.\.venv-research\Scripts\python.exe -B research_twap_stability.py --offline
.\.venv-research\Scripts\python.exe -B research_twap_depth.py
.\.venv-research\Scripts\python.exe -B research_twap_price_ceiling.py
```

- `data/twap_stability_20261108/stability_protocol.json`: cấu hình khóa và source/code hash.
- `stability_summary.json`, `evaluation_trades.csv`: mô phỏng reference và ví theo ngày.
- `depth_study/summary.json`, `high_price_study/summary.json`: coverage và quote scenarios.
- `quotes/manifest.json`, `quotes/source_integrity.json`: nguồn book và kiểm tra hash.
- `download_manifest.json`, `report_quality.json`: pin nguồn TWAP và chất lượng reports.

Đã tái lập cả ba nghiên cứu offline, mọi kết quả khớp. Full suite **165 passed,
14 skipped** do source/archive cũ không có. Tests kiểm tra future data, gap,
drawdown theo từng settlement, không dùng lại vốn pending, giá cao, budget,
arrival quote, depth haircut và việc lãi nếu thắng không ngăn lệnh thua.
