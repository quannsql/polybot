import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from audit_poly_research import bars5, label, walk_forward
from polymarket_bot.signal_grid import features, raw_signals, select_windows
from polymarket_bot.signal import snapshot


def price_frame(n=9000):
    rng = np.random.default_rng(12)
    close = 100*np.exp(np.cumsum(rng.normal(0,.002,n)))
    return pd.DataFrame({'timestamp':pd.date_range('2026-01-01',periods=n,freq='5min',tz='UTC'),
                         'open':close,'high':close,'low':close,'close':close,'volume':np.ones(n)})


def test_mapping_never_uses_signal_after_window_start():
    stamps = pd.to_datetime(['2026-01-01 09:05Z','2026-01-01 09:10Z','2026-01-01 09:15Z',
                             '2026-01-01 09:20Z'],utc=True)
    f = pd.DataFrame({'signal_at':stamps,'side':['up']*4})
    fixed = select_windows(f,policy='latest_5m')
    assert fixed.signal_at.tolist() == [stamps[2],stamps[3]]
    assert fixed.decision_at.dt.minute.tolist() == [15,30]
    assert fixed.signal_age_minutes.tolist() == [0,10]
    assert not fixed.decision_at.duplicated().any()
    assert len(select_windows(f,policy='boundary')) == 1
    assert len(select_windows(f,policy='rolling_15m')) == 4


def test_features_and_predictions_invariant_to_future_prices():
    f = price_frame()
    cut = 8100  # a 15m boundary, after daily warmup
    prefix = features(f.iloc[:cut])
    full = features(f)
    pd.testing.assert_frame_equal(prefix,full.iloc[:cut].reset_index(drop=True))
    at = f.timestamp.iloc[cut]
    for policy in ['boundary','latest_5m']:
        a = snapshot(f,decision_at=at,policy=policy)
        changed = f.copy()
        changed.loc[cut:,['open','high','low','close']] *= 20
        assert snapshot(changed,decision_at=at,policy=policy) == a
        windows = select_windows(raw_signals(prefix,session_start=0,session_end=0),policy=policy)
        selected = windows.loc[windows.decision_at.eq(at)]
        assert a.direction == (None if selected.empty else selected.iloc[-1].side)


def test_missing_day_never_defaults_to_long_and_gap_invalidates_indicators():
    f = price_frame()
    grid = features(f)
    assert grid.loc[grid.decision_at < pd.Timestamp('2026-01-26',tz='UTC'),'route'].isna().all()
    broken = features(f.drop(index=7500))
    assert not broken.loc[7500:7529,'valid5'].any()
    assert broken.loc[broken.decision_at.dt.floor('D').eq(pd.Timestamp('2026-01-28',tz='UTC')),'route'].isna().all()


def test_snapshot_matches_both_batch_policies_on_actual_signals():
    f = price_frame()
    raw = raw_signals(features(f),session_start=0,session_end=0)
    for policy in ['boundary','latest_5m']:
        selected = select_windows(raw,policy=policy)
        selected = selected.loc[selected.decision_at <= f.timestamp.max()]
        for row in selected.iloc[::max(1,len(selected)//15)].itertuples():
            live = snapshot(f,decision_at=row.decision_at,policy=policy)
            assert (live.direction,live.source) == (row.side,row.source)


def test_labels_reject_missing_minute_and_keep_fixed_start():
    m = price_frame(30).set_index('timestamp')
    m.index = pd.date_range('2026-01-01',periods=30,freq='min',tz='UTC')
    at = m.index[0]
    f = pd.DataFrame({'decision_at':[at],'end_at':[at+pd.Timedelta(minutes=15)],'side':['up']})
    assert label(f,m).start_price.iloc[0] == m.open.iloc[0]
    m.loc[m.index[7], 'close'] = np.nan
    assert label(f,m).empty
    assert pd.isna(bars5(m).close.iloc[1])


def test_monthly_fit_excludes_unsettled_and_future_labels():
    times = pd.to_datetime(['2026-01-31 23:30Z','2026-01-31 23:55Z','2026-02-01 00:00Z'])
    f = pd.DataFrame({'decision_at':times,'end_at':times+pd.Timedelta(minutes=15),
                       'source':['main_5m']*3,'side':['up']*3,'correct':[True,False,False]})
    cut = pd.Timestamp('2026-02-01',tz='UTC')
    a = walk_forward(f,cut,cut+pd.Timedelta(days=1))
    assert a.n_train.iloc[0] == 1
    assert a.p_train.iloc[0] == pytest.approx(2/3)
    f.loc[1:,'correct'] = True
    b = walk_forward(f,cut,cut+pd.Timedelta(days=1))
    assert b.p_train.tolist() == a.p_train.tolist()


def test_raw_direction_matches_readonly_dca_contract():
    source = Path('D:/backtest/band_dca_lane.py')
    if not source.exists():
        pytest.skip('Optional read-only Bot1 reference unavailable')
    # The imported reference has pure functions only; prevent bytecode writes in Bot1.
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location('_dca_reference',source)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    f = price_frame()
    grid = features(f)
    daily = f.set_index('timestamp').close.resample('1D').last().reset_index()
    for router in [False,True]:
        raw = raw_signals(grid,router_enabled=router,session_start=0,session_end=0)
        by_time = raw.set_index('decision_at')
        cfg = module.BandDcaConfig(enabled=True,short_router_enabled=router,
                                   short_lane_15m_enabled=True,session_start_utc=0,session_end_utc=0)
        # Include every observed signal and a regular sample of no-signal rows.
        check = grid.loc[grid.decision_at.isin(raw.decision_at) | grid.index.to_series().mod(37).eq(0)]
        for row in check.itertuples():
            if not row.valid5:
                continue
            route = module.daily_route(daily,now=row.decision_at)
            side = 'long' if not router else (route.side if route else None)
            aux = (row.decision_at.minute%15 == 0 and row.valid15 == True and
                   module.short_lane_15m_signal(cfg,close_15m=row.close15,
                    bb_upper_15m=row.upper15,close_60m_ago=row.close15/(1+row.run60/10000)))
            main = side is not None and module.entry_decision(module.BandDcaState(symbol='BTC'),cfg,
                    close_5m=row.close,bb_lower_5m=row.lower5,bb_upper_5m=row.upper5,
                    side=side,now=row.decision_at)[0]
            expected = 'down' if aux else ('up' if side=='long' else 'down') if main else None
            actual = by_time.loc[row.decision_at,'side'] if row.decision_at in by_time.index else None
            assert actual == expected
