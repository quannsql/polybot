# Chuẩn bị thử Polymarket $30/lệnh

Kiểm tra ngày 13/09/2026. Người dùng đăng nhập Google, hiện ở Việt Nam.

## Trạng thái chính xác

**Chưa sẵn sàng bật bot giao dịch thật.** Đã chuẩn bị môi trường riêng, ngân sách paper $30 bao gồm phí, kiểm tra public API/geoblock, kiểm thử và tài liệu triển khai preflight. Chưa đăng nhập ví, tạo API credential, cấp allowance, nạp tiền hoặc gửi lệnh.

Lý do không thể chỉ thêm API key rồi chạy:

1. Runtime cũ vào gần đầu market và giới hạn entry <300 giây; không phải chiến lược vào 11m30 đã nghiên cứu.
2. Bộ gửi lệnh cũ dùng market FAK không truyền trần giá, chưa đối soát rejected/partial fill/on-chain settlement và lượng token thực nhận. Nó lưu số shares dự tính như vị thế, không đủ an toàn cho tiền thật.
3. Luồng oracle/edge mới chưa có price-to-beat được xác minh trong market đang mở và chưa có mẫu settlement mới đủ để hiệu chuẩn.
4. Tư cách sử dụng của người dùng/tài khoản và IP máy chủ chưa xác minh. Public GET hoạt động không chứng minh quyền giao dịch.

Đã **vô hiệu hóa đường gửi lệnh live cũ** ở cả Settings và executor để tránh thêm khóa rồi vô tình kích hoạt prototype. Chỉ thay trong Bot2, không đụng Bot1. Đây không phải hoàn tất executor live mới; các phần đặt lệnh giới hạn giá, lưu ý định bền vững, đối soát khi timeout, số dư/allowance, settlement/redeem và giới hạn danh mục vẫn cần tích hợp và kiểm thử trước kích hoạt.

## Đã chuẩn bị gì?

- `trial_30usd.json`: profile chuẩn bị $30 tổng chi gồm phí; đề xuất lần thử đầu tối đa **một** lệnh, $30 phơi nhiễm và dừng sau một lần thua $30. Đây là giới hạn đề xuất cho canary ban đầu, không phải tự đổi ngân sách dài hạn của người dùng; chưa phải bộ giới hạn runtime được kích hoạt.
- `collect_advanced_paper.py --budget-usd 30`: đưa đúng ngân sách vào phép tính độ sâu, edge shadow và maker queue. Các mốc/policy vẫn là thí nghiệm độc lập có thể chồng nhau, **không phải danh mục tổng vốn $30**.
- `preflight_trial.py`: public read-only; kiểm tra profile, SDK, geoblock, giờ server, market, fee curve và giá vốn $30 theo độ sâu hai outcome. Không khởi tạo secure client, không tạo khóa hay cấp approval; chỉ ghi có/không biến bí mật, không ghi giá trị.
- `.venv-trial`: Python riêng, không dùng system-site-packages; SDK `polymarket-client==0.10.0` đã cài và kiểm tra chữ ký hàm. Không sửa các package Python của Bot1.
- Kiểm tra trong môi trường riêng: `pip check` không có xung đột, **73 test đạt**, gồm khóa live cũ, geoblock fail-closed và ngân sách $30 gồm phí/đi qua nhiều mức ask.
- `requirements-paper.txt`, `requirements-live-sdk.txt`: pin phiên bản phụ thuộc trực tiếp. Chưa phải lock đầy đủ transitive/cross-platform.
- `Dockerfile.preflight`: container chỉ chạy kiểm tra read-only một lần; chưa build vì máy hiện không có Docker được tìm thấy. Không có Docker/worker live hoặc tự chọn Railway region.
- `.gitignore`, `.dockerignore`: giảm nguy cơ đưa `.env`, dữ liệu ví, capture và log vào Git/container. Không thay thế quản lý secrets hay kiểm toán repo trước upload.

## $30 và kiểm tra dữ liệu thực

Trong lần capture hữu hạn 60 giây tại `advanced_paper_capture_30usd`:

- 24 orderbook snapshots; 10 cost probes đủ điều kiện, tổng chi lớn nhất khoảng $29.9999998.
- 14 phép đo bị bỏ: 7 empty/crossed book, 7 thiếu displayed depth trong trần giá.
- 5.950 market stream events; không có edge order paper hoặc lệnh thật.

