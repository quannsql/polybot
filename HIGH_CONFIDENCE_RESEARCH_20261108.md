# Mua muộn, lãi nhỏ và mục tiêu không thua

Ngày nghiên cứu: 08/11/2026. Chỉ nghiên cứu offline từ dữ liệu đã tải, không thay
cấu hình thực thi. Code: `research_high_confidence.py`, `research_complete_sets.py`.

## Kết luận

Chưa có cơ sở để bảo đảm 100% thắng cho chiến lược mua một outcome trước khi
kết quả được xác định. Có thể giảm số cơ hội, mua muộn hơn và chấp nhận lãi nhỏ,
nhưng vẫn phải kiểm chứng rủi ro đảo chiều, source settlement và giá có thể khớp.
Đã tìm thấy các nhóm chưa thua trong mẫu; không chuyển những nhóm đó thành lời
hứa không thua tương lai hoặc tự đổi bot live.

## Đã kiểm tra những gì

- 289 market DCA có dữ liệu tháng 10 từ đợt tải trước, không chỉ 61 lệnh baseline.
- Giữ hướng DCA ban đầu. Chấm theo settlement Polymarket đã xác nhận và curve phí market.
- 7 mốc: T+12:30, 13:00, 13:30, 14:00, 14:30, 14:45, 14:55.
- 5 ngưỡng tham chiếu: 0,85 / 0,90 / 0,95 / 0,97 / 0,99.
- Padding giả định 0,01 hoặc 0,001; age<=75s hoặc <=15s.
- Không lọc, Z>=2, Z>=3, hoặc Z>=3 và vol5/vol60<=1,5.
- Tổng **560 cấu hình**. Ghi protocol và hash trước khi chấm lần này, nhưng dữ liệu
  tháng 10 đã được xem ở lượt trước: toàn bộ là nghiên cứu thăm dò trên dữ liệu tái dùng.
- Z dùng Lighter và nến đã đóng; không phải xác suất thắng. Không có ETH nên
  không gọi các cấu hình này là Variant B đầy đủ.
- Không dùng Gamma `eventMetadata.finalPrice` hoặc outcome/settlement làm tín hiệu.
  Đây là dữ liệu hậu nghiệm. Winner chỉ dùng để chấm điểm.

Đầu ra: `data/high_confidence_20261108/{protocol,summary,results}.json`,
`results.csv`, `trades.csv`. Có thể chạy lại offline bằng Python script ở trên.

## Một số đối chiếu dễ hiểu

Tất cả dùng $20/lệnh gồm phí, giả định đủ vốn, không phải giá đã khớp.

| Mốc vào | Ref tối thiểu | Tuổi ref tối đa | Padding | Thắng/tổng giả định mua | PnL | Lãi TB lệnh thắng |
|---|---:|---:|---:|---:|---:|---:|
| 12:30 | 0,85 | 75s | 0,01 | 57/61 | -$28,91 | $0,8964 |
| 12:30 | 0,95 | 75s | 0,01 | 31/33 | -$29,53 | $0,3377 |
| 14:00 | 0,95 | 75s | 0,001 | 67/68 | -$6,37 | $0,2034 |
| 14:30 | 0,95 | 75s | 0,01 | 13/13 | +$5,46 | $0,4198 |
| 14:30 | 0,95 | 75s | 0,001 | 70/70 | +$11,70 | $0,1671 |
| 14:30 | 0,95 | 15s | 0,001 | 62/62 | +$10,53 | $0,1698 |
| 14:45 | 0,95 | 75s | 0,001 | 71/71 | +$11,78 | $0,1659 |

Tăng ngưỡng ref tại 12:30 lên 0,95 đã giảm lợi nhuận mỗi lần thắng nhưng vẫn có
2 lệnh thua. Tăng giá mua không tự động loại bỏ lệnh thua.

Không cộng các hàng với nhau: nhiều cấu hình dùng trùng market. Mỗi mốc/ngưỡng
thay đổi tập cơ hội, không chứng minh cùng một lệnh thua trở thành thắng khi đợi lâu.

**Padding 0,001 là giả thuyết thực thi khác**. Bot hiện tại dùng trần ref+0,01,
làm tròn xuống theo tick. Những con số padding 0,001 chưa kiểm tra tick/ask/depth
lịch sử và không phải bằng chứng lệnh có thể khớp sát ref đến thế.

