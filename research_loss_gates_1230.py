"""Offline audit of all 410 original 12:30 candidates; never imports a trading engine.

Bot1 is read-only: load its pure helpers without writing bytecode. Gate hypotheses
are fixed in PROTOCOL before scoring. Both historical periods have been studied
before, so validation-only selection is exploratory, not a pristine holdout.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from audit_poly_research import read_minutes, bars5
from polymarket_bot.actual_research import history_asof, cash_cost
from polymarket_bot.signal_grid import features, raw_signals, select_windows
from polymarket_bot.robustness import bankroll_replay
from report_robust_paper import block_interval
from research_signal_extensions import feature_tables, observation

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'logs/loss_gates_1230'
BOT1 = Path('D:/backtest')
EXACT = ['ema200', 'adaptive', 'weak10_turn', 'early_direction', 'memory_rsi',
         'aux_shock', 'aux_above_mid60']
POLY = ['spot_lead_positive', 'lead_z1', 'lead_z1_5', 'momentum3_positive',
        'token_momentum_nonnegative', 'quiet_vol1_5', 'bb_reclaim',
        'lead_z1_and_momentum3', 'ref_at_least90', 'ref_at_most95']
GATES = ['original'] + [f'dca_{g}_{at}' for g in EXACT for at in ('signal', 'entry')] + POLY
PROTOCOL = {
    'entry_seconds': 750, 'min_reference': .85, 'max_reference_age': 75,
    'budget': 20, 'bankroll': 50, 'padding_cents': [1, 2, 3], 'gates': GATES,
    'selection': 'Among gates retaining >=50% and >=100 training candidates, choose highest '
                 '+2c PnL gain with positive gain also at +1c; otherwise keep original. Stable ID tie-break.',
    'split': 'Choose on Apr19-Jul13, evaluate Jul14-Sep03 separately. Already explored history.',
    'walk_forward': 'June/July/August/September; select using only entries ended at least one day before month start.',
    'causality': 'Entry features know 1m closes through T+12:00 and 5m closes through T+10:00. '
                 'No T+12 open candle, eventual close, or settlement may enter a gate.',
    'bot1': 'Exact pure optional gate helpers at original signal time and at T+10. '
            'Main-only scope for adaptive/weak/early/memory; aux-only for shock/above-mid. '
            'EMA200 applied to both branches. Bot1 fail-open diagnostics preserved and reported.',
    'cost': 'Cached fee curve, cash equivalent within $20. Reference+padding assumed fill; '
            'stress>=1 is explicit zero-cost nonfill on original cohort; no historical books/gas/hosting.',
    'portfolio': 'Expiry-time redemption assumption, no capital top-ups; not observed redemption.',
    'not_model_fit': 'No combinations beyond named lead_z1_and_momentum3, no loser-date blacklist, '
                     'no after-the-fact threshold search. All results reported.',
}


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def load_bot1():
    sys.dont_write_bytecode = True
    modules = []
    for name in ('band_dca_lane', 'band_dca_market'):
        spec = importlib.util.spec_from_file_location(name, BOT1 / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def exact_gates(own5, peer5, at, side, source, lane, market):
    """Feed only completed candles to Bot1 helpers; flags explicitly enable research gates."""
    own = own5.loc[own5.timestamp.le(at-pd.Timedelta(minutes=5))].tail(728).copy()
    peer = peer5.loc[peer5.timestamp.le(at-pd.Timedelta(minutes=5))].tail(728).copy()
    cfg = lane.BandDcaConfig(ema_gate_dist_bps=200, adaptive_entry_enabled=True,
        weak10_turn_enabled=True, early_direction_enabled=True, aux_shock_enabled=True,
        lane_above_mid_max=.60, lane_above_mid_hours=12)
    side1 = 'long' if side == 'up' else 'short'
    main = source == 'main_5m'
    checks = {k: (False, 'not_applicable') for k in EXACT}
    grouped = own.set_index('timestamp').close.resample('15min')
    closed = grouped.last().where(grouped.count().eq(3)).dropna().tail(120)
    ema = closed.ewm(span=21, adjust=False).mean().iloc[-1] if len(closed) >= 84 else None
    checks['ema200'] = (lane.ema_gate_blocks(lane.BandDcaState(symbol='BTC'), cfg,
        close_5m=float(own.close.iloc[-1]), ema_15m=ema, side=side1), None)
    if main:
        checks['adaptive'] = lane.adaptive_entry_blocks(own, cfg, side=side1, expected_closed_at=at)
        checks['weak10_turn'] = lane.weak10_plus_turn_blocks(own, peer, cfg, side=side1, expected_closed_at=at)
        checks['early_direction'] = lane.early_direction_blocks(own, peer, cfg, side=side1, expected_closed_at=at)
        checks['memory_rsi'] = market.memory_rsi_blocks(market.market_features(
            own, peer, expected_closed_at=at, peer_bars=36), side=side1)
    else:
        checks['aux_shock'] = lane.auxiliary_short_shock_blocks(own, peer, cfg, coin='BTC', expected_closed_at=at)
        reason = lane.lane_above_mid_blocks(own, cfg, now=at)
        checks['aux_above_mid60'] = (reason is not None, reason)
    return {k: {'keep': not bool(b), 'reason': why} for k, (b, why) in checks.items()}, {
        'ema_gap_bps': float((own.close.iloc[-1]/ema-1)*10000*(1 if side == 'up' else -1)) if ema else None}


def entry_features(minutes, mf, bands, start, side, history):
    x = observation(minutes, mf, bands, start, 750, side)
    current = history_asof(history, int(start.timestamp())+750)
    prior = history_asof(history, int(start.timestamp())+630)
    direction = 1 if side == 'up' else -1
    known = minutes.loc[start:start+pd.Timedelta(minutes=11), 'close']
    opening = minutes.open.get(start, np.nan)
    leads = direction*(known/opening-1)*10000
    return {k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in x.items()} | {
        'token_momentum2': current['price']-prior['price'] if current and prior else np.nan,
        'lead_bps': float(leads.iloc[-1]) if len(leads) == 12 and leads.notna().all() else np.nan,
        'peak_lead_bps': float(leads.max()) if len(leads) == 12 and leads.notna().all() else np.nan,
        'giveback_bps': float(leads.max()-leads.iloc[-1]) if len(leads) == 12 and leads.notna().all() else np.nan,
    }


def poly_gates(x, reference):
    return {
        'spot_lead_positive': x['lead'] > 0, 'lead_z1': x['lead_z'] >= 1,
        'lead_z1_5': x['lead_z'] >= 1.5, 'momentum3_positive': x['momentum3'] > 0,
        'token_momentum_nonnegative': x['token_momentum2'] >= 0,
        'quiet_vol1_5': x['vol_ratio'] <= 1.5, 'bb_reclaim': x['bb_reclaim'],
        'lead_z1_and_momentum3': x['lead_z'] >= 1 and x['momentum3'] > 0,
        'ref_at_least90': reference >= .90, 'ref_at_most95': reference <= .95,
    }


def build():
    oldmeta = json.loads((ROOT/'timeframe_research_20260913/summary.json').read_text())['metadata']
    paths = [Path(s['path']) for s in oldmeta['sources']]
    minutes, meta = read_minutes(paths)
    assert [s['sha256'] for s in meta['sources']] == [s['sha256'] for s in oldmeta['sources']]
    peer, peer_meta = read_minutes([p.with_name('ETHUSDT_1m.csv') for p in paths])
    own5, peer5 = bars5(minutes), bars5(peer)
    grid = features(own5)
    mapped = select_windows(raw_signals(grid, session_start=0, session_end=0), policy='latest_5m').set_index('decision_at')
    mf, bands = feature_tables(minutes)
    candidates = [r for r in json.loads((ROOT/'logs/late_entry_payoff/trades.json').read_text()) if r['delay']==750]
    assert len(candidates) == 410 and sum(r['won'] for r in candidates) == 398
    lane, market = load_bot1()
    rows = []; hashes = {}
    for i, r in enumerate(candidates):
        start = pd.Timestamp(r['start'], unit='s', tz='UTC'); sig = mapped.loc[start]
        assert sig.side == r['side'] and sig.source == r['source']
        path = ROOT/'actual_market_research_20260913/raw'/f"{r['start']}.json"
        data = path.read_bytes(); hashes[path.name] = hashlib.sha256(data).hexdigest()
        raw = json.loads(data); history = raw.get(r['side']+'_history', {}).get('body', {}).get('history', [])
        ref = history_asof(history, r['start']+750)
        assert ref and abs(ref['price']-r['reference']) < 1e-12
        assert raw['settlement']['winner'] == r['winner']
        x = entry_features(minutes, mf, bands, start, r['side'], history)
        masks = {'original': True}; diagnostics = {}
        for label, at in [('signal', sig.signal_at), ('entry', start+pd.Timedelta(minutes=10))]:
            checks, extras = exact_gates(own5, peer5, at, r['side'], r['source'], lane, market)
            for key, check in checks.items():
                masks[f'dca_{key}_{label}'] = check['keep']
                diagnostics[f'dca_{key}_{label}'] = check['reason']
            x[label+'_ema_gap_bps'] = extras['ema_gap_bps']
        masks.update({k: bool(v) for k,v in poly_gates(x, ref['price']).items()})
        row = {k: r[k] for k in ('start','slug','period','side','source','winner','won','opened_ms','end_ms')}
        row.update(reference=ref['price'], quote_age=ref['age_seconds'], signal_at=sig.signal_at.isoformat(),
                   signal_age_minutes=float(sig.signal_age_minutes), route=sig.route, features=x,
                   keep=masks, diagnostics=diagnostics)
        sign = 1 if r['side']=='up' else -1
        row['signal_band_z'] = float(sign*(sig.close-sig.mid5)/((sig.upper5-sig.lower5)/4))
        final = minutes.close.get(start+pd.Timedelta(minutes=14),np.nan)
        opening = minutes.open.get(start,np.nan)
        row['outcome_diagnostic_only'] = {
            'lighter_final_signed_bps': float(sign*(final/opening-1)*1e4),
            'lighter_winner': 'up' if final >= opening else 'down',
            'post_entry_reversal': bool(x['lead_bps'] > 0 and sign*(final/opening-1) < 0)}
        for cents in (1,2,3):
            price = ref['price']+cents/100
            cost = 20. if price < 1 else 0.
            shares = 20/cash_cost(price, raw['fee']) if cost else 0.
            row[f'cost{cents}'] = cost; row[f'shares{cents}'] = shares
            row[f'pnl{cents}'] = shares*r['won']-cost
        assert abs(row['pnl1']-r['pnl']*2/3) < 1e-8
        rows.append(row)
        if (i+1)%100 == 0: print(f'Features and gates {i+1}/{len(candidates)}', flush=True)
    return rows, {'btc':meta, 'eth':peer_meta, 'archive_sha256':hashes,
        'bot1_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                      (BOT1/'band_dca_lane.py', BOT1/'band_dca_market.py')}}


def metric(rows, gate):
    kept = [r for r in rows if r['keep'][gate]]
    removed = [r for r in rows if not r['keep'][gate]]
    n = len(kept); wins = sum(r['won'] for r in kept)
    result = {'n':n,'wins':wins,'losses':n-wins,'win_rate':wins/n if n else None,
        'removed_winners':sum(r['won'] for r in removed), 'avoided_losses':sum(not r['won'] for r in removed),
        'removed_winner_profit1':sum(r['pnl1'] for r in removed if r['won']),
        'pnl1':sum(r['pnl1'] for r in kept), 'pnl2':sum(r['pnl2'] for r in kept),
        'pnl3':sum(r['pnl3'] for r in kept),
        'mean_pnl1':sum(r['pnl1'] for r in kept)/n if n else None,
        'missing_or_invalid_bot1_gate_inputs':sum(any(w in str(r['diagnostics'].get(gate,''))
             for w in ('unavailable','unaligned','invalid','warmup','short')) for r in rows)}
    for c in (1,2,3):
        result[f'delta{c}'] = sum(r[f'pnl{c}'] for r in kept)-sum(r[f'pnl{c}'] for r in rows)
        result[f'nonfill{c}'] = sum(r[f'cost{c}']==0 for r in kept)
        result[f'nonfill_losers{c}'] = sum(r[f'cost{c}']==0 and not r['won'] for r in kept)
    result['monthly'] = {month:{'n':len(part),'wins':sum(r['won'] for r in part),
        'pnl1':sum(r['pnl1'] for r in part)} for month in sorted({pd.Timestamp(r['start'],unit='s').strftime('%Y-%m') for r in rows})
        for part in [[r for r in kept if pd.Timestamp(r['start'],unit='s').strftime('%Y-%m')==month]]}
    result['bankroll50_expiry_credit_assumption'] = bankroll_replay([
        dict(r,cost=r['cost1'],shares=r['shares1']) for r in kept],
        {r['slug']:{'winner':r['winner'],'received_ms':r['end_ms']} for r in kept},50,20)
    return result


def choose(rows):
    candidates = []
    for g in GATES[1:]:
        m = metric(rows,g)
        if m['n'] >= max(100,.5*len(rows)) and m['delta1'] > 0 and m['delta2'] > 0:
            candidates.append((m['delta2'],g))
    return sorted(candidates,key=lambda x:(-x[0],x[1]))[0][1] if candidates else 'original'


def evaluate(rows):
    before = [r for r in rows if r['period']=='validation']
    selected = choose(before)
    dump(OUT/'selected_on_earlier_period.json', {'gate':selected, 'rule':PROTOCOL['selection']})
    results = {g:{p:metric([r for r in rows if p=='all' or r['period']==p],g)
                 for p in ('validation','confirmation','all')} for g in GATES}
    for g in GATES:
        paired = [dict(r,pnl=(r['pnl1'] if r['keep'][g] else 0)-r['pnl1']) for r in rows]
        first = int(pd.Timestamp('2026-04-19',tz='UTC').timestamp())//86400
        last = int(pd.Timestamp('2026-09-03',tz='UTC').timestamp())//86400
        results[g]['all']['paired_delta_per_candidate_block95'] = block_interval(paired,first,last)
        results[g]['all']['strategy_pnl1_if_one_retained_winner_loses'] = min(
            (results[g]['all']['pnl1']-r['shares1'] for r in rows if r['keep'][g] and r['won']), default=None)
    folds = []; sequential = []
    for cut in pd.date_range('2026-06-01','2026-09-01',freq='MS',tz='UTC'):
        train = [r for r in rows if r['end_ms'] <= int((cut-pd.Timedelta(days=1)).timestamp()*1000)]
        end = cut+pd.offsets.MonthBegin(1)
        test = [r for r in rows if cut.timestamp() <= r['start'] < end.timestamp()]
        g = choose(train)
        folds.append({'month':str(cut.date()),'gate':g,'train_n':len(train),
                      'test':metric(test,g),'baseline':metric(test,'original')})
        sequential.extend(dict(r,keep=dict(r['keep'],walkforward=r['keep'][g])) for r in test)
    return {'selected_earlier':selected,'results':results,'walkforward_folds':folds,
            'walkforward':metric(sequential,'walkforward'),'walkforward_baseline':metric(sequential,'original')}


def safe(value):
    if isinstance(value,dict): return {k:safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [safe(v) for v in value]
    if isinstance(value,(float,np.floating)): return float(value) if np.isfinite(value) else None
    if isinstance(value,np.bool_): return bool(value)
    if isinstance(value,np.integer): return int(value)
    return value


def write_report(rows, report):
    losses = [r for r in rows if not r['won']]
    lines = ['# Phân tích 12 lệnh thua tại 12:30', '',
        'Đối chứng 410 lệnh, 398 thắng/12 thua; $20/lệnh, giá tham chiếu+1c và phí cash-equivalent. '
        '138 ngày 19/04–03/09/2026, ngày cuối không đầy đủ. Không sửa cấu hình bot.', '',
        '## Những gì dữ liệu đang gợi ý', '',
        'Cả 12 lệnh thua đều đang dẫn đúng hướng theo snapshot Lighter tại T+12. '
        '10/12 đổi sang phía thua trên Lighter lúc hết hạn; 2/12 Lighter vẫn cho phía thắng nhưng settlement Polymarket cho phía thua '
        '(08/07 và 11/08, giờ VN). Giá tham chiếu outcome cao không bảo đảm BTC không đảo chiều; '
        'khác biệt nguồn Lighter/Chainlink cũng phải được giữ nguyên khi chấm nhãn.', '',
        'Khoảng cách giá tuyệt đối phân biệt kém: trung vị lead 9,11bp ở lệnh thua và 9,93bp ở lệnh thắng. '
        'Sau khi chuẩn hóa theo biến động, trung vị Z là 0,90 và 1,30. Cả 12 lệnh thua có Z<1,5; '
        'đây là mô tả trong mẫu, không có nghĩa Z>=1,5 bảo đảm thắng tương lai.', '',
        '**Gate đáng thu thêm dữ liệu nhất: quiet_vol1_5.** Dùng log-return 1m đã đóng: '
        'std 5 return gần nhất / std 60 return gần nhất; bỏ lệnh nếu tỷ số >1,5 (hoặc thiếu đầu vào). '
        'Gate này đã có trong nghiên cứu Signal Extensions trước đây, là cách áp ý tưởng tránh shock '
        'vào cửa sổ settlement ngắn, không phải sao chép nguyên hàm aux_shock của Bot1. '
        'Nó bỏ lệnh thua 14/05 (ratio 1,83) và 11/08 (1,74), bỏ thêm 9 lệnh thắng. '
        'Tiết kiệm $40 thua, mất $3,77 lãi thắng, tăng ròng $36,23. '
        'Gate vẫn còn 10 lệnh thua; lợi ích hiện tại dựa vào chỉ hai trường hợp.', '',
        '**Gate trực tiếp từ DCA đáng đối chiếu: memory_rsi tại tín hiệu gốc.** '
        'Chỉ main_5m: giữ điều kiện early-direction (ADX<25, DI ngược>=5, ETH 1h ngược>=30bp); '
        'hoặc trong 120 phút từng có điều kiện đó và DI/RSI hiện vẫn bất lợi. '
        'Nó tránh 5 thua nhưng bỏ 91 thắng; lãi ròng tăng $19,36, PnL sau chỉ tăng $3,18. '
        'EMA200 không loại được lệnh nào. Weak10/turn và adaptive band bỏ quá nhiều lệnh thắng ở +1c.', '',
        'Bộ chọn chỉ xem 86 ngày đầu chọn early_direction_entry. Gate đó làm giai đoạn 52 ngày sau '
        'kém bản gốc $6,97. Chọn lại theo từng tháng từ dữ liệu đã kết thúc cho $90,61 so với gốc $91,09 '
        'trên cùng các tháng được chấm. Vì vậy chưa chứng minh được một quy trình chọn gate ổn định.', '',
        'Khoảng bootstrap paired gain/lệnh gốc của quiet_vol là [-$0,0092; +$0,2334], của memory_rsi_signal '
        'là [-$0,1585; +$0,2828]; cả hai chứa 0 và chưa hiệu chỉnh 24 phép thử. '
        'Hướng tiếp theo là ghi shadow quyết định quiet_vol và memory_rsi theo dữ liệu nhận thực tế, '
        'giữ profile gốc làm đối chứng, rồi kiểm tra các lần skip mới. Không tự thêm gate vào live.', '',
        '## Từng lệnh thua', '',
        'Thời gian là giờ Việt Nam (UTC+7) tại lúc xét mua. Lead dương nghĩa giá Lighter đang đúng hướng so với mở cửa market. '
        'Lead Z chia khoảng cách theo biến động 30 phút và sqrt(3 phút còn lại từ close T+12); không phải xác suất đã hiệu chuẩn.', '',
        '| Thời gian VN | Hướng / nhánh | Tuổi tín hiệu (phút) | Ref / tuổi (s) | Lead (bp) | Lead Z | Momentum 3m (bp) | Lighter cũng thua? |',
        '|---|---|---:|---|---:|---:|---:|---|']
    for r in losses:
        f=r['features']; at=pd.Timestamp(r['opened_ms'],unit='ms',tz='UTC').tz_convert('Asia/Bangkok')
        lines.append(f"| {at:%d/%m %H:%M:%S} | {r['side']} / {r['source']} | {r['signal_age_minutes']:.0f} | "
            f"{r['reference']:.3f} / {r['quote_age']} | {f['lead_bps']:.2f} | {f['lead_z']:.2f} | "
            f"{f['momentum3']*10000:.2f} | {'Có' if r['outcome_diagnostic_only']['lighter_winner']!=r['side'] else 'Không'} |")
    lines += ['', 'Toàn bộ 12 lệnh thua mất $20/lệnh trong mô phỏng. Giá BTC ở đây là Lighter, không phải feed settlement Chainlink.', '',
        '## Nhánh và tuổi tín hiệu: phải so cả thắng lẫn thua', '',
        '| Nhóm | Lệnh | Thua | Win-rate | PnL +1c |', '|---|---:|---:|---:|---:|']
    for field in ('source','side','signal_age_minutes','route'):
        for val in sorted({str(r[field]) for r in rows}):
            part=[r for r in rows if str(r[field])==val]; m=metric(part,'original')
            lines.append(f"| {field}={val} | {m['n']} | {m['losses']} | {m['win_rate']:.2%} | ${m['pnl1']:+.2f} |")
    lines += ['', '## Toàn bộ gate, không chỉ các gate có kết quả đẹp', '',
        'signal = gate lúc tín hiệu gốc; entry = gate ở nến 5m đóng T+10. Các gate cùng tên trong hai thời điểm '
        'là hai biến thể độc lập. EMA chặn quá xa phía bất lợi 200bp; above-mid chỉ nhánh short phụ, ngưỡng 60%/12h. '
        'Các gate khác giữ tham số hàm thuần Bot1. Không khẳng định các cờ này đang bật trên Bot1.', '',
        '| Gate | Thắng/tổng | Thua tránh / thắng bỏ | Win-rate | PnL trước | PnL sau | PnL tổng +1c | +2c | +3c |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for g in GATES:
        a,b,c=[report['results'][g][p] for p in ('validation','confirmation','all')]
        lines.append(f"| {g} | {c['wins']}/{c['n']} | {c['avoided_losses']} / {c['removed_winners']} | "
            f"{c['win_rate']:.2%} | ${a['pnl1']:+.2f} | ${b['pnl1']:+.2f} | ${c['pnl1']:+.2f} | ${c['pnl2']:+.2f} | ${c['pnl3']:+.2f} |")
    lines += ['', '## Chọn trên giai đoạn trước, kiểm tra giai đoạn sau', '',
        f"Quy tắc chọn: {PROTOCOL['selection']}", '', f"Gate được chọn: **{report['selected_earlier']}**.", '',
        '| Tháng | Gate chọn chỉ bằng dữ liệu trước | Thắng/tổng | PnL gate | PnL gốc |', '|---|---|---:|---:|---:|']
    for fold in report['walkforward_folds']:
        a,b=fold['test'],fold['baseline']
        lines.append(f"| {fold['month']} | {fold['gate']} | {a['wins']}/{a['n']} | ${a['pnl1']:+.2f} | ${b['pnl1']:+.2f} |")
    lines += ['', '## Độ phủ dữ liệu khi gọi gate DCA', '',
        'Các hàm Bot1 giữ nguyên quy ước fail-open khi thiếu/không hợp lệ: cho qua và lưu lý do. '
        'Đây không phải gate đã được kiểm chứng ở những lượt thiếu dữ liệu. '
        'Gate ngoại suy theo lead/vol chỉ giữ khi có đủ số đo cần thiết.', '',
        '| Gate | Lượt thiếu/không hợp lệ, cho qua |', '|---|---:|']
    for g in GATES:
        n=report['results'][g]['all']['missing_or_invalid_bot1_gate_inputs']
        if n:lines.append(f'| {g} | {n} |')
    lines += ['', '## Giới hạn cần giữ khi diễn giải', '',
        '- 12 thất bại rất ít. Nghiên cứu 24 gate, lịch sử đã khảo sát: cải thiện là giả thuyết, chưa là xác nhận ngoài mẫu. '
        'Không đặt gate riêng theo ngày/giờ của lệnh thua, không tối ưu lại ngưỡng sau khi xem bảng.',
        '- Giá outcome là điểm lịch sử gần nhất trước quyết định, tối đa 75s; chỉ 34/410 điểm mới trong 15s. '
        'Thiếu historical asks/depth và actual fills. +1/2/3c là giả định, phí cache không chứng minh đúng phí tại ngày giao dịch.',
        '- Stress +2/+3c giữ 410 ứng viên; giá>=1 ghi nonfill, có thể loại cả lệnh vốn sẽ thua. Không coi win-rate tăng do nonfill là tín hiệu tốt hơn.',
        '- Dữ liệu 1m chỉ biết close T+12; 30 giây trước quyết định chưa quan sát được. Không dùng close T+13 hoặc T+15 để lọc. '
        'Cột Lighter cuối market chỉ để chẩn đoán khác nguồn settlement.',
        '- Bootstrap trong JSON là paired delta theo block 3 ngày, có ngày không giao dịch, chưa hiệu chỉnh nhiều phép thử. '
        'Ví $50 ghi nhận redemption giả định ngay hết hạn; gas/nạp-rút/vận hành chưa tính.',
        '- Không sao chép TP/trailing/nhồi DCA vì quyền chọn hết hạn cố định có payout khác. '
        'Gate tương quan ETH-BTC dành riêng ETH không áp vào BTC.', '',
        'Tái chạy: `python -B research_loss_gates_1230.py`. '
        'Chi tiết JSON: `logs/loss_gates_1230/summary.json`, `candidates.json`, `losses.json`, `protocol.json`.']
    (ROOT/'LOSS_GATES_1230_RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    dump(OUT/'protocol.json',PROTOCOL)
    rows,manifest=build()
    report=evaluate(rows)
    report.update(protocol=PROTOCOL,manifest=manifest,code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    dump(OUT/'summary.json',safe(report)); dump(OUT/'candidates.json',safe(rows))
    dump(OUT/'losses.json',safe([r for r in rows if not r['won']]))
    write_report(rows,report)
    for g in GATES:
        c=report['results'][g]['all']
        print(g, c['n'], c['losses'], round(c['pnl1'],2),round(c['pnl2'],2),
              'removed W/L', c['removed_winners'],c['avoided_losses'],flush=True)
    print('Selected on earlier:',report['selected_earlier'],flush=True)


if __name__=='__main__':
    main()
