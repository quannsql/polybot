"""Public-data validation and conservative paper execution; no order methods."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_UP
import hashlib
import json
from typing import Any


def dec(value: Any) -> Decimal:
    try:
        x = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('Invalid decimal') from None
    if not x.is_finite():
        raise ValueError('Non-finite decimal')
    return x


def array(value: Any) -> list:
    x = json.loads(value) if isinstance(value, str) else value
    if not isinstance(x, list):
        raise ValueError('Expected array')
    return x


def parse_market(event: dict, start: int) -> dict:
    slug = f'btc-updown-15m-{start}'
    if event.get('slug') != slug or len(event.get('markets', [])) != 1:
        raise ValueError('Unexpected market identity')
    m = event['markets'][0]
    if m.get('slug') != slug or not m.get('conditionId'):
        raise ValueError('Missing/mismatched market identity')
    from datetime import datetime
    def stamp(s):
        return int(datetime.fromisoformat(s.replace('Z','+00:00')).timestamp())
    if stamp(m['endDate']) != start+900:
        raise ValueError('Market end differs from 15m window')
    if m.get('eventStartTime') and stamp(m['eventStartTime']) != start:
        raise ValueError('Event window start mismatch')
    outcomes = array(m['outcomes'])
    tokens = array(m['clobTokenIds'])
    if len(outcomes) != 2 or len(tokens) != 2 or {str(x).lower() for x in outcomes} != {'up','down'}:
        raise ValueError('Not binary Up/Down')
    if len(set(tokens)) != 2:
        raise ValueError('Duplicate token IDs')
    description = str(m.get('description',''))
    source = str(m.get('resolutionSource',''))
    rule = (description+' '+source).lower()
    if 'chainlink' not in rule:
        raise ValueError('Unsupported resolution source for this BTC15m study')
    return {'slug':slug, 'start':start,'end':start+900,'condition_id':m['conditionId'],
        'tokens':dict(zip([str(x).lower() for x in outcomes], map(str,tokens))),
        'rule_type':'chainlink_twap' if 'twap' in rule or 'time-weighted' in rule else 'chainlink_spot',
        'rule_sha256':hashlib.sha256((description+'\n'+source).encode()).hexdigest(),
        'resolution_source':source, 'raw':m}


def settlement(market: dict, clob: dict) -> dict:
    """Require closed + finalized Gamma + agreeing explicit CLOB token winner.

    This is API-confirmed settlement, not an independently verified onchain proof.
    Never turn lastTradePrice/bestAsk or an unresolved near-1 price into a winner.
    """
    m = market['raw']
    if clob.get('condition_id') != market['condition_id']:
        return {'status':'identity_mismatch','winner':None}
    if m.get('closed') is not True or clob.get('closed') is not True or m.get('umaResolutionStatus') != 'resolved':
        return {'status':'not_final','winner':None}
    if clob.get('is_50_50_outcome') is True:
        return {'status':'non_binary_or_void','winner':None}
    prices = array(m.get('outcomePrices',[]))
    labels = [str(x).lower() for x in array(m['outcomes'])]
    if len(prices) != 2 or sorted(map(dec,prices)) != [Decimal(0),Decimal(1)]:
        return {'status':'non_binary_or_void','winner':None}
    gamma_winner = labels[[dec(x) for x in prices].index(Decimal(1))]
    tokens = clob.get('tokens',[])
    if len(tokens) != 2 or {str(t.get('token_id')) for t in tokens} != set(market['tokens'].values()):
        return {'status':'token_mismatch','winner':None}
    winners = [str(t['token_id']) for t in tokens if t.get('winner') is True]
    if winners != [market['tokens'][gamma_winner]]:
        return {'status':'winner_disagreement','winner':None}
    return {'status':'confirmed','winner':gamma_winner,'source':'Gamma resolved + CLOB winner agreement'}


def fee_schedule(market: dict, info: dict | None = None) -> dict:
    """Read the actual market curve, not base_fee/10000 or a global default.

    Only the documented current exponent-1 cash-equivalent model is implemented.
    Other schedules are retained as unsupported rather than silently approximated.
    """
    m = market['raw']
    if m.get('feesEnabled') is False:
        if info is not None and dec((info.get('fd') or {}).get('r',0) or 0)!=0:
            return {'status':'fee_disagreement'}
        return {'status':'known','rate':0.,'exponent':1.,'source':'feesEnabled=false'}
    f = m.get('feeSchedule') or {}
    if m.get('feesEnabled') is not True or f.get('rate') is None or f.get('exponent') is None:
        return {'status':'unknown'}
    r, e = dec(f['rate']),dec(f['exponent'])
    if r < 0 or r > 1 or e != 1:
        return {'status':'unsupported','rate':float(r),'exponent':float(e)}
    if info is not None:
        fd = info.get('fd') or {}
        if info.get('c') != market['condition_id'] or fd.get('r') is None or fd.get('e') is None:
            return {'status':'clob_fee_missing'}
        if dec(fd['r']) != r or dec(fd['e']) != e:
            return {'status':'fee_disagreement'}
    return {'status':'known','rate':float(r),'exponent':float(e),
        'source':'Gamma feeSchedule'+(' + CLOB fd' if info is not None else ''),
        'historical_validity':'metadata fetched now, not an as-of historical fee attestation'}


def history_asof(history: list, when: int, max_age: int=75) -> dict | None:
    points = [p for p in history if isinstance(p,dict) and isinstance(p.get('t'),(int,float))
              and when-max_age <= p['t'] <= when and 0 < dec(p.get('p')) < 1]
    if not points:
        return None
    latest = max(p['t'] for p in points)
    same = [p for p in points if p['t']==latest]
    if len({dec(p['p']) for p in same}) != 1:
        return None
    p = same[-1]
    return {'timestamp':int(p['t']),'price':float(p['p']),'age_seconds':when-int(p['t']),
            'kind':'historical_reference_not_executable_ask'}


def cash_cost(price: float, fee: dict) -> float:
    if fee.get('status') != 'known':
        raise ValueError('Unknown fee curve')
    q = dec(price)
    if not 0 < q < 1:
        raise ValueError('Price outside binary range')
    return float(q + dec(fee['rate'])*q*(1-q))


def buy_depth(book: dict, fee: dict, *, budget: float, max_price: float,
              now_ms: int, max_age_ms: int=5000) -> dict:
    """All-or-nothing shadow fill through asks; fee cash-equivalent upper rounding.

    Conservative dual minimum (shares and notional) avoids ambiguity across API
    versions. No maker fills; no midpoint fills; stale/crossed books fail closed.
    This describes displayed liquidity, not a guaranteed or submitted fill.
    """
    if fee.get('status') != 'known':
        raise ValueError('Unknown fees')
    timestamp = int(book['timestamp'])
    if timestamp > now_ms+1000 or now_ms-timestamp > max_age_ms:
        raise ValueError('Stale/future book')
    cap, remaining = dec(max_price), dec(budget)
    if remaining <= 0 or not 0 < cap < 1:
        raise ValueError('Invalid budget/limit')
    def levels(side):
        x = [(dec(v['price']),dec(v['size'])) for v in book.get(side,[])]
        if any(not 0<p<1 or s<=0 for p,s in x):
            raise ValueError('Malformed book level')
        return sorted(x,reverse=(side=='bids'))
    asks,bids=levels('asks'),levels('bids')
    if not asks or not bids or bids[0][0]>=asks[0][0]:
        raise ValueError('Empty/crossed book')
    rate=dec(fee['rate']); shares=Decimal(0); notional=Decimal(0); charged=Decimal(0); fills=[]
    for price,size in asks:
        if price>cap:
            break
        per=rate*price*(1-price)
        # Leave one fee-precision unit to stay inside the total budget.
        qty=min(size,max(Decimal(0),remaining-Decimal('0.00001'))/(price+per))
        if qty<=0:
            break
        charge=(qty*per).quantize(Decimal('0.00001'),rounding=ROUND_UP)
        value=qty*price
        remaining-=value+charge; shares+=qty; notional+=value; charged+=charge
        fills.append({'price':str(price),'shares':str(qty),'fee_cash_equivalent':str(charge)})
        if remaining<=Decimal('0.00002'):
            break
    if remaining>Decimal('0.01') or shares<=0:
        raise ValueError('Insufficient displayed depth inside price cap')
    minimum=dec(book.get('min_order_size',5))
    if shares<minimum or notional<minimum:
        raise ValueError('Below conservative minimum size')
    return {'shares':float(shares),'notional':float(notional),'fee_cash_equivalent':float(charged),
        'total_cost':float(notional+charged),'vwap':float(notional/shares),
        'break_even_probability':float((notional+charged)/shares),'fills':fills,
        'kind':'displayed_depth_shadow_fill_not_exchange_fill'}