Với 14:45/ref>=0,95/pad0,001: có 115 tham chiếu đạt điều kiện, chỉ 71 giá giả
định dưới $1; 44 còn lại ghi nonfill giá>=1. Trên toàn grid, 294 cấu hình có
ít nhất một lệnh và chưa thua trong mẫu, phần lớn dùng các mẫu trùng nhau.
Không được chọn một trong số đó sau khi xem bảng rồi gọi là xác nhận độc lập.

## Ví dụ 100% ở phần đầu không lặp lại ở phần sau

Quy trình chọn cố định: chỉ dùng trước 15/10, n>=20, chưa thua và PnL dương;
ưu tiên nhiều mẫu nhất, rồi padding nhỏ và ID. Quy trình chọn:

`d810_ref0.85_pad0.001_age75_none` — vào 13:30, giữ ref>=0,85.

| Giai đoạn | Thắng/tổng | PnL |
|---|---:|---:|
| 01–14/10 | 56/56 = 100% | +$46,71 |
| 15–25/10 | 33/35 = 94,29% | -$22,96 |

Đây vẫn là chia theo thời gian trên dữ liệu đã xem, không phải holdout sạch.
Nó minh họa trực tiếp vì sao chưa thua ở phần đầu chưa đủ để suy ra phần sau.

## Lãi càng nhỏ, yêu cầu độ tin cậy càng cao

Tính với rate=0,07, exponent=1, $20 gồm phí, một giá mua, chưa có chi phí khác:

| Giá thực mua giả định | Lãi nếu thắng | Thua | Win-rate hòa vốn | Số lệnh thắng bù 1 thua |
|---|---:|---:|---:|---:|
| 0,96 | $0,7752 | -$20 | 96,2688% | 26 |
| 0,98 | $0,3796 | -$20 | 98,1372% | 53 |
| 0,99 | $0,1879 | -$20 | 99,0693% | 107 |
| 0,995 | $0,0935 | -$20 | 99,5348% | 214 |
| 0,999 | $0,0186 | -$20 | 99,9070% | 1.075 |

