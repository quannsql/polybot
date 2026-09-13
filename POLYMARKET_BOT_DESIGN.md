# Thiết kế Bot 2 — BTC Up/Down 15m

> Thiết kế ban đầu. Kiểm tra và số liệu mới nhất tại
> [RESEARCH_REVIEW_20260913.md](RESEARCH_REVIEW_20260913.md).
> Các số 1.113/54,99% bên dưới đã được thay thế sau sửa warmup.
> Runtime hiện là prototype; chưa có ledger/settlement và reconciliation đầy đủ.

## Mục tiêu

Bot 2 dự đoán **kết quả của từng market 15 phút**, không mở vị thế perpetual.
Một market chỉ có hai outcome `Up`/`Down`; token thắng đổi được thành 1 pUSD,
token thua về 0. Vì vậy bài toán đúng là:

```text
P(model thắng | dữ liệu tại thời điểm vào)
    > giá best ask + fee + spread/slippage dự phòng
```

Win rate của một chu kỳ DCA trên Lighter không phải là xác suất nhị phân của
15 phút kế tiếp.

## Tín hiệu được tái sử dụng từ Bot 1

Chỉ lấy phần quan sát hướng, giữ đúng quy ước nến đã đóng:

1. **Main 5m**: route ngày dùng SMA25 của close ngày hoàn tất; SHORT khi close
   hôm trước thấp hơn SMA 1,5%, còn lại LONG. Trên nến 5m vừa hoàn tất, LONG
   khi close ≤ BB20 lower; SHORT khi close ≥ BB20 upper.
2. **Auxiliary SHORT 15m**: close 15m ≥ BB20 upper và return 60 phút ≥ 60 bp.
   Lane này được xét trước main vì Bot 1 cũng sở hữu nó riêng.

Không mang sang DCA, leverage 20x, SL 200 bp, runner, TP hay time-stop. Những
thành phần đó quản lý payoff của perp; binary market không có cùng trạng thái.

## Causal contract

- Decision time là biên UTC 15 phút, sau một delay nhỏ để Gamma tạo market.
- Chỉ sử dụng 5m đã đóng tại biên đó; không dùng candle đang hình thành.
- Signal feed hiện là Binance public OHLCV để Bot 2 chạy độc lập. Trước khi
  calibration production phải đối chiếu chênh lệch Lighter/Binance và thay bằng
  một adapter Lighter nếu cần tái tạo tuyệt đối Bot 1.
- Resolution không lấy Binance: market metadata phải chứa Chainlink rules và
  token IDs. RTDS Chainlink 60s là nguồn cần dùng cho nghiên cứu resolution.

## Cơ chế chọn lệnh

`PolymarketPublic` lấy event theo slug:

```text
btc-updown-15m-{unix_window_start}
```

Sau đó xác minh title, một market duy nhất, outcomes, `conditionId`,
`clobTokenIds`, `active`, `closed`, `acceptingOrders`, Chainlink resolution
source, tick size, minimum order size và `negRisk`.

Engine lấy order book của token được chọn và chỉ có thể tạo một quyết định cho
mỗi slug. Không DCA, không martingale, không đồng thời mua hai outcome.

## Fee và sizing

Với crypto taker fee rate `r=0.07`, giá ask `q`, fee mỗi share là:

```text
fee_share = r × q × (1 - q)
edge_share = P_model - q - fee_share
```

Chỉ xét lệnh nếu edge vượt `POLYMARKET_MIN_EDGE`, spread không vượt ngưỡng,
book có đủ depth và stake đạt minimum order size. Stake dùng fractional Kelly
với trần bankroll/market; mặc định chỉ 10% Kelly và tối đa 10 USD.

Calibration là điều kiện bắt buộc. JSON phải có `approved: true` và bảng:

```json
{
  "approved": true,
  "probability_by_source": {
    "main_5m": {"up": 0.54, "down": 0.46},
    "aux_short_15m": {"up": 0.42, "down": 0.58}
  }
}
```

Các con số trên chỉ là schema minh họa, không phải calibration đã được duyệt.

## State machine

```text
WAIT boundary
  -> DISCOVER Gamma event
  -> VALIDATE rules/token IDs/constraints
  -> CHECK geoblock
  -> LOAD closed Binance/Lighter candles
  -> SIGNAL (or abstain)
  -> READ CLOB book
  -> CALIBRATION + EV + risk checks
  -> PAPER_LOG             (default)
  -> LIVE FAK BUY           (explicit opt-in only)
  -> RECONCILE user stream/order
  -> WAIT resolution / redeem
```

Live mode phải bổ sung user-stream reconciliation, cancellation on stale/late
orders, market resolution polling, winning token redemption và audit of every
fill. Paper mode hiện ghi signal/quote/risk calculation, không ký lệnh.

## Lộ trình kiểm chứng

1. Thu thập mỗi boundary: Gamma event JSON, CLOB books, Chainlink RTDS values,
   Binance/Lighter candles, timestamp/latency.
2. Dựng nhãn theo **đúng rules của event**; không dùng close Binance làm nhãn
   thay thế trong báo cáo cuối.
3. Walk-forward calibration theo source × entry offset × ask bucket; giữ riêng
   discovery, calibration, validation và OOS.
4. Replay phí crypto, spread, depth, FAK partial fill, stale book và missed
   market. Chỉ bật `approved` sau khi OOS edge còn dương.
5. Paper run đủ dài, rồi mới dùng ví nhỏ ở IP được phép.

## Độ tin cậy hiện tại

`research_polymarket_btc15m_signal.py` cho sanity check trên 240 ngày dữ liệu
Lighter: auxiliary 58,05% (441 tín hiệu), main 52,98% (672), composite 54,99%
(1.113). Nhãn là proxy first-open/last-close 1m, chưa phải Chainlink TWAP và
không có historical Polymarket ask/fill. Kết quả này đủ để thiết kế abstention
và calibration pipeline, chưa đủ để khẳng định có lợi nhuận.
