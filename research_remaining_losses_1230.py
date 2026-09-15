"""Retrospective additive filters on the frozen 300-trade strong-gate cohort.

No venue/executor or live configuration imports. No automatic approval/deploy.
Only entry-known inputs may enter keep(); outcome fields are scoring-only.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from polymarket_bot.entry_gates import PROFILE, decide
from research_gate_combinations_1230 import inputs, scores
from polymarket_bot.robustness import bankroll_replay

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT/'logs/gate_combinations_1230/candidates.json'
OUT = ROOT/'logs/remaining_losses_1230'


def suite():
    rules = [dict(id='current', kind='none')]
    # Coarse thresholds specified before scoring; not fitted to exact loss values.
    for z in (.5, .75, 1., 1.25):
        for scope in ('all', 'aux', 'adverse_momentum', 'against_slope'):
            rules.append(dict(id=f'{scope}_z{z:g}', kind='lead', scope=scope, z=z))
    for name in ('adaptive','weak10_turn','early_direction','memory_rsi','aux_above_mid60'):
        for at in ('signal','entry'):
            rules.append(dict(id=f'dca_{name}_{at}',kind='dca', key=f'dca_{name}_{at}'))
    for kind in ('momentum_positive','slope_agrees','token_momentum_nonnegative'):
        rules.append(dict(id=kind,kind=kind))
    for frac in (.25,.5,.75):
        rules.append(dict(id=f'giveback_max{frac:g}',kind='giveback',maximum=frac))
    for age in (15,30,45):
        rules.append(dict(id=f'quote_age_max{age}',kind='quote_age',maximum=age))
    for z in (.5,.75,1.):
        for key in ('dca_adaptive_entry','dca_weak10_turn_entry'):
            rules.append(dict(id=f'aux_z{z:g}_plus_{key}',kind='branch',z=z,key=key))
    return rules


RULES = suite()
PROTOCOL = dict(base=PROFILE, entry_seconds=750, minimum_reference=.85, budget=20,
    source='Same 300 kept from 410 original eligible candidates; additive vetoes only.',
    period='2026-04-19..2026-09-03; validation ends 2026-07-13, later starts 2026-07-14.',
    design='Three losses already inspected and base already optimized; all results retrospective. '
           'Later period has zero baseline losses: any veto can only sacrifice its winning profit.',
    rules=RULES,
    selection='Training only: retain >=70% trades and >=85% PnL at +1c/+2c, '
              'remove >=1 loss, rank min(PnL gain +1c, PnL gain +2c), then fewer dropped winners, ID. '
              'If none, retain current. Later results never enter this selector.',
    timing='Frozen signal gates at original signal_at; entry DCA at closed5m T+10; '
           'Z/momentum/slope at closed1m T+12 and completed5m/15m; no future features.',
    execution='Cached reference+1/2/3c and fee cash equivalent within $20. '
              'Prices>=1 are explicit nonfills on SAME base cohort. No measured historical depth, '
              'latency, historical fee attestation, gas, hosting. Wallet replay assumes redemption timing.',
    robustness='Neighbor thresholds, monthly counts, later profit retention, paired 3-day block bootstrap '
               'with family max-t diagnostic, leave-one-loss-out selection, one-extra-loss stress. '
               'None of these erase prior data reuse.')


def entry_inputs(row):
    f = row['features']
    return dict(z=f['lead_z'], aux=row['source']=='aux_short_15m', momentum=f['momentum3'],
        slope=f['slope15_agrees'], token_momentum=f['token_momentum2'], age=row['quote_age'],
        giveback=f['giveback_bps'], peak=f['peak_lead_bps'], gates=row['keep'].copy())


def finite(x):
    return x is not None and np.isfinite(x)


def keep(x, rule):
    kind=rule['kind']
    if kind=='none': return True
    if kind=='dca': return x['gates'][rule['key']]
    if kind=='lead':
        applies = (rule['scope']=='all' or rule['scope']=='aux' and x['aux'] or
                   rule['scope']=='adverse_momentum' and (not finite(x['momentum']) or x['momentum']<0) or
                   rule['scope']=='against_slope' and not x['slope'])
        return not applies or finite(x['z']) and x['z']>=rule['z']
    if kind=='branch':
        return (finite(x['z']) and x['z']>=rule['z']) if x['aux'] else x['gates'][rule['key']]
    if kind=='momentum_positive': return finite(x['momentum']) and x['momentum']>=0
    if kind=='slope_agrees': return bool(x['slope'])
    if kind=='token_momentum_nonnegative': return finite(x['token_momentum']) and x['token_momentum']>=0
    if kind=='quote_age': return finite(x['age']) and x['age']<=rule['maximum']
    if kind=='giveback':
        return (finite(x['peak']) and x['peak']>0 and finite(x['giveback']) and
                x['giveback']/x['peak']<=rule['maximum'])
    raise ValueError(kind)


def matrix(rows):
    return np.array([[keep(entry_inputs(r),rule) for r in rows] for rule in RULES],bool)


def choose(rows, masks):
    if not rows:return 0
    base=scores(rows,np.ones(len(rows),bool)); ranked=[]
    for i,rule in enumerate(RULES[1:],1):
        s=scores(rows,masks[i])
        if s['n']<.70*len(rows) or s['losses']>=base['losses']:continue
        if any(s[f'pnl{c}']<.85*base[f'pnl{c}'] for c in (1,2)):continue
        ranked.append((-min(s['delta1'],s['delta2']),s['removed_winners'],rule['id'],i))
    return sorted(ranked)[0][-1] if ranked else 0


def uncertainty(rows,masks,reps=3000):
    first=int(pd.Timestamp('2026-04-19',tz='UTC').timestamp())//86400
    days=138
    daily=np.zeros((days,len(RULES)))
    delta=(masks.astype(float)-1)*np.array([r['pnl1'] for r in rows])
    for i,r in enumerate(rows):daily[r['start']//86400-first]+=delta[:,i]
    rng=np.random.default_rng(20260916)
    starts=rng.integers(0,days,(reps,(days+2)//3))
    idx=((starts[:,:,None]+np.arange(3))%days).reshape(reps,-1)[:,:days]
    draws=daily[idx].sum(axis=1); means=delta.sum(axis=1); se=draws.std(axis=0,ddof=1)
    stable=se>1e-12
    standardized=np.zeros_like(draws)
    standardized[:,stable]=(draws[:,stable]-means[stable])/se[stable]
    max_t=standardized[:,stable].max(axis=1)
    return {rule['id']:dict(gain_total_ci95=np.quantile(draws[:,i],[.025,.975]).tolist(),
        approximate_family_p=float(np.mean(max_t>=means[i]/se[i])) if stable[i] else 1.)
        for i,rule in enumerate(RULES)}


def audit_inputs(rows):
    """Recompute causal features and cash-equivalent payouts from raw sources."""
    from audit_poly_research import read_minutes
    from research_signal_extensions import feature_tables, observation
    from polymarket_bot.actual_research import cash_cost, history_asof
    meta=json.loads((ROOT/'timeframe_research_20260913/summary.json').read_text())['metadata']
    minutes,actual=read_minutes([Path(s['path']) for s in meta['sources']])
    assert [s['sha256'] for s in actual['sources']]==[s['sha256'] for s in meta['sources']]
    mf,bands=feature_tables(minutes); hashes={}; lagged={1:[],2:[]}; trajectories=[]
    for row in rows:
        start=pd.Timestamp(row['start'],unit='s',tz='UTC')
        x=observation(minutes,mf,bands,start,750,row['side'])
        for key in ('lead_z','momentum3','slope15_agrees','vol_ratio'):
            old=row['features'][key]; now=x[key]
            assert (old is None and not np.isfinite(now)) or np.isclose(old,now,atol=1e-8,rtol=1e-8), (row['slug'],key)
        path=ROOT/'actual_market_research_20260913/raw'/f"{row['start']}.json"
        blob=path.read_bytes();raw=json.loads(blob);hashes[path.name]=hashlib.sha256(blob).hexdigest()
        assert raw['settlement']['status']=='confirmed' and raw['fee']['status']=='known'
        assert raw['settlement']['winner']==row['winner'] and (row['side']==row['winner'])==row['won']
        q=history_asof(raw.get(row['side']+'_history',{}).get('body',{}).get('history',[]),row['start']+750,75)
        assert q and q['price']==row['reference'] and q['age_seconds']==row['quote_age']
        for c in (1,2,3):
            ask=q['price']+c/100
            expected=20*(int(row['won'])/cash_cost(ask,raw['fee'])-1) if ask<1 else 0
            assert abs(expected-row[f'pnl{c}'])<1e-8
        for lag in (1,2):
            y=observation(minutes,mf,bands,start,750-60*lag,row['side'])
            f=dict(row['features'])
            for key in ('lead_z','momentum3','slope15_agrees'):
                f[key]=float(y[key]) if np.isfinite(y[key]) else None
            lagged[lag].append(dict(row,features=f))
        if not row['won']:
            candles=[];opening=float(minutes.loc[start,'open']);sign=1 if row['side']=='up' else -1
            for offset in range(15):
                v=minutes.loc[start+pd.Timedelta(minutes=offset)]
                candles.append(dict(close_known_minute=offset+1,close=float(v.close),
                    signed_bps=float(sign*(v.close/opening-1)*1e4),after_gate=offset>=12))
            trajectories.append(dict(slug=row['slug'],oracle_label=raw['settlement']['winner'],
                rule_type=raw['parsed']['rule_type'],opening=opening,candles=candles))
    focus=['adverse_momentum_z0.5','against_slope_z0.75']
    sensitivity={}
    for lag,part in lagged.items():
        m=matrix(part)
        sensitivity[str(lag)]={key:scores(rows,m[next(i for i,r in enumerate(RULES) if r['id']==key)]) for key in focus}
    return dict(recomputed_candidates=len(rows),features_match=True,payouts_match=True,
                raw_sha256=hashes,minute_sources=actual,loss_trajectories=trajectories,
                additional_gate_features_older_minutes=sensitivity,
                lag_note='Only added gate Z/momentum/slope lagged; baseline cohort, original DCA gate flags and prices fixed. No latency/fill simulation.')


def run():
    source=SOURCE.read_bytes(); all_rows=json.loads(source)
    rows=[r for r in all_rows if decide(inputs(r))[0]]
    assert len(rows)==300 and sum(r['won'] for r in rows)==297
    assert all(r['combination_keep'][PROFILE] == decide(inputs(r))[0] for r in all_rows)
    assert abs(sum(r['pnl1'] for r in rows)-191.4714468574)<1e-7
    audit=audit_inputs(rows)
    masks=matrix(rows); before=np.array([r['period']=='validation' for r in rows])
    chosen=choose([r for r,k in zip(rows,before) if k],masks[:,before])
    results={}; ci=uncertainty(rows,masks)
    for i,rule in enumerate(RULES):
        result=dict(rule=rule,uncertainty=ci[rule['id']])
        for period,which in [('all',np.ones(len(rows),bool)),('validation',before),('confirmation',~before)]:
            result[period]=scores([r for r,k in zip(rows,which) if k],masks[i,which])
        result['losses_removed']=[r['slug'] for r,k in zip(rows,masks[i]) if not k and not r['won']]
        result['losses_retained']=[r['slug'] for r,k in zip(rows,masks[i]) if k and not r['won']]
        result['one_extra_loss_pnl1']=result['all']['pnl1']-max((r['shares1'] for r,k in zip(rows,masks[i]) if k and r['won']),default=0)
        taken=[dict(r,cost=r['cost1'],shares=r['shares1']) for r,k in zip(rows,masks[i]) if k]
        result['wallet50']={str(delay):bankroll_replay(taken,{r['slug']:dict(winner=r['winner'],received_ms=r['end_ms']+delay*1000) for r in taken},50,20) for delay in (0,300,1800)}
        result['monthly']={}
        for month in sorted({pd.Timestamp(r['start'],unit='s').strftime('%Y-%m') for r in rows}):
            ix=np.array([pd.Timestamp(r['start'],unit='s').strftime('%Y-%m')==month for r in rows])
            result['monthly'][month]=scores([r for r,k in zip(rows,ix) if k],masks[i,ix])
        results[rule['id']]=result
    loo=[]
    for j,row in enumerate(rows):
        if row['won']:continue
        train=before.copy();train[j]=False
        ix=choose([r for r,k in zip(rows,train) if k],masks[:,train])
        loo.append(dict(omitted=row['slug'],selected=RULES[ix]['id'],would_keep_omitted=bool(masks[ix,j])))
    report=dict(protocol=PROTOCOL,sha256=hashlib.sha256(source).hexdigest(),selected_earlier=RULES[chosen]['id'],
                results=results,audit=audit,leave_one_loss_out=loo,losses=[r for r in rows if not r['won']])
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'summary.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    write_report(report)
    print('selected_earlier',report['selected_earlier'])
    for key,r in results.items():
        a,b,c=(r[p] for p in ('all','validation','confirmation'))
        print(key, a['n'],a['losses'],round(a['pnl1'],2),round(b['pnl1'],2),round(c['pnl1'],2),round(a['pnl2'],2))
    return report


def write_report(report):
    lines=['# Ba lệnh thua còn lại: bộ lọc bổ sung ở 12:30','',
        'Giữ ngưỡng 0,85; DCA gốc + strong gate đã chọn; $20/lệnh. '
        'Đối chứng tái hiện 297 thắng/300 lệnh, PnL +$191,47. Chỉ nghiên cứu, chưa thay bot live.','',
        'Dữ liệu 19/04–03/09/2026 (138 ngày lịch; ngày cuối không đầy đủ). '
        'Cả ba lệnh thua đều ở giai đoạn trước; giai đoạn sau là 97/97 thắng. '
        'Mọi thử nghiệm ở đây đều dùng lại dữ liệu đã biết, không có holdout mới.','',
        '## Các lệnh thua','',
        '| Mốc mua giờ Việt Nam | Nhánh | Hướng | Giá tham chiếu | Z | Momentum 3m (bps log) | Tuổi giá (s) |',
        '|---|---|---|---:|---:|---:|---:|']
    for r in report['losses']:
        at=pd.Timestamp(r['start']+750,unit='s',tz='UTC').tz_convert('Asia/Bangkok')
        f=r['features']
        lines.append(f"| {at:%d/%m/%Y %H:%M:%S} | {r['source']} | {r['side']} | {r['reference']:.3f} | {f['lead_z']:.3f} | {f['momentum3']*10000:+.3f} | {r['quote_age']} |")
    lines+=['','Z đo khoảng cách giá BTC theo hướng dự đoán so với biến động 30 phút, '
        'tính bằng nến đã đóng đến T+12. Z không phải xác suất thắng được hiệu chuẩn. '
        'Cả ba có khoảng dẫn dương rồi đảo chiều; dữ liệu cuối market chỉ dùng giải thích hậu nghiệm.','',
        '## Toàn bộ lưới cố định','',
        f"{len(RULES)-1} biến thể bổ sung; selector dùng giai đoạn trước chọn `{report['selected_earlier']}`. "
        'Selector và lưới được xây sau khi xem các lệnh thua nên không được xem là kiểm chứng độc lập.', '',
        '| Bộ lọc thêm | Thắng/tổng | Bỏ thắng/thua | PnL trước | PnL sau | Tổng +1c | Tổng +2c | Tổng +3c |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for key,r in report['results'].items():
        a,b,c=(r[p] for p in ('all','validation','confirmation'))
        lines.append(f"| {key} | {a['wins']}/{a['n']} | {a['removed_winners']}/{a['avoided_losses']} | ${b['pnl1']:+.2f} | ${c['pnl1']:+.2f} | ${a['pnl1']:+.2f} | ${a['pnl2']:+.2f} | ${a['pnl3']:+.2f} |")
    focus=['current','adverse_momentum_z0.5','against_slope_z0.75','all_z0.75']
    conclusions=['','## Hai ứng viên đáng theo dõi','',
        '**A — `adverse_momentum_z0.5`: bỏ khi momentum 3m ngược hướng VÀ Z<0,5.** '
        'Momentum dùng signed log(close T+12 / close T+9), dấu dương là đi đúng hướng đã chọn. '
        'Không yêu cầu mọi lệnh phải có momentum dương. Z dùng sigma log-return 30 phút × sqrt(3).', '',
        '**B — `against_slope_z0.75`: bỏ khi độ dốc đường giữa Bollinger 15m không cùng hướng VÀ Z<0,75.** '
        'Độ dốc là SMA20 của nến 15m đã đóng trừ giá trị của chính SMA đó 4 nến trước (60 phút). '
        'Không dùng nến 15m đang chạy; độ dốc 0 hoặc dữ liệu band không hợp lệ cũng không xác nhận cùng hướng.', '',
        '| Đối chứng/ứng viên | Thắng/tổng | PnL +1c | PnL giai đoạn sau | Bỏ lãi thắng để tránh thua | PnL nếu thêm 1 thua* |',
        '|---|---:|---:|---:|---:|---:|']
    for key in focus:
        r=report['results'][key];a=r['all']
        conclusions.append(f"| {key} | {a['wins']}/{a['n']} | ${a['pnl1']:+.2f} | ${r['confirmation']['pnl1']:+.2f} | ${a['sacrificed_winner_profit1']:.2f} | ${r['one_extra_loss_pnl1']:+.2f} |")
    conclusions+=['', '*Stress đổi lệnh thắng có payout lớn nhất thành thua trên tập giữ lại; không thêm cơ hội mới.', '',
        'A tránh $40 tiền thua, bỏ $1,51 lãi của một lệnh thắng trong tháng 5; tăng ròng $38,49. '
        '97/97 lệnh của giai đoạn sau đều giữ nguyên nên chưa có ví dụ giai đoạn sau để kiểm chứng tác dụng loại lệnh của A. '
        'B tránh $60 tiền thua nhưng bỏ $32,57 lãi thắng, tăng ròng $27,43. '
        'PnL giai đoạn sau giảm $7,45 (~10,2%).', '',
        'Các gate DCA áp cứng không đạt đánh đổi tốt bằng A: adaptive_entry còn 2 thua, '
        'PnL $167,68; weak10_turn_entry còn 2 thua, PnL $131,92. '
        'Chúng loại được lệnh long ngày 30/04 nhưng loại nhiều lệnh thắng hơn.', '',
        '## Độ nhạy và bằng chứng còn thiếu','',
        '| Ứng viên | Dữ liệu đúng T+12 | Cũ 1 phút: lệnh/thua/PnL | Cũ 2 phút: lệnh/thua/PnL | Khoảng 95% phần PnL tăng thêm |',
        '|---|---:|---:|---:|---|']
    for key in focus[1:3]:
        r=report['results'][key];u=r['uncertainty'];lags=report['audit']['additional_gate_features_older_minutes']
        a,b=lags['1'][key],lags['2'][key];lo,hi=u['gain_total_ci95']
        conclusions.append(f"| {key} | ${r['all']['pnl1']:+.2f} | {a['n']}/{a['losses']}/${a['pnl1']:+.2f} | {b['n']}/{b['losses']}/${b['pnl1']:+.2f} | ${lo:+.2f}..${hi:+.2f} |")
    conclusions+=['', 'Phép dữ liệu cũ chỉ thay Z/momentum/slope của gate mới; tập nền, gate DCA và giá mua giữ nguyên. '
        'Đây là độ nhạy thời điểm quan sát, không phải ước tính trượt giá mạng.', '',
        'Ngưỡng lân cận cũng cho thấy đánh đổi: A với Z<0,75 còn 1 thua nhưng PnL giảm còn $211,78; '
        'Z<1 còn $176,76. B với Z<0,5 giữ 1 thua và PnL $223,28; Z<1 hết thua nhưng PnL còn $176,63. '
        'Không nên chọn riêng mức 0,75 chỉ vì nó nằm ngay trên Z=0,723 của lệnh thua cuối.', '',
        'Cả hai khoảng bootstrap đều chứa 0. Family max-t p xấp xỉ 0,485 (A) / 0,918 (B); '
        'không đủ bằng chứng thống kê về lợi thế bền vững. Bỏ lần lượt từng lệnh thua: selector đổi khỏi A '
        'khi bỏ lệnh long tháng 4, cho thấy lựa chọn phụ thuộc vào vài trường hợp.', '',
        'Tôi ưu tiên A làm ứng viên xác nhận tiếp theo vì chỉ bỏ 3 cơ hội trong 300 và PnL mẫu cao nhất. '
        'B phục vụ mục tiêu ưu tiên ít thua hơn, nhưng 281/281 thắng là kết quả trong mẫu đã xem. '
        'Nếu triển khai sau này, cần có dữ liệu đúng T+12; không tự thay bằng nến cũ hơn. '
        'Hiện không sửa cấu hình, không push, không deploy và không gọi executor.', '',
        f"Đã tái tính {report['audit']['recomputed_candidates']}/300 mẫu từ nến nguồn, "
        'đối chiếu Z/momentum/slope/volatility, giá tham chiếu, nhãn settlement và PnL +1/+2/+3c; tất cả khớp.']
    marker=lines.index('## Toàn bộ lưới cố định')
    lines[marker:marker]=conclusions+['']
    lines+=['','## Giới hạn và cách đọc','',
        '- PnL tổng giả định có đủ vốn và khớp ở giá tham chiếu + padding, phí cash-equivalent nằm trong $20. '
        'Sổ lệnh, spread, độ trễ và giá khớp lịch sử chưa được xác minh; chưa trừ gas/máy chủ/nạp rút.',
        '- Stress +2/+3c giữ nguyên tập 300 cơ hội: giá >=1 được coi không khớp (PnL 0), JSON ghi riêng số nonfill. '
        'Đây không phải bằng chứng lệnh FOK với trần +1c sẽ khớp ở +2c.',
        '- Chỉ 21/300 giá tham chiếu mới trong 15 giây. Gate quote_age là điều kiện chất lượng dữ liệu; '
        'không được diễn giải như một tín hiệu thị trường loại thua.',
        '- Tất cả kết quả theo nhãn settlement Polymarket đã lưu. Chỉ báo dùng Lighter, không phải Chainlink. '
        'Quy tắc spot/TWAP và các giá trị phí trong cache có thể khác market hiện tại.',
        '- Bootstrap khối 3 ngày và family max-t chỉ là chẩn đoán trong lưới này, không sửa được việc thử nhiều vòng trước.',
        '- Chi tiết JSON gồm PnL từng tháng, wallet50 với trì hoãn redemption 0/300/1800s, '
        'stress một lệnh thắng thành thua, bỏ từng lệnh thua và chọn lại trên phần trước.',
        '- API lịch sử giá và sổ lệnh là nguồn khác nhau: '
        '[Polymarket prices-history](https://docs.polymarket.com/api-reference/markets/get-prices-history), '
        '[Polymarket order book](https://docs.polymarket.com/api-reference/market-data/get-order-book).','',
        'Chạy lại: `python -B research_remaining_losses_1230.py`. '
        'Chi tiết: `logs/remaining_losses_1230/summary.json`.']
    (ROOT/'REMAINING_LOSSES_1230_RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':run()