Đây là phép đo chi phí giả định trên book hiển thị, không phải bằng chứng khớp $30 thực tế. Phí cash-equivalent cần đối chiếu debit và số shares thực nhận khi tích hợp live.

Không đơn giản lấy PnL backtest $5 nhân 6 làm dự báo $30: khối lượng lớn hơn có thể đi qua nhiều mức ask. Thuần số học trên cùng giả định giá, mốc 11m30/ref≥0.85 có +$165.16/125 lệnh ở 52 ngày sau, nhưng đó **không phải backtest thực thi $30** và không dùng làm dự báo thu nhập.

## Con số 99% có đáng tin?

Số trong file là **124/125 = 99.20%**, không phải 99.22%. Nó mô tả đúng nhãn settlement của tập lệnh lịch sử đó, nhưng chưa chứng minh xác suất thắng thực tế 99.20%:

- Chỉ 125 lệnh, có tương quan theo thời gian và đã khảo sát nhiều cấu hình trên cùng lịch sử.
- Cận dưới Wilson 95% khoảng **95.61%**, ngay cả khi tạm coi các lệnh độc lập; chưa điều chỉnh lựa chọn tham số hoặc sai số giá.
- Giai đoạn trước của cùng mốc 11m30/ref≥0.85: 273/288 = 94.79%, PnL giả định $5 là **-$5.24**.
- Chỉ 9/125 reference ở mốc này cũ không quá 15 giây. Giá reference không phải ask có thể khớp; quanh cuối market giá thay đổi nhanh.
- 99% đúng cũng chưa chắc lãi: nếu giá vốn mỗi share cao hơn xác suất thắng thì kỳ vọng vẫn âm.

Vì vậy không gán `p=0.992` vào bot, không tăng cược để bù lỗ và không bỏ guard chỉ vì bảng lịch sử đẹp.

## Railway: vùng nào dùng được?

