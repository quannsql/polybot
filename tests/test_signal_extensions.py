import numpy as np
import pandas as pd
import pytest

from research_signal_extensions import (feature_tables, observation, policy_mask,
                                        metric, select_on_validation)


def candles():
    ix = pd.date_range('2026-05-01', periods=1200, freq='min', tz='UTC')
    price = 60000 + 20 * np.sin(np.arange(len(ix)) / 11) + np.arange(len(ix)) * .1
    return pd.DataFrame({'open': price, 'close': price, 'high': price + 2,
                         'low': price - 2, 'volume': 1.}, index=ix).rename_axis('timestamp')


def test_features_ignore_current_unfinished_and_future_candles():
    m = candles(); start = m.index[900]; delay = 630
    mf, bands = feature_tables(m)
    a = observation(m, mf, bands, start, delay, 'up')
    future = m.index >= start + pd.Timedelta(minutes=10)
    m.loc[future, ['open', 'high', 'low', 'close']] *= 2
    mf, bands = feature_tables(m)
    b = observation(m, mf, bands, start, delay, 'up')
    assert a == b
    assert a['feature_at'] <= start + pd.Timedelta(seconds=delay)


def test_gap_invalidates_distance_forecast():
    m = candles(); start = m.index[900]
    m.loc[start + pd.Timedelta(minutes=3), ['open','high','low','close']] = np.nan
    mf, bands = feature_tables(m)
    obs = observation(m, mf, bands, start, 630, 'up')
    assert np.isnan(obs['lead'])
    assert np.isnan(obs['normal_p_uncalibrated'])


def rows(n=120, period='validation'):
    return pd.DataFrame({
        'decision_at': pd.date_range('2026-05-01', periods=n, freq='15min', tz='UTC'),
        'delay': 630, 'period': period, 'reference': .8, 'cost_1c': .82,
        'cost_3c': .84, 'correct': True, 'pnl_1c': 1., 'pnl_3c': .8,
        'lead': .001, 'lead_z': 1.1, 'momentum3': .001,
        'normal_p_uncalibrated': .9, 'vol_ratio': 1.,
        'bb_reclaim': True, 'slope15_agrees': True, 'token_momentum2': .02,
    })


def test_selection_ignores_later_labels_and_pnl():
    data = pd.concat([rows(), rows(period='confirmation')], ignore_index=True)
    a = select_on_validation(data)
    data.loc[data.period.eq('confirmation'), ['pnl_1c','pnl_3c']] = -500
    data.loc[data.period.eq('confirmation'), 'correct'] = False
    assert a is not None
    assert a == select_on_validation(data)


def test_no_selection_if_training_stress_loses():
    data = rows(); data['pnl_3c'] = -1
    assert select_on_validation(data) is None


def test_price_cap_rejects_expensive_winner_without_looking_at_label():
    data = rows(3); data['reference'] = [.64, .80, .96]
    assert policy_mask(data, 'd630_cap95').tolist() == [False, True, False]
    data['correct'] = False
    assert policy_mask(data, 'd630_cap95').tolist() == [False, True, False]


def test_five_dollar_cash_equivalent_and_drawdown():
    data = rows(4); data['correct'] = [True, False, False, True]
    data['cost_1c'] = .8
    data['pnl_1c'] = 5 * (data.correct.astype(float) / data.cost_1c - 1)
    data['pnl_3c'] = data.pnl_1c
    result = metric(data)
    assert result['pnl_1c'] == pytest.approx(-7.5)
    assert result['avg_win_1c'] == pytest.approx(1.25)
    assert result['max_drawdown_1c'] == pytest.approx(10)
    assert result['max_loss_streak'] == 2