Các mức giá là phép tính kinh tế, không chứng minh tick/khả năng khớp hoặc xác
suất thật. Con số $0,775 là ví dụ mua đúng giá 0,96, không phải lãi bình quân
đã đo của mọi lệnh bot. [Công thức phí](https://docs.polymarket.com/trading/fees).

Ví dụ 71/71 tại 14:45 chỉ lãi $11,78 cả mẫu. Đổi lệnh thắng có payout lớn nhất
thành thua làm PnL còn **-$9,08**. Một lần thua có thể xóa hơn toàn bộ lãi mẫu.

## Cỡ mẫu không chứng minh xác suất bằng 1

Nếu một quy tắc đã cố định, các giao dịch độc lập/cùng phân phối và có n thắng,
0 thua, cận dưới một phía 95% chính xác cho win probability là `0.05**(1/n)`.

- 71/71 => khoảng **95,87% trở lên**, không phải xác suất thật bằng 100%.
- 281/281 => khoảng **98,94% trở lên** trong giả định trên. B được chọn hậu nghiệm
  nên không dùng phép tính này như chứng nhận thống kê của B.
- Muốn cận dưới đạt 99,9% cần ít nhất **2.995 thắng liên tiếp**, sau khi khóa
  quy tắc, với các giả định thống kê nêu trên. Vẫn không chứng minh 100%.

Phụ thuộc theo market/ngày, đổi chế độ, chọn giữa 560 cấu hình làm độ tin cậy
kém hơn cách tính một quy tắc cố định. Các cận này chỉ minh họa lượng bằng chứng.

## Các hướng kỹ thuật đáng kiểm chứng

### A. Oracle/TWAP cùng nguồn và chỉ giao dịch khi có buffer lớn

1. Ghi price-to-beat từ đầu market với timestamp nhận; không lấy metadata cuối
   market rồi giả vờ đã biết giá đó trước khi vào.
2. Dùng Chainlink TWAP đúng stream của settlement, ghi raw update, seq/gap và
   timestamp. Feed hiện hành có TWAP lookback 60 giây; một TWAP đang dẫn ở 14:30
   chưa phải TWAP cuối lúc 15:00.
3. Ước lượng phân phối đảo chiều của **TWAP cuối so với quan sát đã biết** trong
   30/15 giây còn lại bằng dữ liệu mới; dùng quantile đuôi và buffer cho độ trễ.
   Không biến Z của Lighter hoặc phân phối chuẩn thành xác suất thắng đã hiệu chuẩn.
4. Shadow các mốc 14:00 và 14:30; chỉ thêm 14:45/14:55 sau khi có stream subsecond
   và đo được feature/quote/submit latency. Thiếu stream/gap thì bỏ cơ hội.
5. Chỉ cho qua khi cận xác suất đã kiểm chứng đủ vượt chi phí mỗi share và buffer
   vận hành, đồng thời vẫn có depth trong trần. Lọc rủi ro và lọc giá là hai điều kiện riêng.

Nguồn: [settlement TWAP](https://docs.polymarket.com/concepts/resolution),
[TWAP stream](https://docs.polymarket.com/market-data/realtime-data).

Đây là hướng thiết kế để giảm xác suất thua, chưa thể backtest oracle chuẩn vì
chưa có stream lịch sử đúng kỳ. Một TWAP trung bình ở hiện tại không cho phép
tái tạo chính xác phần tích lũy của TWAP cuối nếu không biết đúng observation/weight.
Ngay cả có buffer lớn vẫn còn biến động đuôi, feed stale và thời gian thực thi.

### B. Khóa payout bằng complete set, nếu mua được đủ rẻ

Với cùng market, mua **q shares Up và q shares Down**, một complete set có thể
merge lại thành q đơn vị collateral. Nếu tổng giá mua, phí, gas/merge và các chi phí
khác nhỏ hơn q, phần chênh lệch không phụ thuộc hướng BTC **sau khi đã sở hữu đủ cặp**.
Đây là điều kiện arbitrage khác với tín hiệu dự đoán. Mua $10 mỗi phía thường
không tạo số shares bằng nhau nên không tự động khóa payout như vậy.
[Cơ chế complete set/merge](https://docs.polymarket.com/concepts/positions-tokens).

Đã sàng 141 cặp quote gần thời gian từ capture trước, thuộc **một market**:
không có cặp nào dương sau phí với 5 shares mỗi outcome. Cặp tốt nhất vẫn lỗ
$0,1082 trước chi phí khác. Đây là quote GET không đồng thời, không phải 141
lần gửi lệnh, không chứng minh thị trường khác không có cơ hội.

Hai lệnh FOK riêng không bảo đảm hai phía cùng khớp. Nếu chỉ một phía khớp thì
vẫn có rủi ro hướng. Không hứa "arbitrage không rủi ro" trước khi cặp đã được
khớp đủ/đối soát và merge thành công. [Quy tắc đặt lệnh](https://docs.polymarket.com/trading/place-orders).

### C. Chờ kết quả chính thức

Khi market đã resolved thì biết winner, nhưng trading dừng, không còn một cơ
chế chung để đợi biết chắc rồi mua rẻ hơn payout. Có thể có các khoảng trễ thị
trường đã biết kết quả nhưng chưa đóng; cần kiểm tra rule, khả năng khớp và rủi
ro vận hành riêng, không coi đó là lợi thế được bảo đảm.
[Sau resolution](https://docs.polymarket.com/concepts/resolution).

## Bước tiếp theo hợp lý

Ưu tiên một thử nghiệm shadow oracle/TWAP 14:30, giữ ngân sách và trần giá
thành cấu hình nghiên cứu riêng, ghi tất cả market bị bỏ và lý do. Cấu hình
thử nghiệm chỉ được đánh giá bằng dữ liệu mới sau khi khóa; chưa đổi bot live.
Tiêu chí cần tối ưu là rủi ro thua và PnL sau phí cùng khoảng bất định, không
chỉ số "100%" của nhóm nhỏ nhất sau nhiều phép thử.

Kiểm thử mới: 8 tests passed cho causality, dữ liệu thiếu, kế toán giá cao,
nonfill, source settlement không làm đổi entry, chi phí hai phía và depth thiếu.
