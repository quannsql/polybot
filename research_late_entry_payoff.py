"""Fixed original 15m signal: late-entry net payoff and loss-recovery audit.

Read-only cached venue data; no trading, credentials or runtime config changes.
"""
import json
import math
from collections import Counter
from pathlib import Path

from polymarket_bot.actual_research import cash_cost, history_asof
from polymarket_bot.robustness import bankroll_replay
from report_robust_paper import block_interval

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'logs/timeframe_expansion'
OUT = ROOT / 'logs/late_entry_payoff'
DELAYS = (690, 720, 750, 780, 810, 840, 870, 885)
BUDGET = 30.


def payoff(reference, fee, won, pad=.01, budget=BUDGET):
    """Cash-equivalent fee is inside budget. Price >=1 means no order."""
    if reference + pad >= 1:
        return None
    unit_cost = cash_cost(reference + pad, fee)
    shares = budget / unit_cost
    return {'unit_cost': unit_cost, 'shares': shares,
            'pnl': shares * bool(won) - budget}


def metrics(rows):
    n = len(rows)
    if not n:
        return {'n': 0}
    wins = [r for r in rows if r['won']]
    win_profit = sum(r['pnl'] for r in wins) / len(wins) if wins else None
    # Descriptive recovery rate from observed winner payoff, not a forecast.
    recovery = BUDGET / win_profit if win_profit else None
    labels = {r['slug']: {'winner': r['winner'], 'received_ms': r['end_ms']} for r in rows}
    out = {'n': n, 'wins': len(wins), 'losses': n-len(wins),
           'win_rate': len(wins)/n, 'pnl': sum(r['pnl'] for r in rows),
           'mean_pnl': sum(r['pnl'] for r in rows)/n,
           'mean_winning_profit': win_profit, 'loss_per_losing_order': -BUDGET,
           'wins_to_cover_one_loss': recovery,
           'whole_average_wins_to_cover_loss': math.ceil(recovery) if recovery else None,
           'descriptive_break_even_rate': BUDGET/(BUDGET+win_profit) if win_profit else None,
           'fresh15s': sum(r['age'] <= 15 for r in rows),
           'bankroll50': bankroll_replay(rows, labels, 50, BUDGET),
           'mean_pnl_block95': block_interval(rows, min(r['opened_ms'] for r in rows)//86400000,
                                            max(r['opened_ms'] for r in rows)//86400000)}
    for cents in (2, 3):
        out[f'pnl_{cents}c'] = sum(r[f'pnl_{cents}c'] for r in rows)
        out[f'nonfills_{cents}c'] = sum(r[f'nonfill_{cents}c'] for r in rows)
        out[f'nonfill_would_lose_{cents}c'] = sum(r[f'nonfill_{cents}c'] and not r['won'] for r in rows)
    return out


def main():
    predictions = json.loads((SOURCE/'selected_predictions.json').read_text())
    predictions = [r for r in predictions if r['id'] == 'main5_aux15__h15']
    records = []; excluded = Counter()
    for p in predictions:
        start = p['start']
        raw = json.loads((SOURCE/'raw'/f'15_{start}.json').read_text())
        for delay in DELAYS:
            if raw.get('settlement', {}).get('status') != 'confirmed' or raw.get('fee', {}).get('status') != 'known':
                excluded[(delay, 'unverified_fee_or_label')] += 1
                continue
            quote = history_asof(raw.get(p['side']+'_history', {}).get('body', {}).get('history', []), start+delay)
            if quote is None or quote['price'] < .85:
                excluded[(delay, 'missing_quote_or_below_threshold')] += 1
                continue
            winner = raw['settlement']['winner']; won = p['side'] == winner
            fill = payoff(quote['price'], raw['fee'], won)
            if fill is None:
                excluded[(delay, 'price_plus_1c_ge_one')] += 1
                continue
            row = {**p, **fill, 'delay': delay, 'won': won, 'winner': winner,
                   'slug': raw['parsed']['slug'], 'age': quote['age_seconds'],
                   'reference': quote['price'], 'cost': BUDGET,
                   'opened_ms': (start+delay)*1000, 'end_ms': (start+900)*1000}
            for cents in (2, 3):
                stress = payoff(quote['price'], raw['fee'], won, cents/100)
                row[f'pnl_{cents}c'] = stress['pnl'] if stress else 0.
                row[f'nonfill_{cents}c'] = stress is None
            records.append(row)
    results = {str(d): {period: metrics([r for r in records if r['delay'] == d and
                                       (period == 'all' or r['period'] == period)])
                       for period in ('validation', 'confirmation', 'all')} for d in DELAYS}
    original = results['690']
    assert original['validation']['n'] == 288 and original['confirmation']['wins'] == 124
    assert abs(original['all']['pnl']-133.7225380952) < 1e-7
    OUT.mkdir(parents=True, exist_ok=True)
    protocol = {'delays': DELAYS, 'budget': BUDGET, 'threshold': .85, 'max_quote_age_seconds': 75,
                'selection': 'Report all delays. No fresh holdout, no runtime changes.',
                'signal': 'Original main5/aux15, fixed at market start; no entry recheck.',
                'execution': 'Reference+1c with cached cash-equivalent fee; assumed depth and fill. '
                             'Stress+2/+3c on same candidate cohort; prices>=1 become nonfills. '
                             'Fee metadata not historical fee verification. No gas/hosting/deposit costs.',
                'bankroll': 'Independent $50 wallet per delay; $30 fixed stake, expiry-time redemption assumed.'}
    (OUT/'summary.json').write_text(json.dumps({'protocol': protocol, 'results': results,
        'excluded': [{'delay': d, 'reason': why, 'n': n} for (d, why), n in excluded.items()]}, indent=2), encoding='utf-8')
    (OUT/'trades.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    lines = ['# Bản gốc 15m: chờ thêm có đủ lãi bù lỗ?', '',
        'Giữ nguyên hướng DCA/Boll chính 5m và short phụ 15m đã chọn ở đầu market; chỉ đổi thời gian mua. '
        'Ngưỡng tham chiếu >=0.85, giá tham chiếu không quá 75 giây, $30/lệnh gồm phí cash-equivalent. '
        'Không tính lại hướng trước khi mua. Mọi mốc đều settlement ở phút 15.', '',
        '86 ngày trước: 19/04–13/07/2026; 52 ngày sau: 14/07–03/09/2026 (ngày cuối dữ liệu không đầy đủ). '
        'Lịch sử đã được xem nhiều lần; không phải holdout mới.', '',
        '## Kết luận trên tập dữ liệu này', '',
        '12:30 có PnL +1c toàn kỳ cao nhất trong 8 mốc thử, không phải cấu hình đã chứng minh tối ưu cho tương lai. '
        'Có 398 lệnh thắng và 12 lệnh thua: tổng lãi các lệnh thắng $558.22 trừ $360 lỗ = $198.22. '
        'Lãi bình quân lệnh thắng $1.403; cần khoảng 22 lệnh thắng như mức trung bình này để bù một lệnh thua $30. '
        'Tỷ lệ hòa vốn tính từ mức lãi thắng quan sát là 95.53%, so với tỷ lệ thắng mẫu 97.07%.', '',
        'Ở +2c, 12:30 còn lãi $86.96 toàn kỳ, trong đó giai đoạn trước chỉ +$6.58. '
        'Ở +3c, toàn kỳ +$27.18 nhưng giai đoạn trước lỗ $27.69; 145 cơ hội không mua vì giá >=1, gồm 1 lệnh vốn sẽ thua. '
        'Chỉ 34/410 tham chiếu mới trong 15 giây; khoảng bootstrap PnL trung bình vẫn chứa 0. '
        'Do đó chưa đủ bằng chứng để xác nhận khả năng bù chi phí live.', '',
        'Ví $50/stake $30 ở 12:30 chỉ đi được 8 lệnh rồi còn $26.49, bỏ 402 cơ hội tiếp theo. '
        'Con số +$198.22 giả định luôn đủ vốn, không đạt được bằng cách chạy liên tục ví $50 này. '
        'Không đổi mức vốn hoặc tự nạp tiền trong mô phỏng.', '',
        '## Giá mua giả định +1 cent', '',
        '| Mốc vào | Trước: thắng/tổng | PnL trước | Sau: thắng/tổng | PnL sau | PnL toàn kỳ | PnL/lệnh | Lãi TB lệnh thắng | Số thắng TB bù 1 thua |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for d in DELAYS:
        a,b,c = (results[str(d)][p] for p in ('validation','confirmation','all'))
        lines.append(f"| {d//60}:{d%60:02} | {a['wins']}/{a['n']} | ${a['pnl']:+.2f} | {b['wins']}/{b['n']} | ${b['pnl']:+.2f} | ${c['pnl']:+.2f} | ${c['mean_pnl']:+.3f} | ${c['mean_winning_profit']:.3f} | {c['wins_to_cover_one_loss']:.1f} |")
    lines += ['', 'Mỗi lệnh thua mất $30. Số thắng bù lỗ dùng mức lãi trung bình các lệnh thắng đã quan sát; '
              'không phải cam kết những lệnh thắng tiếp theo có cùng lợi nhuận.', '',
        '## Stress chi phí, độ mới dữ liệu và ví $50', '',
        '| Mốc | PnL +2c | PnL +3c | +3c trước / sau | Giá mới <=15s | Ví $50 cuối kỳ | Khoảng bootstrap 95% PnL/lệnh |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for d in DELAYS:
        a,b,c = (results[str(d)][p] for p in ('validation','confirmation','all'))
        lo,hi = c['mean_pnl_block95']
        lines.append(f"| {d//60}:{d%60:02} | ${c['pnl_2c']:+.2f} | ${c['pnl_3c']:+.2f} | ${a['pnl_3c']:+.2f} / ${b['pnl_3c']:+.2f} | {c['fresh15s']}/{c['n']} | ${c['bankroll50']['cash_after_known_settlements']:.2f} | ${lo:+.3f} đến ${hi:+.3f} |")
    lines += ['', 'Giả định +1/+2/+3c không phải spread hoặc slippage đã đo. Stress giữ tập ứng viên +1c; '
        'khi giá >=1 thì không mua, PnL=0, có thể bỏ cả lệnh thua. JSON lưu số nonfill và số would-lose. '
        'Ví $50 chạy liên tục cả hai giai đoạn, không tự nạp lại; settlement được giả định trả tiền ngay hết hạn.', '',
        'Các mốc lọc ra tập lệnh khác nhau; không thể diễn giải rằng chờ thêm tự biến cùng một lệnh thua thành thắng. '
        'Vào 14:45 chỉ còn 15 giây nhưng dữ liệu được phép cũ 75 giây, nên đặc biệt không đủ kiểm chứng khớp live. '
        'Chưa có sổ lệnh lịch sử, độ trễ và phí lịch sử được xác nhận; chưa trừ gas, nạp/rút hay máy chủ. '
        'Bootstrap chỉ chẩn đoán, chưa hiệu chỉnh thử nhiều mốc.', '',
        'Chạy lại: `python -B research_late_entry_payoff.py`. Dữ liệu chi tiết: `logs/late_entry_payoff/`. '
        'Đối chứng 11:30 được kiểm tra tái hiện kết quả cũ. Không sửa Bot1 hay cấu hình paper/live.']
    (ROOT/'LATE_ENTRY_PAYOFF_RESULT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('Created LATE_ENTRY_PAYOFF_RESULT.md and logs/late_entry_payoff/')


if __name__ == '__main__':
    main()
