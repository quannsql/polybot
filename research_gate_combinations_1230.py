"""Second-stage, explicitly retrospective research on the frozen 410 candidates.

Rule inputs are whitelisted before scoring; no order paths or live changes.
The family was motivated by losses already inspected, so chronological scoring
does not turn this archive into an untouched out-of-sample evaluation.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from audit_poly_research import read_minutes
from polymarket_bot.robustness import bankroll_replay
from research_signal_extensions import feature_tables, observation

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT/'logs/loss_gates_1230/candidates.json'
OUT = ROOT/'logs/gate_combinations_1230'


def rule_suite():
    """Bounded coarse family, frozen before this run; no arbitrary subset search."""
    rules = [{'id':'original'}]
    for vol in (1.25,1.5,1.75):
        rules.append({'id':f'quiet_{vol:g}', 'vol_cap':vol})
    for flag in ('memory','early','aux_shock','old_signal','weak'):
        rules.append({'id':f'veto_{flag}','blocks':[[flag,None]]})
    for z in (.75,1.,1.25,1.5):
        rules.append({'id':f'lead_{z:g}','min_z':z})
    for z in (.75,1.,1.25):
        for flag in ('memory','early','old_signal','weak'):
            rules.append({'id':f'{flag}_if_zlt{z:g}','blocks':[[flag,z]]})
    for vol in (1.25,1.5,1.75):
        for z in (.75,1.,1.25):
            for flags in (['memory'],['memory','old_signal'],['memory','old_signal','aux_shock']):
                # Shock clause is unconditional; memory/stale are conditional on a weak lead.
                rules.append({'id':f'q{vol:g}_z{z:g}_'+ '_'.join(flags), 'vol_cap':vol,
                              'blocks':[[f,None if f=='aux_shock' else z] for f in flags]})
    for flag in ('memory','early','aux_shock'):
        rules.append({'id':f'q1.5_veto_{flag}','vol_cap':1.5,'blocks':[[flag,None]]})
    for z in (.75,1.,1.25):
        rules.append({'id':f'q1.5_z{z:g}_memory_old_weak', 'vol_cap':1.5,
                      'blocks':[[f,z] for f in ('memory','old_signal','weak')]})
    return rules


RULES = rule_suite()
PROTOCOL = {
    'base':'Original DCA 5m+aux15m, T+750s, ref>=.85, same frozen 410 candidates',
    'budget':20,'bankroll':50,'rules':RULES,
    'hypothesis_status':'Second-stage family informed by already inspected 12 losses; retrospective, not independent confirmation.',
    'grid':'Vol 5m/60m caps 1.25/1.5/1.75; conditional lead Z .75/1/1.25. '
           'Z>=1.5 is a high-win reference, not a hand-fitted boundary. No continuous optimization.',
    'flags':'memory=Bot1 memory_rsi at original signal; early and weak=Bot1 gates at T+10; '
            'aux_shock=Bot1 auxiliary shock at T+10; old_signal=age>=10 minutes at market start.',
    'selection':'On training data only: retain >=max(100,50% of training); +1c and +2c gain positive; '
                'at least 2 of 3 chronological thirds have nonnegative +1c gain; no third loses >$20 vs base. '
                'Rank min(total gain +1c,+2c), fewer clauses then stable ID. Otherwise original.',
    'split':'Apr19-Jul13 training, Jul14-Sep03 later; later data previously seen.',
    'walkforward':'Jun/Jul/Aug/Sep: choose with outcomes ended <=month start minus 24h.',
    'robustness':'Report all rules; paired 3-day block bootstrap with centered max-t family check, '
                 'leave-one-loss-out reselection, one extra model-loss stress, feature staleness 1/2 minutes, '
                 'cost pads1/2/3c, fixed wallet50. No claim these repair prior adaptive data reuse.',
    'execution':'Historical reference+padding assumed fill, cached cash-equivalent fees. '
                'Stress price>=1 becomes explicit nonfill on SAME original candidates; no measured depth or latency.',
    'timing':'Features through closed 1m at T+12 and closed 5m at T+10. '
             'Older-feature sensitivity is not actual order-book slippage. No future rows in a gate.',
}


def dump(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')


def inputs(row, lag=0):
    f=row['features'] if not lag else row['lagged_features'][str(lag)]
    return {'vol':f['vol_ratio'], 'z':f['lead_z'],
        'memory':not row['keep']['dca_memory_rsi_signal'],
        'early':not row['keep']['dca_early_direction_entry'],
        'weak':not row['keep']['dca_weak10_turn_entry'],
        'aux_shock':not row['keep']['dca_aux_shock_entry'],
        'old_signal':row['signal_age_minutes'] >= 10}


def decide(x,rule):
    for feature,param,comparison in [('vol','vol_cap',lambda a,b:a<=b),('z','min_z',lambda a,b:a>=b)]:
        if param in rule and (x[feature] is None or not np.isfinite(x[feature]) or not comparison(x[feature],rule[param])):
            return False
    for flag,z in rule.get('blocks',[]):
        if x[flag]:
            if z is None: return False
            if x['z'] is None or not np.isfinite(x['z']) or x['z'] < z: return False
    return True


def masks(rows,lag=0):
    return np.array([[decide(inputs(r,lag),rule) for r in rows] for rule in RULES],dtype=bool)


def scores(rows,mask):
    ix=np.asarray(mask,dtype=bool); win=np.array([r['won'] for r in rows],dtype=bool)
    n=int(ix.sum()); w=int((ix&win).sum())
    r={'n':n,'wins':w,'losses':n-w,'win_rate':w/n if n else None,
       'avoided_losses':int((~ix&~win).sum()),'removed_winners':int((~ix&win).sum())}
    for c in (1,2,3):
        pnl=np.array([r[f'pnl{c}'] for r in rows],dtype=float)
        costs=np.array([r[f'cost{c}'] for r in rows],dtype=float)
        r[f'pnl{c}']=float(pnl[ix].sum()); r[f'delta{c}']=float(-pnl[~ix].sum())
        filled=ix&(costs>0)
        r[f'fills{c}']=int(filled.sum());r[f'nonfills{c}']=int((ix&~filled).sum())
        r[f'filled_losses{c}']=int((filled&~win).sum())
        r[f'filled_win_rate{c}']=float(win[filled].mean()) if filled.any() else None
        r[f'nonfill_would_lose{c}']=int((ix&~filled&~win).sum())
    r['mean_pnl1']=r['pnl1']/n if n else None
    r['sacrificed_winner_profit1']=sum(row['pnl1'] for row,k in zip(rows,ix) if not k and row['won'])
    path=np.r_[0.,np.cumsum([row['pnl1'] for row,k in zip(rows,ix) if k])]
    r['max_drawdown1']=float((np.maximum.accumulate(path)-path).max())
    return r


def choose(rows, matrix):
    """Only caller-provided ended training observations can influence selection."""
    if not rows:return 0
    boundaries=np.linspace(min(r['start'] for r in rows),max(r['end_ms']/1000 for r in rows),4)
    candidates=[]
    for i,rule in enumerate(RULES[1:],1):
        s=scores(rows,matrix[i])
        if s['n']<max(100,len(rows)*.5) or s['delta1']<=0 or s['delta2']<=0:continue
        thirds=[]
        for left,right in zip(boundaries[:-1],boundaries[1:]):
            thirds.append(-sum(r['pnl1'] for r,k in zip(rows,matrix[i]) if not k and left<=r['start']<right))
        if sum(v>=0 for v in thirds)<2 or min(thirds)<-20:continue
        complexity=len(rule.get('blocks',[]))+int('vol_cap' in rule)+int('min_z' in rule)
        candidates.append((-min(s['delta1'],s['delta2']),complexity,rule['id'],i))
    return sorted(candidates)[0][-1] if candidates else 0


def walkforward(rows, matrix):
    selected_mask=np.zeros(len(rows),dtype=bool); evaluated=np.zeros(len(rows),dtype=bool);folds=[]
    for cut in pd.date_range('2026-06-01','2026-09-01',freq='MS',tz='UTC'):
        training=np.array([r['end_ms']<=(cut.timestamp()-86400)*1000 for r in rows])
        test=np.array([cut.timestamp()<=r['start']<(cut+pd.offsets.MonthBegin(1)).timestamp() for r in rows])
        i=choose([r for r,k in zip(rows,training) if k],matrix[:,training])
        selected_mask[test]=matrix[i,test]; evaluated|=test
        part=[r for r,k in zip(rows,test) if k]
        folds.append({'month':str(cut.date()),'rule':RULES[i]['id'],'train_n':int(training.sum()),
                      'test':scores(part,matrix[i,test]),'baseline':scores(part,np.ones(len(part),bool))})
    part=[r for r,k in zip(rows,evaluated) if k]
    return {'folds':folds,'strategy':scores(part,selected_mask[evaluated]),
            'baseline':scores(part,np.ones(len(part),bool))}


def bootstrap(rows,matrix,repetitions=4000):
    """Paired daily differences; same resampled 3-day blocks for every rule.

    Centered maximum studentized mean is an approximate family check over this
    fixed family, not a correction for all earlier iterations of this project.
    """
    first=int(pd.Timestamp('2026-04-19',tz='UTC').timestamp())//86400
    last=int(pd.Timestamp('2026-09-03',tz='UTC').timestamp())//86400
    n_days=last-first+1
    daily=np.zeros((n_days,len(RULES)))
    pnl=np.array([r['pnl1'] for r in rows])
    delta=(matrix.astype(float)-1)*pnl
    for j,r in enumerate(rows):daily[r['start']//86400-first]+=delta[:,j]
    rng=np.random.default_rng(20260915)
    starts=rng.integers(0,n_days,(repetitions,(n_days+2)//3))
    idx=((starts[:,:,None]+np.arange(3))%n_days).reshape(repetitions,-1)[:,:n_days]
    draws=daily[idx].sum(axis=1)/len(rows)
    means=delta.sum(axis=1)/len(rows); se=draws.std(axis=0,ddof=1)
    stable=se>1e-12
    centered=np.zeros_like(draws);centered[:,stable]=(draws[:,stable]-means[stable])/se[stable]
    max_t=centered[:,stable].max(axis=1) if stable.any() else np.zeros(repetitions)
    result={}
    for i,r in enumerate(RULES):
        t=means[i]/se[i] if stable[i] else 0.
        result[r['id']]={'paired_gain_per_original_candidate_ci95':np.quantile(draws[:,i],[.025,.975]).tolist(),
            'family_max_t_p_approx':float((1+(max_t>=t).sum())/(repetitions+1)) if stable[i] else 1.,
            'note':'Exploratory only; family-specific correction does not account for earlier adaptive study reuse.'}
    return result


def add_lags(rows):
    prior=json.loads((ROOT/'logs/loss_gates_1230/summary.json').read_text(encoding='utf-8'))['manifest']['btc']
    m,metadata=read_minutes([Path(s['path']) for s in prior['sources']])
    assert [s['sha256'] for s in metadata['sources']]==[s['sha256'] for s in prior['sources']]
    mf,bands=feature_tables(m)
    for r in rows:
        r['lagged_features']={}
        for lag in (1,2):
            x=observation(m,mf,bands,pd.Timestamp(r['start'],unit='s',tz='UTC'),750-60*lag,r['side'])
            r['lagged_features'][str(lag)]={k:float(x[k]) if np.isfinite(x[k]) else None for k in ('vol_ratio','lead_z')}


def evaluate(rows):
    matrix=masks(rows); before=np.array([r['period']=='validation' for r in rows])
    chosen=choose([r for r,k in zip(rows,before) if k],matrix[:,before])
    dump(OUT/'chosen_using_earlier_only.json',{'id':RULES[chosen]['id'],'rule':PROTOCOL['selection']})
    result={}
    for i,rule in enumerate(RULES):
        result[rule['id']]={'rule':rule}
        for period,which in [('validation',before),('confirmation',~before),('all',np.ones(len(rows),bool))]:
            part=[r for r,k in zip(rows,which) if k]
            result[rule['id']][period]=scores(part,matrix[i,which])
    hindsight=max(range(len(RULES)),key=lambda i:(result[RULES[i]['id']]['all']['pnl1'],-i))
    # This is a hindsight shortlist, deliberately labelled; it cannot be called holdout selection.
    balanced=[i for i,r in enumerate(RULES) if result[r['id']]['all']['n']>=.5*len(rows)
              and result[r['id']]['all']['win_rate']>=.98
              and all(result[r['id']][p][f'delta{c}']>0 for p in ('validation','confirmation') for c in (1,2))]
    balanced_i=max(balanced,key=lambda i:result[RULES[i]['id']]['all']['pnl1']) if balanced else 0
    intervals=bootstrap(rows,matrix)
    for key,value in intervals.items():result[key]['uncertainty']=value
    lags={k:masks(rows,k) for k in (1,2)}
    report={'protocol':PROTOCOL,'selected_earlier':RULES[chosen]['id'],
            'hindsight_max_pnl':RULES[hindsight]['id'],'hindsight_balanced':RULES[balanced_i]['id'],
            'results':result,'walkforward':walkforward(rows,matrix)}
    focus=sorted({0,chosen,hindsight,balanced_i,
                  next(i for i,r in enumerate(RULES) if r['id']=='quiet_1.5'),
                  next(i for i,r in enumerate(RULES) if r['id']=='q1.5_z1_memory')})
    report['focus_details']={}
    # Remove each of the 11 training losses and reselect without looking at later labels.
    stability=[]
    for index,r in enumerate(rows):
        if not before[index] or r['won']:continue
        train=before.copy();train[index]=False
        j=choose([r for r,k in zip(rows,train) if k],matrix[:,train])
        later=[r for r,k in zip(rows,~before) if k]
        stability.append({'omitted_loss':r['slug'],'selected':RULES[j]['id'],
                          'later':scores(later,matrix[j,~before])})
    report['leave_one_training_loss_out']=stability
    for i in focus:
        rule=RULES[i]; detail={}
        detail['data_lag_1m']=scores(rows,lags[1][i]); detail['data_lag_2m']=scores(rows,lags[2][i])
        detail['losses_avoided']=[r['slug'] for r,k in zip(rows,matrix[i]) if not k and not r['won']]
        detail['losses_retained']=[r['slug'] for r,k in zip(rows,matrix[i]) if k and not r['won']]
        detail['missing_inputs_used_by_dca']=dict(Counter(reason for r in rows for k,reason in r['diagnostics'].items()
            if any(w in str(reason) for w in ('unavailable','unaligned','invalid')) and
            k in {'dca_memory_rsi_signal','dca_early_direction_entry','dca_aux_shock_entry','dca_weak10_turn_entry'}))
        detail['monthly']={}
        for month in sorted({pd.Timestamp(r['start'],unit='s').strftime('%Y-%m') for r in rows}):
            ix=np.array([pd.Timestamp(r['start'],unit='s').strftime('%Y-%m')==month for r in rows])
            detail['monthly'][month]=scores([r for r,k in zip(rows,ix) if k],matrix[i,ix])
        for delay in (0,300,1800):
            taken=[dict(r,cost=r['cost1'],shares=r['shares1']) for r,k in zip(rows,matrix[i]) if k]
            labels={r['slug']:{'winner':r['winner'],'received_ms':r['end_ms']+delay*1000} for r in taken}
            detail[f'bankroll50_redemption_delay_{delay}s']=bankroll_replay(taken,labels,50,20)
        detail['pnl1_if_one_extra_retained_win_turns_loss']=result[rule['id']]['all']['pnl1']-max(
            (r['shares1'] for r,k in zip(rows,matrix[i]) if k and r['won']),default=0)
        # Counterfactual: one vetoed would-lose turns out to have won. Baseline improves too.
        gain=result[rule['id']]['all']['delta1']
        detail['delta1_if_one_avoided_loss_were_winner']=gain-max(
            (r['shares1'] for r,k in zip(rows,matrix[i]) if not k and not r['won']),default=0)
        report['focus_details'][rule['id']]=detail
    return report,matrix


def write_report(report):
    lines=['# Nghiên cứu phối hợp gate 12:30 — giai đoạn 2','',
        f"Đã thử {len(RULES)-1} biến thể + đối chứng trên cùng 410 lệnh. $20/lệnh, giữ Boll gốc và 12:30. "
        'Lưới được xây dựng sau khi đã xem 12 lệnh thua, nên mọi kết quả là thăm dò trên lịch sử đã biết.','',
        f"Gate chọn bằng 86 ngày trước: `{report['selected_earlier']}`. "
        f"Gate PnL cao nhất khi nhìn cả mẫu: `{report['hindsight_max_pnl']}`. "
        f"Gate cân bằng trong mẫu (giữ>=50%, win>=98%, tăng PnL cả hai giai đoạn ở +1c/+2c): `{report['hindsight_balanced']}`.",'',
        '## Diễn giải các ứng viên chính','',
        'Hướng thực dụng để tiếp tục thử là `q1.5_z1_memory`: chỉ hai điều kiện bổ sung. '
        'Đây là lựa chọn đánh giá thủ công sau khi xem bảng, ưu tiên đơn giản và giữ nhiều cơ hội, '
        'không phải gate đã được selector chọn trước khi biết kết quả.', '',
        '1. Bỏ nếu std log-return1m của 5 phút / 60 phút >1,5.',
        '2. Với nhánh main_5m, nếu Memory RSI ở tín hiệu gốc báo bất lợi, chỉ bỏ khi lead Z tại close T+12 <1. '
        'Nếu Memory RSI báo bất lợi nhưng giá đã đi đủ xa đúng hướng (Z>=1), cho đi tiếp. '
        'Lead Z = signed log(close T+12/open T) / [std30(log-return1m) × sqrt(3)].', '',
        'Memory RSI là gate thuần của DCA: giữ cảnh báo early-direction gốc hoặc cảnh báo trong 120 phút '
        'khi DI/RSI vẫn bất lợi. Gate này áp riêng nhánh main, không thay hướng DCA đã chọn. '
        'Ý nghĩa là tránh loại máy móc một cơ hội mà giá đã hồi đúng hướng đủ xa.', '',
        '| Ứng viên | Thắng/tổng | Win-rate | Tránh thua / bỏ thắng | PnL +1c | PnL/lệnh |',
        '|---|---:|---:|---:|---:|---:|']
    for key in dict.fromkeys(['original','quiet_1.5','q1.5_z1_memory',report['hindsight_balanced'],report['hindsight_max_pnl'],'lead_1.5']):
        m=report['results'][key]['all']
        lines.append(f"| {key} | {m['wins']}/{m['n']} | {m['win_rate']:.2%} | {m['avoided_losses']} / {m['removed_winners']} | "
                     f"${m['pnl1']:+.2f} | ${m['mean_pnl1']:+.3f} |")
    simple=report['results']['q1.5_z1_memory']; best=report['results'][report['hindsight_max_pnl']]
    lines += ['',f"Gate đơn giản tiết kiệm ${simple['all']['avoided_losses']*20:.2f} thua nhưng bỏ "
        f"${simple['all']['sacrificed_winner_profit1']:.2f} lãi thắng; tăng ròng ${simple['all']['delta1']:.2f}. "
        f"PnL trước/sau: ${simple['validation']['pnl1']:+.2f} / ${simple['confirmation']['pnl1']:+.2f}.", '',
        f"Gate PnL cao nhất trong toàn mẫu còn {best['all']['losses']} thua. Nó thêm điều kiện tuổi tín hiệu>=10 phút "
        'và aux shock, dùng Z<1,25 cho memory/tuổi tín hiệu. '
        f"Giai đoạn sau đạt ${best['confirmation']['pnl1']:+.2f}, thấp hơn gốc "
        f"${report['results']['original']['confirmation']['pnl1']:+.2f}. "
        'Vì vậy PnL toàn mẫu cao nhất không đồng nghĩa cấu hình đáng tin nhất.', '',
        '## Lân cận ngưỡng của ứng viên đơn giản', '',
        '| Cap biến động / Z | Lệnh | Thua | PnL trước | PnL sau | Tổng +1c |',
        '|---|---:|---:|---:|---:|---:|']
    for key in ['q1.25_z1_memory','q1.5_z1_memory','q1.75_z1_memory','q1.5_z0.75_memory','q1.5_z1.25_memory']:
        a,b,c=[report['results'][key][p] for p in ('validation','confirmation','all')]
        lines.append(f"| {key} | {c['n']} | {c['losses']} | ${a['pnl1']:+.2f} | ${b['pnl1']:+.2f} | ${c['pnl1']:+.2f} |")
    lines += ['', 'Khi vol cap=1,75, lệnh thua 11/08 với ratio~1,736 không bị chặn nữa. '
        'Các ngưỡng xung quanh vẫn tăng tổng PnL trong mẫu, nhưng cải thiện giai đoạn sau không đồng đều. '
        'Không tối ưu thành ngưỡng khớp riêng từng lệnh thua.', '',
        '## Bảng đầy đủ','',
        '| Quy tắc | Thắng/tổng | Tránh thua / bỏ thắng | Win-rate | PnL trước | PnL sau | Tổng +1c | +2c | +3c |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for rule in RULES:
        k=rule['id'];a,b,c=[report['results'][k][p] for p in ('validation','confirmation','all')]
        lines.append(f"| {k} | {c['wins']}/{c['n']} | {c['avoided_losses']}/{c['removed_winners']} | {c['win_rate']:.2%} | "
            f"${a['pnl1']:+.2f} | ${b['pnl1']:+.2f} | ${c['pnl1']:+.2f} | ${c['pnl2']:+.2f} | ${c['pnl3']:+.2f} |")
    lines+=['','q=vol cap; z=lead threshold dùng khi cờ DCA/tuổi tín hiệu bất lợi. '
        'memory đọc tại tín hiệu gốc; early/weak/aux_shock ở nến đóng T+10; old_signal=tuổi>=10 phút. '
        'Gate có blocks chỉ veto khi cờ bật VÀ Z dưới ngưỡng; aux_shock veto không phụ thuộc Z. '
        'vol luôn kiểm tra ở close1m cuối biết được T+12. Chi tiết công thức: protocol.json.','',
        '## Quy trình chọn theo thời gian','',
        '| Tháng kiểm tra | Gate chọn bằng dữ liệu cũ | PnL | PnL gốc |','|---|---|---:|---:|']
    for f in report['walkforward']['folds']:
        lines.append(f"| {f['month']} | {f['rule']} | ${f['test']['pnl1']:+.2f} | ${f['baseline']['pnl1']:+.2f} |")
    a,b=report['walkforward']['strategy'],report['walkforward']['baseline']
    lines+=['',f"Tổng walk-forward: ${a['pnl1']:+.2f}; đối chứng cùng tháng ${b['pnl1']:+.2f}. "
            'Đây là chấm theo thời gian trên một họ gate đã biết lịch sử; không phải bằng chứng triển khai ngoài mẫu.','',
        '## Độ nhạy và vốn $50','',
        '| Gate | PnL +1c | Feature cũ thêm 1m / 2m | Ví50 cuối (trả tiền ngay hết hạn) | CI95 paired gain/lệnh gốc | p họ gate xấp xỉ |',
        '|---|---:|---:|---:|---:|---:|']
    for k,f in report['focus_details'].items():
        r=report['results'][k];lo,hi=r['uncertainty']['paired_gain_per_original_candidate_ci95']
        lines.append(f"| {k} | ${r['all']['pnl1']:+.2f} | ${f['data_lag_1m']['pnl1']:+.2f} / ${f['data_lag_2m']['pnl1']:+.2f} | "
            f"${f['bankroll50_redemption_delay_0s']['cash_after_known_settlements']:.2f} | [{lo:+.3f};{hi:+.3f}] | "
            f"{r['uncertainty']['family_max_t_p_approx']:.3f} |")
    lines+=['','Thay độ mới feature không phải thay thời điểm khớp. Dữ liệu giá/book thật ở 12:30 chưa có trong archive. '
        'p được tính bằng centered max-t trên block3 ngày cho họ gate lần này; không sửa được việc dữ liệu đã được xem '
        'nhiều lần. CI và p chỉ chẩn đoán, không phải chứng nhận lợi nhuận.','',
        '## Bỏ từng lệnh thua khỏi training rồi chọn lại','']
    counts=Counter(f['selected'] for f in report['leave_one_training_loss_out'])
    for k,n in counts.items():lines.append(f'- `{k}`: {n}/{len(report["leave_one_training_loss_out"])} lần.')
    lines+=['','## Giới hạn','',
        '- Không thay nguyên tắc cố định hướng Boll, không chọn gate theo ngày hoặc slug. '
        'Mọi phép loại đều chấm cả thắng bị bỏ và thua tránh được.',
        '- Pad1/2/3c và phí cash-equivalent cache là giả định. Không có historical depth/ask thực thi; '
        'giá>=1 là nonfill có ghi rõ, giữ tập ứng viên cố định. Gas/vận hành/nạp-rút chưa tính.',
        '- Một vài gate DCA thiếu dữ liệu peer/indicator thì giữ cơ chế cho qua của Bot1; JSON ghi chẩn đoán. '
        'Các kiểm tra Z/vol thiếu số liệu thì không cấp phép dựa trên số liệu đó.',
        '- Các nhãn theo settlement cache Polymarket. Nguồn tín hiệu Lighter không luôn trùng Chainlink.',
        '- Ví50 giả định redemption0/5/30 phút sau hết hạn; không suy ra timing on-chain đã được đo.',
        '- Không đổi config live/paper, không deploy. Scripts và artifacts chỉ nằm trong polybot.','',
        'Tái chạy: `python -B research_gate_combinations_1230.py`. '
        'JSON: `logs/gate_combinations_1230/{summary,candidates,protocol}.json`.']
    (ROOT/'GATE_COMBINATIONS_1230_RESULT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    OUT.mkdir(parents=True,exist_ok=True);dump(OUT/'protocol.json',PROTOCOL)
    rows=json.loads(SOURCE.read_text(encoding='utf-8'))
    assert len(rows)==410 and sum(r['won'] for r in rows)==398
    assert abs(sum(r['pnl1'] for r in rows)-132.149707693452)<1e-8
    add_lags(rows);report,matrix=evaluate(rows)
    report['manifest']={'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        'source_audit_summary_sha256':hashlib.sha256((SOURCE.parent/'summary.json').read_bytes()).hexdigest(),
        'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    dump(OUT/'summary.json',report)
    dump(OUT/'candidates.json',[dict(r,combination_keep={rule['id']:bool(matrix[i,j]) for i,rule in enumerate(RULES)})
                               for j,r in enumerate(rows)])
    write_report(report)
    print('rules',len(RULES),'selected',report['selected_earlier'],'hindsight',report['hindsight_max_pnl'],
          'balanced',report['hindsight_balanced'],flush=True)
    for k in sorted(report['results'],key=lambda k:-report['results'][k]['all']['pnl1'])[:12]:
        r=report['results'][k]; a=r['all']; print(k,a['n'],a['losses'],round(a['pnl1'],2),
            round(r['confirmation']['pnl1'],2),round(a['pnl2'],2),flush=True)
    print('walkforward',report['walkforward']['strategy']['pnl1'],report['walkforward']['baseline']['pnl1'])


if __name__=='__main__': main()
