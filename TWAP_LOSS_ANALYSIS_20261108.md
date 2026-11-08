# Phân tích 3 lệnh TWAP thua và khả năng thoát sớm

Phạm vi: đúng mô hình **116 thắng /119 lệnh, +$22,56 trong tuần15–21/08/2026**,
$20/lệnh, giả định đủ vốn, mua theo historical reference+1cent. Đây là các lệnh
trong mô phỏng; chưa có119 fills thực được xác nhận. Không đổi runtime, không
gửi lệnh, không mua dữ liệu.

**Kết quả đáng chú ý:** tại thời điểm mua của cả3 lệnh thua, giá spot Chainlink
đã yếu hơn TWAP theo hướng đang mua. Bộ lọc spot củng cố TWAP giữ66 lệnh thắng,
loại3 lệnh thua và50 lệnh thắng, PnL tham chiếu còn+$47,32. Tuy nhiên đây là
phát hiện hồi cứu sau khi đã biết các lệnh thua, chưa phải bằng chứng thắng tuyệt
đối. Giá mua/khả năng khớp vẫn là giới hạn lớn nhất.

Với thoát sớm, cảnh báo spot vượt mốc bất lợi xuất hiện ở cả3 lệnh thua, nhưng
cũng ở6 lệnh cuối cùng vẫn thắng. Chỉ một lệnh thua có bid trùng kỳ; tại cảnh
báo đó bid còn0,24. Hai lệnh thua còn lại thiếu book, nên **PnL bán sớm cả tuần
chưa xác định**.

## Dữ liệu và phương pháp

- Giữ nguyên TWAP60s, market official, reference và phí của nghiên cứu tuần.
- Tải thêm14 ngày **Chainlink spot** cùng publisher/revision:1.151.517 reports
  thô,1.151.493 unique usable;24 duplicate đồng ý giá,0 timestamp xung đột.
