"""Pure, deterministic replay of fixed rules against observed books."""
import copy
from decimal import ROUND_DOWN

from .actual_research import buy_depth, dec


def quote(book, now_ms, protocol):
    age = now_ms - int(book['timestamp'])
    if not -1000 <= age <= protocol['maximum_quote_age_ms']:
        raise ValueError('stale_or_future_quote')
    asks = [dec(x['price']) for x in book['asks'] if dec(x['size']) > 0]
    bids = [dec(x['price']) for x in book['bids'] if dec(x['size']) > 0]
    if not asks or not bids:
        raise ValueError('empty_book')
    ask, bid = min(asks), max(bids)
    if bid >= ask or ask-bid > dec(protocol['maximum_spread']):
        raise ValueError('crossed_or_wide_spread')
    return ask, bid


def select_intent(side, books, now_ms, protocol):
    if side not in books:
        raise ValueError('no_signal_or_book')
    book = books[side]
    ask, _ = quote(book, now_ms, protocol)
    if ask < dec(protocol['minimum_ask']):
        raise ValueError('ask_below_filter')
    if ask > dec(protocol['maximum_price']):
        raise ValueError('ask_above_cap')
    tick = dec(book.get('tick_size', '0.01'))
    if tick <= 0:
        raise ValueError('invalid_tick')
    cap = min(dec(protocol['maximum_price']), ask + dec(protocol['price_padding']))
    cap = (cap/tick).to_integral_value(rounding=ROUND_DOWN)*tick
    return {'side': side, 'ask': str(ask), 'cap': str(cap), 'decision_ms': now_ms}


def favourite(books, now_ms, protocol):
    # Select direction using both contemporaneous midpoints, never the winner.
    scores = {}
    for side in ('up', 'down'):
        ask, bid = quote(books[side], now_ms, protocol)
        scores[side] = (ask+bid)/2
    if scores['up'] == scores['down']:
        raise ValueError('tied_favourite')
    return max(scores, key=scores.get)


def replay_fill(intent, book, fee, observed_ms, protocol, depth_fraction=1):
    if observed_ms < intent['decision_ms']:
        raise ValueError('arrival_before_decision')
    # Freeze the original cap: never raise it after seeing a later book.
    stressed = copy.deepcopy(book)
    if not 0 < depth_fraction <= 1:
        raise ValueError('invalid_depth_fraction')
    for level in stressed.get('asks', []):
        level['size'] = str(dec(level['size'])*dec(depth_fraction))
    return buy_depth(stressed, fee, budget=protocol['budget_usd'],
                     max_price=float(intent['cap']), now_ms=observed_ms,
                     max_age_ms=protocol['maximum_quote_age_ms'])


def bankroll_replay(rows, labels, initial=50, target=30):
    """Independent fixed-stake portfolio; settlement proceeds wait for observed label."""
    cash = float(initial)
    locked = []
    peak = cash
    drawdown = 0.
    taken = skipped = losses = max_losses = 0
    def release(now):
        nonlocal cash, locked, peak, drawdown, losses, max_losses
        locked.sort()
        while locked and locked[0][0] <= now:
            at, payout, cost = locked.pop(0)
            cash += payout
            losses = losses+1 if payout < cost else 0
            max_losses = max(max_losses, losses)
            # Other positions are marked at cost, not unrealized market prices.
            equity = cash + sum(x[2] for x in locked)
            peak = max(peak, equity)
            drawdown = max(drawdown, peak-equity)
    for row in sorted(rows, key=lambda x: (x['opened_ms'], x['slug'])):
        release(row['opened_ms'])
        if cash + 1e-8 < target:
            skipped += 1
            continue
        taken += 1
        cash -= row['cost']
        label = labels.get(row['slug'])
        payout = row['shares'] if label and row['side']==label['winner'] else 0.
        locked.append((label['received_ms'] if label else float('inf'), payout, row['cost']))
    release(10**16)
    return {'initial_cash': initial, 'cash_after_known_settlements': cash,
            'locked_cost': sum(x[2] for x in locked), 'taken': taken,
            'skipped_for_funds': skipped, 'max_realized_drawdown': drawdown,
            'max_realized_losing_streak': max_losses,
            'note': 'Credits at first observed confirmed label; assumes immediate redemption then. Pending positions held at cost; no intramarket mark-to-market or gas.'}