Railway hiện công bố **4 vùng ở 3 quốc gia**, không phải 5 quốc gia: California và Virginia (US), Amsterdam (NL), Singapore (SG). [Railway Regions](https://docs.railway.com/deployments/regions).

| Railway | Tài liệu API Polymarket hiện tại | Kết luận cho mở lệnh mới |
|---|---|---|
| US West / US East | US close-only trên frontend và API | Không chọn để mở vị thế mới trên API quốc tế này |
| Singapore | SG close-only trên frontend và API | Không chọn để mở vị thế mới |
| Amsterdam, Netherlands | NL close-only trên frontend; tài liệu nói API không bị hạn chế | Có thể kiểm tra hạ tầng API, **chưa xác nhận đủ điều kiện giao dịch** |

Nguồn phân biệt frontend/API: [Geographic Restrictions API](https://docs.polymarket.com/api-reference/geoblock). Mặt khác, [Help Center](https://help.polymarket.com/en/articles/13364163-geographic-restrictions) liệt kê Netherlands trong danh sách hạn chế tổng quát. Hai trang chính thức chưa đồng nhất; cần Polymarket xác nhận trường hợp dùng API từ server NL cho người sử dụng ở Việt Nam trước khi coi đây là lựa chọn live hợp lệ.

Việt Nam không xuất hiện trong các bảng API đã đọc tại ngày kiểm tra, nhưng điều này **không xác nhận pháp lý tại Việt Nam hoặc tư cách tài khoản**. Không suy từ “IP không blocked” sang “được phép sử dụng”. Không dùng VPN, proxy, sửa DNS hay đổi server để che vị trí/vượt hạn chế.

`GET https://polymarket.com/api/geoblock` cần chạy từ chính môi trường deploy. Trên máy hiện tại request lỗi ConnectError, nên trạng thái là **unknown, không cho live**. Không đổi sang API host khác hoặc mặc định allowed khi endpoint lỗi. Chưa tạo deploy Railway và chưa có kết quả IP Railway thật.

Nếu được xác nhận đủ điều kiện, có thể chạy preflight không cần secrets trên Amsterdam (`europe-west4-drams3a`). Kết quả `blocked=false` chỉ là kiểm tra mạng, không thay thế xác nhận điều kiện người dùng/tài khoản. Không bật failover tự động sang US/SG cho giao dịch mới.

## Google login: cần những gì?

Đăng nhập Google không cho biết chắc loại ví:

- Tài khoản Google cũ có thể là **Proxy Wallet**.
- Theo tài liệu, ví account được deploy từ 04/05/2026 dùng **Deposit Wallet**.

Phải xác minh đúng **Polymarket account wallet address**, không tự coi địa chỉ signer là địa chỉ giữ tiền. [Wallets and Authentication](https://docs.polymarket.com/trading/wallets-auth).

Các thành phần cần chuẩn bị sau khi đủ điều kiện:

1. **Địa chỉ ví Polymarket** hiển thị trong profile và loại ví đã xác minh. Đây là địa chỉ công khai; vẫn chỉ chia sẻ khi cần.
2. **Signer được ủy quyền.** Nếu là Deposit Wallet, cân nhắc Session Key để bot không giữ owner key. Session Key không rút tiền nhưng vẫn có thể gây lỗ khi trade; không tự có hạn mức $30. Cần bảo vệ key và quy trình thu hồi. Nếu ví cũ không hỗ trợ, phải chọn cách ký phù hợp; không chuyển ví hay xuất key tự động. [Session Keys](https://docs.polymarket.com/trading/session-keys).
3. **CLOB credentials:** API key + secret + passphrase cho request riêng tư. Có thể được SDK tạo/derive bằng signer; chúng không thay thế toàn bộ quyền ký order và không phải Google password/token.
4. **Relayer hoặc Builder credentials khi cần thao tác ví gasless/approvals.** Đây không phải cùng loại với CLOB API key. Luồng cụ thể tùy loại ví; không nhất thiết phải tạo mọi loại key. [Wallet authentication và approvals](https://docs.polymarket.com/trading/wallets-auth).
5. **Số dư collateral đúng ví, đúng mạng và approvals đúng exchange.** Tài liệu quickstart hiện dùng pUSD; nạp qua flow chính thức và kiểm tra token/network trong tài khoản, không gửi token vào địa chỉ suy đoán. $30/lệnh là ngân sách giao dịch, không đảm bảo $30 tổng tài khoản đủ cho mọi thao tác/gas ngoài giao dịch. [Quickstart](https://docs.polymarket.com/trading/quickstart).

Không gửi private key, seed phrase, CLOB secret/passphrase hoặc Google token vào chat. Không upload `.env`. Hiện **chưa cần nhập khóa**: các kiểm tra chuẩn bị đều dùng public API. Nếu dùng Railway sau này, secrets phải nhập trực tiếp trong vùng quản lý biến bí mật của service đã kiểm toán, không ghi vào Dockerfile hoặc Git.

Tài liệu xuất key của Help Center dành cho email/Magic Link không chứng minh áp dụng đúng cho mọi tài khoản Google mới. Không yêu cầu bạn xuất owner key trước khi xác minh loại ví. [Hướng dẫn chính thức](https://help.polymarket.com/en/articles/13364258-how-do-i-export-my-key).

## Các lệnh an toàn đã chuẩn bị

Từ `D:/polybot`:

```powershell
.\.venv-trial\Scripts\python.exe -B preflight_trial.py --output trial_preflight_local.json
.\.venv-trial\Scripts\python.exe -B collect_advanced_paper.py --duration-seconds 120 --budget-usd 30 --output-dir advanced_paper_capture_30usd
```

Preflight mặc định kết thúc thành công về mặt kiểm tra và ghi `live_ready=false`; dùng `--require-ready` để pipeline trả exit code 2 khi chưa đủ điều kiện. Không dùng exit code 0 mặc định như giấy phép bật live.

Trên máy có Docker, chỉ để kiểm tra public network:

```text
docker build -f Dockerfile.preflight -t polybot-preflight .
docker run --rm polybot-preflight
```

Chưa chạy hai lệnh Docker này trên máy hiện tại. Nếu deploy preflight Railway, chọn Dockerfile tương ứng, không nhập private key và tắt tự restart cho công việc kiểm tra một lần. Không coi preflight container là bot live.

## Bước tiếp theo cần đầu vào

Trước khi nối ví: xác nhận chính sách sử dụng/API đối với người ở Việt Nam chạy server NL, và xác định loại ví Google. Có thể bắt đầu bằng **địa chỉ ví Polymarket công khai hoặc tên loại ví trong tài khoản**, không phải private key. Sau đó mới chuẩn bị adapter ký phù hợp, kiểm tra số dư/allowance read-only và hoàn thiện execution reconciliation. Vẫn cần dữ liệu/giá mốc để chiến lược oracle-edge đủ điều kiện; một thử nghiệm kết nối/khớp lệnh có chủ đích không chứng minh chiến lược sinh lời.
