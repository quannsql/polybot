"""Reference cap parity, verified venue fees and conservative full-book capacity."""
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from urllib.parse import urlparse

from .actual_research import history_asof, parse_market, fee_schedule, settlement
from .polymarket_api import PolymarketPublic

D = Decimal


def reference_cap(history, due_seconds, tick, settings):
    quote = history_asof(history,due_seconds,settings.reference_max_age_seconds)
    if quote is None or D(str(quote['price'])) < settings.min_entry_price:
        raise ValueError('reference_missing_stale_or_below_085')
    cap = D(str(quote['price']))+settings.reference_price_padding
    if cap >= 1:
        raise ValueError('reference_plus_1c_ge_one')
    cap = (min(settings.live_max_price,cap)/tick).to_integral_value(rounding=ROUND_DOWN)*tick
    if cap <= 0:
        raise ValueError('invalid_tick_rounded_cap')
    return quote,cap


def levels(raw, side):
    rows = raw.get(side)
    if not isinstance(rows,list):
        raise ValueError('missing_book_side')
    values = []
    for row in rows:
        price, size = D(str(row['price'])),D(str(row['size']))
        if not price.is_finite() or not size.is_finite() or not 0 < price < 1 or size <= 0:
            raise ValueError('invalid_book_level')
        values.append((price,size))
    return sorted(values,reverse=side=='bids')


def check_book(raw, token, cap, rate, settings, now_ms, rtt_ms=0, signed_shares=None):
    if str(raw.get('asset_id')) != str(token):
        raise ValueError('wrong_book_asset')
    stamp = raw.get('timestamp')
    if isinstance(stamp,bool) or not str(stamp).isdigit():
        raise ValueError('missing_book_timestamp')
    age = now_ms-int(stamp)
    if not -1000 <= age <= settings.live_quote_max_age_ms or rtt_ms > settings.live_quote_max_age_ms:
        raise ValueError('stale_book_or_slow_request')
    asks,bids = levels(raw,'asks'),levels(raw,'bids')
    if not asks or not bids or bids[0][0] >= asks[0][0]:
        raise ValueError('one_sided_or_crossed_book')
    if asks[0][0] > cap:
        raise ValueError('ask_above_frozen_reference_cap')
    # Worst price bound, not a forecast of the probability or expected profit.
    unit = cap+rate*cap*(1-cap)
    target = signed_shares if signed_shares is not None else settings.live_fixed_stake_usd/unit
    minimum = D(str(raw.get('min_order_size','5')))
    if target < minimum:
        raise ValueError('shares_below_venue_minimum')
    available = sum((size*settings.depth_fraction for price,size in asks if price <= cap),D(0))
    if available < target:
        raise ValueError('insufficient_haircut_depth_inside_cap')
    profit = settings.live_fixed_stake_usd/unit-settings.live_fixed_stake_usd
    if profit < settings.minimum_winning_pnl:
        raise ValueError('winning_margin_too_small')
    return dict(best_ask=asks[0][0],best_bid=bids[0][0],spread=asks[0][0]-bids[0][0],
        conservative_shares=target,available_haircut_shares=available,
        minimum_winning_pnl_at_cap=profit,book_timestamp_ms=int(stamp),rate=rate,cap=cap)


def check_signed(signed, token, cap, rate, settings):
    if str(signed.token_id) != str(token) or signed.side != 'BUY' or signed.order_type != 'FOK' or signed.post_only:
        raise ValueError('signed_order_identity_or_type_mismatch')
    if str(signed.maker).lower() != str(settings.wallet_address).lower():
        raise ValueError('signed_order_uses_wrong_wallet')
    if int(signed.maker_amount) <= 0 or int(signed.taker_amount) <= 0:
        raise ValueError('invalid_signed_amounts')
    notional,shares = D(signed.maker_amount)/1000000,D(signed.taker_amount)/1000000
    price = notional/shares
    # SDK may encode a fraction above cap due to amount rounding. No higher
    # supported tick (finest0.0001) may be reachable by this signature.
    reachable = (price/D('.0001')).to_integral_value(rounding=ROUND_DOWN)*D('.0001')
    if reachable > cap or not 0 < price < 1:
        raise ValueError('signed_price_exceeds_cap')
    if str(signed.builder).lower().replace('0x','').strip('0'):
        raise ValueError('unexpected_builder_fee_not_supported')
    fee = (shares*rate*price*(1-price)).quantize(D('.00001'),rounding=ROUND_UP)
    if notional+fee > settings.live_fixed_stake_usd:
        raise ValueError('signed_cash_plus_metadata_fee_exceeds_20')
    return dict(notional=notional,shares=shares,encoded_price=price,estimated_fee=fee,
                max_cost_under_checked_fee=notional+fee)


class TwapPublic(PolymarketPublic):
    def __init__(self, settings):
        super().__init__(settings,timeout=6)

    async def market_record(self, start):
        event = await self._get(f'{self.settings.gamma_url}/events/slug/btc-updown-15m-{start}')
        parsed = parse_market(event,start)
        raw = parsed['raw']
        source = urlparse(parsed['resolution_source'])
        config = raw.get('cryptoMarketConfig') or event.get('cryptoMarketConfig') or {}
        if source.scheme != 'https' or source.hostname != 'data.chain.link' or source.path.rstrip('/') != '/streams/btc-usd-twap-60s-streams' or raw.get('version','v1') != 'v1':
            raise ValueError('unsupported_settlement_stream_or_market_version')
        if config.get('twapEnabled') is not True or config.get('twapLookbackSeconds') != 60 or config.get('asset') != 'btc' or config.get('duration') != '15m':
            raise ValueError('market_is_not_verified_btc15m_twap60')
        info = await self._get(f'{self.settings.clob_url}/clob-markets/{parsed["condition_id"]}')
        fee = fee_schedule(parsed,info)
        if fee.get('status') != 'known':
            raise ValueError('unknown_or_disagreeing_fee_schedule')
        tick = D(str(raw.get('orderPriceMinTickSize')))
        if not tick.is_finite() or tick not in {D('.1'),D('.01'),D('.005'),D('.0025'),D('.001'),D('.0001')}:
            raise ValueError('unsupported_tick_size')
        return dict(event=event,parsed=parsed,fee=fee,tick=tick)

    async def raw_book(self, token):
        return await self._get(f'{self.settings.clob_url}/book',token_id=token)

    async def resolved(self, start):
        event = await self._get(f'{self.settings.gamma_url}/events/slug/btc-updown-15m-{start}')
        parsed = parse_market(event,start)
        clob = await self._get(f'{self.settings.clob_url}/markets/{parsed["condition_id"]}')
        return settlement(parsed,clob),parsed