- Nguồn public [PMData/mileswangs](https://huggingface.co/datasets/mileswangs/polymarket-btc-updown-5m-orderbook-tick-data),
  CC BY4.0, revision `acb8cecf4234677823ddd8ee1275de1db48aa995`;14 file spot
  khớp LFS SHA256. Spot chỉ là tín hiệu cảnh báo; settlement vẫn theo TWAP.
  [Schema nguồn](https://pmdata.dev/docs/schemas/chainlink).
- So sánh8 rule entry cố định và4 rule thoát; không dò hàng trăm ngưỡng để
  loại đúng3 lệnh thua. Protocol khóa trước khi chấm dữ liệu spot/diễn biến mới.
- **Toàn bộ là nghiên cứu post-hoc**: đã nhận diện ba lệnh thua và từng xem kỳ
  tháng08. Không gọi tuần này hoặc tuần08–14/08 là holdout mới độc lập.
- Tuần trước có103/103 lệnh thắng trong baseline, nên gần như không cung cấp
  ví dụ thua để kiểm chứng khả năng phát hiện đuôi rủi ro.
- Mỗi quyết định chỉ dùng reports có observation và receive timestamp không
  sau thời điểm quyết định; report mới tuổi<=3s. Mốc đầu đúng report đầu market,
  nhận trong5s; kiểm tra tính liên tục TWAP như nghiên cứu trước.
- Outcome official chỉ dùng chấm điểm. Không dùng final price để phát sinh
  tín hiệu trước khi đóng market. Trong7.021 tick giám sát sau entry có16 tick
  TWAP không đạt chất lượng; thêm1 tick có TWAP nhưng thiếu spot mới. Khi thiếu
  dữ liệu, confirmation reset và mô hình giữ vị thế, không tự tạo giá.

## Ba lệnh thua cụ thể

Giờ trong bảng là **giờ mua giả định tại Việt Nam**, không phải giờ bắt đầu
market. Khoảng dẫn dương nghĩa là đang có lợi cho phía đã mua;1bp=0,01%.

| Entry Việt Nam | Phía mua | Giá mua giả định | TWAP dẫn mốc đầu | Spot dẫn cùng mốc | Spot yếu hơn TWAP |
|---|---|---:|---:|---:|---:|
|17/08 12:14|Down|0,935|6,30bp|1,18bp|5,12bp|
|20/08 02:14|Up|0,905|5,79bp|4,83bp|0,96bp|
|20/08 02:29|Up|0,985|12,49bp|7,79bp|4,70bp|

Lệnh1: TWAP còn thấp hơn mốc đầu khoảng$40, nhưng spot chỉ thấp hơn khoảng$7,49.
TWAP đang tăng ngược hướng Down: động lượng30s signed=-4,21bp. Cảnh báo đã có
trước khi mua; chỉ nhìn khoảng dẫn6,30bp sẽ đánh giá thiếu rủi ro.

Lệnh2: động lượng TWAP30s vẫn dương nhẹ, nhưng spot đã thấp hơn TWAP. Sau mua
khoảng10s, spot vượt sang phía bất lợi và tiếp tục giảm mạnh. Đây là ví dụ một
shock mới sau entry; không thể tuyên bố bộ lọc đã biết chắc nó sẽ xảy ra.

Lệnh3: khoảng dẫn TWAP khá lớn12,49bp và động lượng30s vẫn dương, nhưng spot
đã yếu hơn TWAP4,70bp. Sau đó TWAP giảm dần, chỉ báo động cắt mốc đầu xác nhận
ở14:59. Tăng buffer lên10bp vẫn không loại được lệnh này.

![Diễn biến ba lệnh thua](D:/polybot/data/twap_loss_audit_20261108/loss_paths.png)

Biểu đồ trái: xanh là khoảng dẫn TWAP; cam là khoảng dẫn spot, cùng quy về phía
đã mua. Đường tím là entry14:00; đỏ là cảnh báo spot-cross sau confirmation.
Tiêu đề ghi giờ bắt đầu market Việt Nam. Biểu đồ phải chỉ chấm bid quan sát
được, không nối qua khoảng thiếu và không giả định các ngày thiếu book có giá0.

## Bộ lọc trước khi mua

Các rule mới áp trên cùng119 cơ hội tham chiếu gốc, không bổ sung market mới.
Mỗi hàng độc lập, không cộng PnL giữa các hàng.

| Rule | Tuần08–14/08: giữ /103 | Tuần15–21/08: thắng/tổng | Loại lệnh thua | Loại lệnh thắng | PnL tham chiếu tuần, $20/lệnh |
|---|---:|---:|---:|---:|---:|
|Baseline14:00, buffer5bp|103|116/119|0|0|+$22,56|
|Buffer10bp|16|53/54|2|63|+$15,79|
|TWAP momentum10s cùng hướng|65|74/75|2|42|+$34,51|
|TWAP momentum30s cùng hướng|64|75/77|1|41|+$16,57|
|Ngoại suy TWAP slope30s vẫn đúng phía khi hết hạn|103|110/112|1|6|+$38,06|
|Spot vẫn đúng phía mốc đầu|103|116/119|0|0|+$22,56|
|**Spot không yếu hơn TWAP theo hướng mua**|61|**66/66**|**3**|**50**|**+$47,32**|
|Primary khóa trước: spot đúng phía + momentum30s cùng hướng|64|75/77|1|41|+$16,57|

Động lượng là thay đổi TWAP từ report có thể biết10/30s trước tới report hiện
đã nhận, signed theo hướng mua. Ngoại suy slope chỉ là giả thuyết tuyến tính,
không phải công thức Chainlink hoặc xác suất thắng.

Rule **spot không yếu hơn TWAP** được viết rõ:

- Xét mua Up khi TWAP vượt mốc đầu>=5bp **và spot>=TWAP hiện tại**.
- Xét mua Down khi TWAP dưới mốc đầu>=5bp **và spot<=TWAP hiện tại**.
- Vẫn phải qua kiểm tra dữ liệu, giá mua, phí, trần giá, depth và vốn.

Cơ chế hợp lý để nghiên cứu: TWAP phản ánh một phút vừa qua; spot yếu đi có
thể báo rằng phần giá mới đi vào cửa sổ TWAP sẽ bất lợi. Đây là suy luận từ
cấu trúc cửa sổ và dữ liệu, không bảo đảm đường giá tương lai.

**Không đổi primary sau khi nhìn thấy66/66.** Primary định trước vẫn còn2
lệnh thua và PnL thấp hơn baseline. Rule spot-vs-TWAP là ứng viên secondary
đáng kiểm chứng tiếp, không được biến thành tuyên bố đã tìm ra100% thắng.
Ngay lệnh2, chênh lệch spot/TWAP chưa tới1bp, nên độ trễ và timestamp rất đáng kể.

## Bán sớm: cảnh báo đúng chưa đủ, cần giá bán của cả lệnh thắng

Mô hình giám sát từng giây từ14:01 tới14:59. Chỉ báo động sau3 observations
nguồn khác nhau thỏa điều kiện liên tiếp, gap<=5s; không đếm một report ba lần.

| Rule thoát | Báo động ở3 lệnh thua | Báo động ở116 lệnh cuối cùng thắng | Thời điểm báo động của lệnh1 /2 /3 |
|---|---:|---:|---|
|Spot sang phía bất lợi của mốc đầu|3|6|14:10 /14:10 /14:24|
|TWAP mất một nửa khoảng dẫn lúc mua|3|10|14:22 /14:20 /14:40|
|Ngoại suy slope30s sang phía bất lợi|3|7|14:05 /14:19 /14:45|
|TWAP cắt mốc đầu sang phía bất lợi|3|0 trong mẫu|14:53 /14:26 /14:59|

Rule TWAP-cross ít báo động nhầm trên mẫu này nhưng có thể quá muộn để thu
hồi đáng kể vốn. Rule spot-cross sớm hơn nhưng bán6 lệnh đang âm tạm thời rồi
cuối cùng thắng; cần tính khoản lãi bị bỏ/mức lỗ chốt trên cả6 lệnh đó.

### Lệnh1 có bid: mức giảm lỗ chỉ là giá trị có điều kiện

Giữ nguyên số shares giả định đã mua theo reference0,935+$fee, stake20:

| Cảnh báo | Clock từ đầu market | Bid mới quan sát được tới arrival+500ms | PnL nếu bán được đủ shares tại bid đó |
|---|---|---:|---:|
|Ngoại suy30s bất lợi|14:05|0,19|-$16,19|
|Spot-cross|14:10|0,24|**-$15,17**|
|TWAP mất nửa lead|14:22|0,05|-$19,02|
|Giữ tới thua settlement|15:00|Không áp dụng|-$20,00|

Tại spot-cross, khoản thu hồi so với giữ tới thua khoảng**$4,83**. Chưa có bid
size trong nguồn GitHub nên **không xác nhận có thể bán đủ shares**. Đây không
phải trade receipt; clock giữa nhà cung cấp quote và oracle chưa được chứng nhận.
Bid sau một cảnh báo sớm hơn không nhất thiết tốt hơn: trong mẫu,0,19 lúc14:05
thấp hơn0,24 lúc14:10.

Hai lệnh thua ngày19/08 UTC không có book trùng kỳ. Trong9 spot-cross alerts,
chỉ1 có bid benchmark ở scenario500ms,8 không có market book. Vì vậy không
cộng khoản thu hồi giả định của3 lệnh thua thành PnL bán sớm cả tuần.

Các tính toán bán trừ fee trên proceeds và overhead giả định$0,01/exit. Công
thức venue là `shares * rate * p * (1-p)`; tham số từ metadata từng market tải
hiện tại, không phải attestation phí lúc khớp lịch sử. [Polymarket fees](https://docs.polymarket.com/trading/fees).
Mô phỏng yêu cầu quote **mới sau cảnh báo và không sau arrival**, thử500/1000ms,
clock±1000ms; không lấy snapshot tương lai để lấp khoảng trống.

### Stop theo giá10% không có nghĩa chỉ lỗ tối đa10%

Kiểm tra riêng ngưỡng net bid thấp hơn90% chi phí vào lệnh cho2 cảnh báo quan
sát:1 lệnh thua,1 lệnh sau cùng thắng. Không market nào có đủ chuỗi bid hợp lệ
liên tục dưới giới hạn gap1,5s trong cả phút giám sát. Vì thế không coi các
market còn lại là không chạm stop; PnL stop cả tuần để `null`.

Ở lệnh1, stop đã bị vượt ngay capture đầu sau entry, bid0,48. Với arrival1s
và snapshot mới, bid chỉ còn0,46; nếu đủ khối lượng, PnL có điều kiện là
**-$10,59**, vượt xa mức lỗ$2 tương ứng10% stake20. Đây cũng bộc lộ vấn đề giá
tham chiếu cũ, không phải chứng minh stop10% giới hạn được thiệt hại.

## Giá mua giả định vẫn là giới hạn quan trọng

Cả3 reference entry cũ49–50s. Ví dụ lệnh1:

- History reference0,925; mô hình mua0,935 tại14:00.
- Capture14:00,121s có ask Down0,49 và bid0,48; trước đó khoảng1s ask0,53.
- Ask size tốt nhất21 shares; chưa đủ để mua stake20 với haircut50% tại mức
  giá đó. Không biết depth sâu hơn; không kết luận chắc chắn FOK sẽ fail.

Như vậy cả giá mua lẫn số shares thực tế có thể khác đáng kể mô hình. Kiểm
tra lại119 entry với cap reference+1c cũ, arrival500ms, capture<=1,5s và50%
top depth chưa có trường hợp đủ bằng chứng capacity. Có81 market thiếu book;
phần còn lại gồm book một phía/crossed, thiếu refresh, ask vượt cap, stale hoặc
thiếu top size. Đây là **không xác nhận được**, không phải119 nonfills thực tế.

Ngay ứng viên66/66 vẫn43 market thiếu book,15 quote không hợp lệ/one-sided,
4 thiếu arrival refresh,3 ask vượt cap,1 stale. **+$47,32 chưa phải PnL thực thi.**
Định giá mua thực phải chạy lại theo ask và depth; bán theo bid và depth, với
phí hai chiều. [Order lifecycle](https://docs.polymarket.com/concepts/order-lifecycle).

## Kiểm soát đơn giản đã có trước nghiên cứu mới

Không cần lọc riêng những timestamp đã biết thua: rule dừng sau một lệnh thua
đã được giả định biết kết quả trong ngày có thể tránh lệnh thua thứ hai liền kề.
Với ví50, stake20, redemption giả định5 phút, giữ baseline buffer5bp:

- 100 lệnh được lấy:98 thắng,2 thua;19 cơ hội bị dừng.
- PnL mô hình **+$30,70 cả tuần**, thay vì+$22,56 không dừng.
- Max realized drawdown vẫn**$25,52**, ngày tệ nhất**-$17,08**.

Dừng sau thua cũng bỏ các lệnh thắng, và có thể làm PnL tệ hơn ở kỳ khác. Lệnh
thua đầu phải được biết trước entry tiếp theo; không dừng dựa trên outcome mà
bot chưa thể biết. Không cộng PnL của rule này với các bộ lọc entry khác.

## Việc nên kiểm chứng tiếp

1. Giữ baseline và rule secondary spot-vs-TWAP chạy shadow trên một kỳ mới đã
   khóa trước; theo dõi cả cơ hội bị bỏ, không sửa ngưỡng để đạt100% mẫu cũ.
2. Theo dõi spot-cross3 observations như cảnh báo thoát sớm. Việc quyết định
   bán cần giá bid đủ mới và bid depth; không đợi tới TWAP-cross rồi mặc định
   vẫn thoát được gần giá mua.
3. Tải/ghi đủ BTC15m L2 và timestamp cho các ngày có shock/lệnh thua. Nguồn
   hiện tại không đủ xác nhận giá bán2 trong3 lệnh thua hoặc PnL thoát cả tuần.
4. Trước live, đo ask entry, bid exit, phí hai chiều, latency, FOK acknowledgments,
   partial/failed exits, vốn pending và daily stop; không dùng giá history
   một phút để thay thế book ở điểm vào/ra.

## Artifacts và kiểm thử

```powershell
# Chỉ lệnh đầu tải public data; các lệnh sau đọc cache, không gửi lệnh
.\.venv-research\Scripts\python.exe -B download_twap_loss_data.py
.\.venv-research\Scripts\python.exe -B research_twap_loss_audit.py
.\.venv-research\Scripts\python.exe -B plot_twap_loss_audit.py
```

- `data/twap_loss_audit_20261108/protocol.json`: họ giả thuyết post-hoc cố định.
- `summary.json`, `losses.csv`: kết quả và3 lệnh thua.
- `candidate_trades.csv`: toàn bộ222 cơ hội của hai tuần và mọi entry filter.
- `exit_details.json`, `paths.json`: cảnh báo trên toàn bộ119 lệnh, kể cả winners.
- `run_manifest.json`: hash1.378 source artifacts; `spot_manifest.json`: nguồn mới.
- `loss_paths.png`, `loss_paths.svg`: biểu đồ độc lập.
- `verification.json`: kiểm tra tái lập và checksum.

Full suite **179 passed,14 skipped** vì source/archive cũ không có. Các tests
mới kiểm tra không dùng future/late-received data, dấu hướng Up/Down, confirmation
theo observations khác nhau, quote mới sau tín hiệu, thiếu depth, thiếu book,
phí hai chiều và không giả định bán được sau giờ đóng. Không đổi logic bot live.
