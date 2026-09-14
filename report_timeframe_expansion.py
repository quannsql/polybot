"""Human-readable report from frozen timeframe research outputs."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'logs/timeframe_expansion'


def label(ident):
    main,tail=ident.removeprefix('main').split('_aux');aux,h=tail.split('__h')
    return f'Boll {main}m + short phụ {aux}m / market {h}m'


def pct(p):return f'{100*p:.2f}%' if p is not None else 'n/a'


def main():
    proxy=json.loads((OUT/'proxy_summary.json').read_text())
    venue=json.loads((OUT/'venue_summary.json').read_text())
    coverage=json.loads((OUT/'fetch_coverage.json').read_text())
    selected=venue['selected']
    lines=['# Đổi khung Bollinger/DCA và thời hạn market', '',
        f"Đã khảo sát {len(proxy['variants'])} tổ hợp, dựng lại tín hiệu gốc khớp hoàn toàn. "
        f"Kiểm tra {coverage['requested']} market trong nhóm chọn để đánh giá giá outcome và settlement.", '',
        '## Kết luận', '',
        '**Chưa xác nhận được biến thể nào tốt hơn một cách bền vững để thay cấu hình đang chạy.** Ứng viên được chọn bằng giai đoạn trước bị lỗ ở giai đoạn sau.',
        'Hai hướng đáng nghiên cứu tiếp là market 5m với Boll chính/phụ 30m/30m và market 4h với Boll 1m/60m. Đây là nhận xét khám phá sau khi xem kết quả, không phải hai cấu hình đã vượt kiểm định độc lập.',
        'Bản 5m có 98/101 lệnh thắng, nhưng giai đoạn trước lỗ khi giả định giá mua đắt thêm 3c. Bản 4h có 51/52 lệnh thắng và có lãi ở cả hai giai đoạn dưới stress 3c, nhưng chỉ có 39 lệnh giai đoạn trước, không đạt mức tối thiểu 50 đã định. Không có cơ sở gọi 100% của 13 hoặc 28 lệnh gần đây là tỷ lệ thắng thật.',
        'Với ví chỉ $50 và stake $30, mô phỏng bản 5m dừng khả năng mua sau 41 lệnh, còn $17.34 và bỏ 60 cơ hội tiếp theo. Vì thế PnL toàn tập +$70.53 không phải lợi nhuận đạt được bằng ví $50 này.', '',
        '## Quy tắc và cách chọn', '',
        '- Nhánh chính: chạm Bollinger theo hướng router ngày. Nhánh phụ short: chạm dải trên và pump >=60bps trong 60 phút; nhánh phụ ưu tiên.',
        '- Giữ Bollinger 20/2, SMA ngày 25, short depth 1,5%, phiên 24h. Chỉ dùng nến đã đóng. Khung thay đổi là độ dài mỗi nến, không đổi số kỳ hoặc độ lệch chuẩn.',
        '- 18 cặp khung: main 1/3/5/10/15/30m và auxiliary 5/15/30/60m, chỉ nhận cặp mà auxiliary chia hết cho main. Mỗi cặp thử horizon 5/10/15/30/60/240m.',
        '- Mỗi market lấy tín hiệu mới nhất trước đầu kỳ, tuổi tối đa 10 phút. Không có tín hiệu đủ mới thì bỏ market, kể cả với horizon dài.',
        '- Giữ tỷ lệ vào muộn 11:30 trên 15m: market5m vào3:50, 10m vào7:40, 15m vào11:30, 30m vào23:00, 1h vào46:00, 4h vào3h04. Không vào lúc11:30 cho mọi horizon.',
        '- Hai biến thể mỗi horizon được chọn bằng Wilson lower trên tín hiệu dự đoán giá Lighter ở 86 ngày trước (>=100 mẫu train và validation), cộng bản gốc làm đối chứng. Sau đó mới kiểm tra giá outcome của nhóm này. Đây là sàng lọc có giới hạn, không chứng minh tối ưu toàn bộ biến thể theo PnL.',
        '- Trong nhóm có dữ liệu outcome, chọn theo PnL/lệnh của 86 ngày trước, tối thiểu50 lệnh và PnL dương ở cả +1c và +3c. Ghi lựa chọn trước khi báo cáo 52 ngày sau. Không chọn dựa vào kết quả của giai đoạn sau.', '',
        '## Market thực tế', '',
        'Danh mục đã kiểm tra có BTC 5m, 15m, 1h và 4h. Chưa xác minh được market chuẩn10m/30m tương ứng. Không thể thay bằng hai lệnh15m rồi gọi là cùng một hợp đồng30m.',
        'Market1h được kiểm tra chốt theo Binance BTC/USDT 1h, trong khi market5m/15m/4h dùng Chainlink. Phần PnL dùng nhãn Gamma resolved và CLOB winner đồng thuận, không lấy giá Lighter làm settlement.', '',
        '## Kết quả giá outcome, $30/lệnh', '',
        'Giá mua giả định=tham chiếu+1c, tham chiếu>=0.85, tuổi<=75s; có phí theo metadata cache. Giả định luôn đủ vốn và depth. Các bảng này chưa chứng minh khả năng khớp lệnh thật.', '',
        '| Biến thể | 86 ngày trước: thắng/tổng | Win-rate | PnL | 52 ngày sau: thắng/tổng | Win-rate | PnL |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for k,v in sorted(venue['results'].items(),key=lambda kv:(int(kv[0].split('__h')[1]),kv[0])):
        a,b=v['validation'],v['confirmation']
        lines.append(f"| {label(k)} | {a['wins']}/{a['n']} | {pct(a['win_rate'])} | ${a['pnl']:+.2f} | {b['wins']}/{b['n']} | {pct(b['win_rate'])} | ${b['pnl']:+.2f} |")
    lines+=['','## Biến thể được chọn bằng giai đoạn trước','']
    if selected:
        v=venue['results'][selected]
        lines+=[f'Ứng viên theo quy tắc đã định: **{label(selected)}**.',
                f"Giai đoạn sau: {v['confirmation']['wins']}/{v['confirmation']['n']} thắng, PnL +1c ${v['confirmation']['pnl']:+.2f}, +3c ${v['confirmation']['pnl_3c']:+.2f}.",
                '**Ứng viên này thất bại ở giai đoạn kiểm tra sau; không đề xuất chuyển bot sang cấu hình này.** Vị trí đứng đầu ở giai đoạn trước không phải bằng chứng tốt nhất trong tương lai.']
    else:
        lines+=['**Không có ứng viên nào vượt đủ điều kiện đã định trên giai đoạn trước.** Không ép chọn một cấu hình chỉ vì nhóm nhỏ có win-rate100%.']
    lines+=['','## Độ nhạy chi phí và vốn toàn kỳ','',
        '| Biến thể | Số lệnh gốc | PnL +1c | PnL +2c | PnL +3c | Ví $50 cuối kỳ* |',
        '|---|---:|---:|---:|---:|---:|']
    for k,v in sorted(venue['results'].items()):
        a=v['all'];wallet=a['bankroll50_instant_settlement']['cash_after_known_settlements']
        lines.append(f"| {label(k)} | {a['n']} | ${a['pnl']:+.2f} | ${a['pnl_2c']:+.2f} | ${a['pnl_3c']:+.2f} | ${wallet:.2f} |")
    lines+=['','*Mỗi biến thể dùng ví riêng$50, stake$30, giả định tiền settlement về ngay lúc hết hạn. Khi không đủ$30 thì bỏ lệnh tiếp theo. Không cộng PnL của các biến thể thành một danh mục.',
        'Stress giữ nguyên tập cơ hội +1c; giá+2/+3c >=1 được ghi không mua với PnL0. Có thể vô tình bỏ lệnh thua; JSON báo riêng số này. Chi phí là giả định, không phải trượt giá đã đo.', '',
        '## Khả năng dự đoán khi chưa lọc giá outcome', '',
        'Bảng dưới là hướng giá Lighter từ đầu đến cuối market, CHƯA lọc giá tham chiếu0.85 khi vào muộn. Không so trực tiếp các tỷ lệ này với99,20% của tập lệnh đã lọc giá.', '',
        '| Horizon | Khung | 86 ngày trước: n / đúng | 52 ngày sau: n / đúng |',
        '|---|---|---:|---:|']
    for h,ids in proxy['selected'].items():
        for k in [f'main5_aux15__h{h}']+ids[:1]:
            v=proxy['variants'][k];a,b=v['validation'],v['confirmation']
            lines.append(f"| {h}m | {label(k)} | {a['n']} / {pct(a['win_rate'])} | {b['n']} / {pct(b['win_rate'])} |")
    lines+=['','## Chất lượng bằng chứng của các ứng viên đáng chú ý','',
        '| Biến thể | Giá tham chiếu không quá 15 giây | Lệnh theo Chainlink TWAP | Khoảng bootstrap 95% PnL trung bình/lệnh |',
        '|---|---:|---:|---:|']
    for k in ('main5_aux15__h15','main30_aux30__h5','main1_aux60__h240'):
        a=venue['results'][k]['all'];lo,hi=a['mean_pnl_block95_diagnostic']
        twap=a['by_rule_type'].get('chainlink_twap',{}).get('n',0)
        lines.append(f"| {label(k)} | {a['fresh15s']}/{a['n']} | {twap}/{a['n']} | ${lo:+.2f} đến ${hi:+.2f} |")
    lines+=['',
        'Cả ba khoảng bootstrap đều chứa 0; đây chỉ là chẩn đoán, chưa hiệu chỉnh việc thử nhiều cấu hình. Phần lớn kết quả lịch sử là quy tắc Chainlink spot, không phải TWAP đang thấy ở market hiện tại. Đặc biệt bản 4h chỉ có 3 lệnh TWAP và không có tham chiếu nào mới trong 15 giây. Chưa đủ để kết luận phù hợp live hiện tại.', '',
        '## Giới hạn và bằng chứng','',
        f"Tình trạng fetch: `{coverage['counts']}`. Chỉ ghi PnL khi có nhãn cuối, phí biết được và tham chiếu hợp lệ. Thiếu dữ liệu không được coi là lệnh thắng hay giả lập giá mua.",
        'Các khung có thể có khác biệt ngày niêm yết và độ phủ dữ liệu. Số tín hiệu, lý do loại, kết quả theo tháng và theo quy tắc settlement có trong JSON để kiểm tra.',
        'Lịch sử đã được nghiên cứu nhiều lần. Chọn trên giai đoạn trước rồi kiểm tra giai đoạn sau giảm việc nhìn trước, nhưng không biến lịch sử cũ thành holdout mới. Không có bảo đảm108 phép thử sẽ tìm ra lợi thế bền vững.',
        'Metadata phí được đọc khi thu thập, không chứng thực mức phí tại đúng ngày lịch sử. Chưa có depth, spread và độ trễ khớp thật cho các market này. Không gồm gas, phí trung gian nạp/rút hay máy chủ.',
        'Cấu hình paper đang chạy và Bot1 được giữ nguyên. Chỉ bổ sung code nghiên cứu.', '',
        'Chạy lại: `python -B research_timeframe_expansion.py screen`, rồi `fetch`, rồi `analyze`, cuối cùng `python -B report_timeframe_expansion.py`.',
        'Dữ liệu trong `logs/timeframe_expansion`: proxy_summary.json, selected_predictions.json, venue_summary.json, venue_trades.json và raw/. Các snapshot được cache và có SHA256; không push archive lên GitHub.', '',
        'Nguồn: [danh mục Bitcoin](https://polymarket.com/crypto/bitcoin), '
        '[quy tắc1h](https://polymarket.com/event/bitcoin-up-or-down-august-30-2026-12pm-et), '
        '[quy tắc4h](https://polymarket.com/event/btc-updown-4h-1789372800), '
        '[lịch sử giá](https://docs.polymarket.com/api-reference/markets/get-prices-history).']
    (ROOT/'TIMEFRAME_EXPANSION_RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Report created; selected:',selected)


if __name__=='__main__':main()
