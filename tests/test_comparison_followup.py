from research_comparison_followup import QueueLeg,price_sensitivity


def test_queue_only_exact_price_sell_consumes_ahead_before_our_fill():
    leg=QueueLeg('up',.49,10,5)
    leg.trade('up','buy',.49,100)
    leg.trade('down','sell',.49,100)
    leg.trade('up','sell',.48,100)
    assert leg.queue==10 and leg.filled==0
    leg.trade('up','sell',.49,12)
    assert leg.queue==0 and leg.filled==2
    leg.trade('up','sell',.49,100)
    assert leg.filled==5


def test_freshness_sensitivity_does_not_turn_no_data_into_zero_profit():
    feature=dict(start=100000,delay=840,side='up',absolute_lead_bps=10)
    record=dict(settlement=dict(status='confirmed',winner='up'),fee=dict(status='known',rate=.07),
        up_history=dict(status=200,body=dict(history=[dict(t=100810,p=.9)])))
    rows=price_sensitivity([feature],{100000:record})
    old=next(x for x in rows if x['delay']==840 and x['buffer_bps']==5 and x['max_reference_age']==75 and x['padding']==.01)
    fresh=next(x for x in rows if x['delay']==840 and x['buffer_bps']==5 and x['max_reference_age']==15 and x['padding']==.01)
    assert old['n']==1 and old['pnl']>0
    assert fresh['n']==0 and fresh['pnl'] is None
