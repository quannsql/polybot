# So sánh TWAP mua muộn và mua đủ cặp Up/Down

Ngày nghiên cứu: 08/11/2026. Không đặt lệnh, không sửa chiến lược live.

## Kết luận để quyết định hướng nghiên cứu

**Ưu tiên hướng 1 — oracle TWAP + buffer + giá/depth — cho thử nghiệm tiếp theo.**
Lý do: đã xác minh được dữ liệu cùng nguồn settlement, có thể tạo tín hiệu mà
không cần khớp hai chân. Chưa chứng minh PnL thực thi dương: giá lịch sử quá thưa
và chưa có L2 BTC15m đủ kỳ để đánh giá khả năng mua.

**Hướng 2 khóa rủi ro hướng sau khi sở hữu đủ cặp net shares**, nhưng chưa tìm
được cơ hội mua ngay hai phía có lãi trong mẫu. Chờ mua bằng maker có thể tạo
giá tổng dưới $1, đổi lại queue và rủi ro chỉ khớp một chân. Chưa đủ bằng chứng
để gọi là một bot không thua hoặc chọn triển khai.

Không xếp hạng lợi suất thật giữa hai hướng: TWAP được kiểm tra trên một ngày
BTC15m; L2 hai token chỉ có một market BTC5m ngày khác. Quy mô vị thế cũng khác.
Các kết quả dưới đây đo tính khả thi và điểm nghẽn, không phải một cuộc thi
PnL công bằng trên cùng ngày/universe/điều kiện thực thi.

## Dữ liệu mới đã lấy và đối chiếu

1. Mẫu [PMData Chainlink TWAP60s](https://pmdata.dev/chainlink-twap-data):
   82.743 reports BTCUSD cho ngày 01/09/2026 UTC. Mẫu công khai không cần key;
   các ngày khác theo quyền truy cập/gói của nhà cung cấp.
2. Tải metadata, lịch sử hai outcome, curve phí và settlement official cho
   **96 market BTC15m** của cùng ngày. Cả 96 có Gamma resolved và CLOB winner đồng ý.
3. Chuyển `price` của mẫu trực tiếp từ E18; dùng **observation timestamp và
   receive timestamp** để loại dữ liệu chưa đến nơi vào lúc quyết định.
   Dedupe/loại xung đột còn 82.742 reports sử dụng được.
4. Có **189 điểm đầu/cuối market** đối chiếu được với Gamma `priceToBeat`/`finalPrice`;
   tất cả khớp chính xác ở độ chính xác float đọc được. Metadata cuối chỉ dùng
   audit, không dùng tạo tín hiệu. Thiếu report ở một vài biên không được nội suy.
5. Replay **518.581 events L2 của Vike**, hai token trong một BTC5m ngày 06/11.
   Đi theo receive-order, áp snapshot/delta; status/gap và seq lỗi chặn sử dụng
   tới snapshot mới. Ghi công [Vike, CC BY-NC 4.0](https://vike.io/data/polymarket/historical-data).
6. Đã thử tham số `outcome=No` ở mẫu PMData: trả đúng cùng file/hash với mẫu gốc.
   Không gọi đó là book Down độc lập; không dùng để giả tạo replay hai outcome.

Nguồn schema và scaling: [PMData Chainlink schema](https://pmdata.dev/docs/schemas/chainlink).
Kho dữ liệu local:

- `data/strategy_comparison_20261108/BTCUSD_twap60s.parquet`
- `data/strategy_comparison_20261108/raw/markets/{start}/`
- `data/strategy_comparison_20261108/{oracle_summary,oracle_features,complete_set_replay}.json`
- `data/strategy_followup_20261108/summary.json`

## Hướng 1: TWAP + mua muộn

### Quy tắc đã kiểm tra

- Hướng = dấu của TWAP hiện đã nhận so với report TWAP **đúng đầu market**.
  Opening report phải tới trong 5 giây đầu và trước quyết định.
- Oracle age<=3 giây, trong phút gần nhất cần >=30 reports và không có gap>5 giây.
- 4 mốc T+12:30 / 14:00 / 14:30 / 14:45, 4 buffer cố định 0/5/10/20 bps.
  **5 bps = 0,05%**, là độ nhạy nghiên cứu, không phải xác suất hay ngưỡng tối ưu đã xác nhận.
- Ghi cả 16 cấu hình, không chọn một cấu hình đẹp rồi gọi là validation.
- Chính sách oracle này độc lập với DCA/Variant B. Không thiếu ETH rồi gọi là backtest B.
- Có 379/384 quan sát quyết định hợp lệ: 4 thiếu/nhận muộn report đầu, 1 oracle stale.

### Đúng hướng và giá mua là hai tầng khác nhau

Tầng PnL giả định thêm: ref>=0,85, ref age<=75s, mua ref+0,01 dưới $1, $20 gồm
curve phí per-market rate=0,07/exponent=1. Không có book để xác nhận fill.

| Mốc | Buffer | Đúng hướng trong nhóm oracle | Số giá mua giả định đủ điều kiện | Thắng/thua nhóm mua | PnL giả định |
|---|---:|---:|---:|---:|---:|
| 12:30 | 0 bp | 79/95 | 35 | 29/6 | -$95,82 |
| 12:30 | 10 bp | 50/50 | 19 | 19/0 | +$9,11 |
| 14:00 | 0 bp | 84/95 | 24 | 22/2 | -$20,57 |
| 14:00 | 5 bp | 70/70 | 21 | 21/0 | +$17,92 |
| 14:30 | 5 bp | 68/68 | 2 | 2/0 | +$0,19 |
| 14:30 | 10 bp | 49/49 | **0** | Chưa có lệnh để chấm | **Không xác định** |

49/49 đúng hướng ở 14:30/buffer10bp nhưng không còn giá ref+1c dưới $1 đủ
điều kiện: tín hiệu đúng có thể đi kèm **không có cơ hội mua có lãi**.
Không cộng các hàng: cùng market xuất hiện ở nhiều cấu hình.

### Độ mới giá làm thay đổi bằng chứng

Với 14:00/buffer5bp/ref+1c:

- Cho ref cũ tối đa 75s: 21 giá giả định đủ điều kiện, PnL +$17,92.
- Chỉ cho ref cũ tối đa 15s: **0 điểm đủ mới** để chấm PnL.

Điều này không chứng minh thị trường không có ask lúc đó. Nó cho thấy chuỗi
reference theo phút không đủ kiểm chứng giá mua. Không thể dùng +$17,92 làm
PnL thực thi. Padding0,001 trong sensitivity là một giả thuyết khác, chưa xác
minh tick/depth/khả năng mua sát ref như vậy.

### Buffer có thể bị vượt

Tại T+14:30, biến động tuyệt đối từ TWAP đã nhận tới TWAP cuối:

| Khoảng dữ liệu | Số quan sát có report cuối | Quantile99% trong mẫu | Lớn nhất |
|---|---:|---:|---:|
| 12 giờ đầu | 46 | 4,57 bp | 5,59 bp |
| 12 giờ sau | 46 | 10,01 bp | 12,72 bp |

Đuôi biến động nửa sau lớn hơn rõ rệt. Với ~46 mẫu, quantile99% gần như phụ
thuộc vài điểm lớn nhất; không thể hiệu chuẩn xác suất thua 0,1% bằng một ngày.
70/70 chưa thua trong mẫu không phải bảo đảm tương lai.

TWAP của market có lookback 60 giây. TWAP đang dẫn ở 14:30 vẫn thay đổi đến
15:00. Nguồn: [settlement](https://docs.polymarket.com/concepts/resolution),
[stream TWAP](https://docs.polymarket.com/market-data/realtime-data).

### Độ trễ đã đo được ở nguồn mẫu

Thời gian từ observation tới PMData receive: median **1.356ms**, p99 **2.215ms**,
max **3.991ms**. Đây là độ trễ tại site nhà cung cấp, không phải server của người dùng.
Không bỏ qua receive timestamp rồi coi report tới ngay lúc observation.
RTT REST ~250ms ở capture trước cũng chưa phải latency submit/match.

## Hướng 2: mua đủ cặp Up/Down

### Điều kiện kinh tế

Phải cùng condition/market, đúng token và **số net shares sau phí bằng nhau**:

```text
PnL khóa được sau khi mua đủ cặp = q collateral
                                - cost_Up(q) - cost_Down(q)
                                - merge/relayer/gas/other_costs
```

Không dùng tổng hai giá midpoint hoặc giá last trade. Cần đi hết asks theo q
và phí từng chân, rồi chờ fill reconciliation/merge. Cơ chế:
[complete set và merge](https://docs.polymarket.com/trading/positions/manage).

### Mua ngay hai phía — taker/taker

Mỗi lần đánh giá mua 5 shares mỗi token, dùng L2 thực đã nhận. Lấy một trạng
thái đầu tiên mỗi giây receive-time để tránh đếm hàng trăm nghìn delta như
hàng trăm nghìn giao dịch. Chặn book quá 1,5s/empty/crossed/gap.

| Chỉ tiêu | Kết quả mẫu Vike |
|---|---:|
| Trạng thái theo giây đánh giá được | 386 |
| Cơ hội dương trước phí | **0** |
| Cơ hội dương với rate0,07 | **0** |
| Chi phí thấp nhất để nhận 5 cặp, chưa phí | $5,0500 |
| Chi phí thấp nhất gồm phí mô hình | $5,0603 |
| Chi phí trung vị gồm phí | $5,2236 |

Ngay cả bỏ phí taker, spread đã làm tổng asks vượt payout. Case rate0 chỉ là
độ nhạy phí trên **cùng asks**, không phải mô phỏng đặt maker.
Curve metadata của chính market mẫu tải official hiện tại cũng là rate0,07/exponent1;
đó vẫn chưa phải attestation phí tại từng match lịch sử. Chưa gồm merge/gas.

386 trạng thái là **một market BTC5m**, không phải 386 cơ hội độc lập hoặc một
backtest nhiều ngày. Cũng không chứng minh market khác không có arbitrage.

### Chờ khớp maker — khả năng khác nhưng có rủi ro tồn kho

Maker không bị taker fee theo [tài liệu phí](https://docs.polymarket.com/trading/fees).
Ví dụ minh họa: mua maker Up0,49 + Down0,50 => tổng0,99, còn0,01 mỗi cặp
trước chi phí khác **nếu cả hai khớp đủ**. Nếu chỉ Up khớp rồi về $0 thì mất0,49/share,
xóa 49 lần lãi0,01. Nếu hedge Down bằng taker ở giá xấu hơn thì có thể khóa lỗ.

Đã replay 8 kịch bản queue cố định: đặt tại T+5/60/120/180s, latency250/1000ms,
5 shares/token, hết hạn30s. Chỉ SELL print đúng giá mới tiêu thụ queue trước
và tới phần fill giả định; không tính hủy/rút size thành fill. Không tính rebate.

- 4 kịch bản bị gap/status làm mất khả năng xác minh queue.
- 4 kịch bản có một chân sẽ cross sau latency, nên post-only có thể bị từ chối.
- **Chưa xác nhận được khớp đủ cặp**. Không suy ra win-rate0%, không coi 8 kịch
  bản là 8 giao dịch thực. Trong hệ thống thật chân còn lại có thể đã được nhận,
  nên còn cần cancel/hedge và xử lý trạng thái không chắc chắn.
- Queue priority thực tế, lệnh mới chen vào và mức market impact chưa được chứng minh.

Hai FOK riêng không phải một giao dịch nguyên tử. [FOK](https://docs.polymarket.com/trading/place-orders)
chỉ bảo đảm phạm vi một order, không bảo đảm hai order cùng khớp.

## So sánh cho mục tiêu vốn nhỏ, lãi nhỏ, hạn chế thua

| Tiêu chí | 1. TWAP + buffer | 2. Mua đủ cặp |
|---|---|---|
| Nguồn lợi nhuận | Khả năng dự báo cao hơn chi phí mua | Tổng chi phí sở hữu cặp thấp hơn collateral merge |
| Rủi ro giá BTC | Có tới settlement | Hết rủi ro hướng sau khi sở hữu đủ cặp net shares |
| Rủi ro thực thi | Một chân mua, quote/latency | Hai chân, partial/unmatched inventory, cancel/hedge/merge |
| Bằng chứng hiện có | Có tín hiệu oracle; PnL chỉ giả định | Chưa có taker pair dương; maker chưa xác nhận đủ cặp |
| Điểm nghẽn | Giá mua khi tín hiệu đã rõ, calibration đuôi | Mua được đủ rẻ ở cả hai chân |
| Ưu tiên nghiên cứu | **Trước** | Scanner song song; chưa bật executor hai chân |
| Đã chứng minh có lợi nhuận thật? | Chưa | Chưa |

Không tối ưu riêng win-rate: có thể 100% trên mẫu nhỏ mà thu nhập rất ít hoặc
không có giá mua. Mục tiêu đo tiếp là PnL ròng/vốn/thời gian cùng drawdown,
coverage, fill rate và worst-case loss trên cùng universe.

## Công việc tiếp theo có thể quyết định bằng dữ liệu

1. Ghi **cùng BTC15m**, cùng khoảng 14–30 ngày: market rules/tick/fees, opening
   TWAP/PTB nhận lúc đầu, reports TWAP, hai token L2, gap/seq, timestamps nhận.
   Đây là yêu cầu dữ liệu nghiên cứu, không phải bảo đảm 30 ngày đủ xác nhận99,9%.
2. Khóa hai cấu hình oracle 14:00/14:30, buffer5/10bp như đối chứng, không chọn
   lại ngưỡng sau khi xem thua. Lấy calibration đuôi từ dữ liệu trước, kiểm tra
   riêng theo ngày/biến động trên giai đoạn sau.
3. Trên cùng replay, scanner pairs chỉ báo đủ điều kiện khi **net cost cả hai
   chân + chi phí khác đo được < payout**, còn dư buffer và đủ depth. Chi phí
   merge chưa biết phải ghi unknown, không tự gán0 để cho pass.
4. Replay arrival latency và FOK capacity; maker phải có queue/timeout/hedge
   riêng. Báo unmatched exposure, không chỉ matched pair margin.
5. Mỗi market/policy chỉ một quyết định; report repeated quotes thành episode,
   không tăng n bằng polling. Mỗi chiến lược một ví $50/stake<=20 độc lập.
6. Chỉ sau đó so sánh return on capital/day, PnL ròng, drawdown, expected shortfall,
   số cơ hội đủ dữ liệu, fill rate và inventory duration. Không cộng PnL các scenario.

PolyBolt TWAP hiện hành yêu cầu xác thực trước subscribe; code RTDS topic cũ
trong repo không được mặc định coi là đã tương thích. Không tạo credential,
đọc private key hoặc gọi executor trong nghiên cứu này. Lịch sử TWAP nhiều
ngày cần nguồn có quyền truy cập; hiện chỉ dùng sample miễn phí.
[PolyBolt authentication và stream](https://docs.polymarket.com/market-data/realtime-data).

## Tái lập

```powershell
# Sau đợt tải đầu, không cần gọi mạng để tái lập kết quả
.\.venv-research\Scripts\python.exe -B research_strategy_comparison.py --offline
.\.venv-research\Scripts\python.exe -B research_comparison_followup.py
```

Protocol/hash được lưu trước chấm; followup ghi rõ là sensitivity sau khi đã xem
mẫu đầu. Source thay đổi phải giữ run cũ. Full suite: **148 passed, 14 skipped**;
skip do source/archive cũ không có. Tests mới chặn nhìn tương lai, opening nhận
muộn, oracle gap, book gap/seq, queue và sai khác reference freshness.
