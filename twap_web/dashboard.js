'use strict';

const $ = id => document.getElementById(id);
const zone = 'Asia/Ho_Chi_Minh';
const timeFormat = new Intl.DateTimeFormat('en-US', {timeZone: zone, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'});
const shortTime = new Intl.DateTimeFormat('en-US', {timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23'});
const dateFormat = new Intl.DateTimeFormat('en-US', {timeZone: zone, month: 'short', day: '2-digit'});
const usd = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', minimumFractionDigits: 2});
const orderPrice = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: 4});
const price = value => Number.isFinite(value) ? usd.format(value) : '—';
const time = value => Number.isFinite(value) ? timeFormat.format(value) : '—';
const colors = {twap: '#66edc3', spot: '#78aaff'};
const pending = new Set(['reserved', 'submitted', 'ambiguous']);
const orderStates = {
  reserved: ['Reserved', 'warn'], submitted: ['Submitted', 'blue'], ambiguous: ['Needs review', 'warn'],
  open: ['Open', 'good'], resolved: ['Resolved', 'blue'], rejected: ['Rejected', 'bad'],
  aborted_before_submit: ['Aborted before submit', 'muted'], unknown: ['Unknown', 'muted'],
};
const eventLabels = {
  twap_started: ['Bot started', 'system'], polygon_rpc_ready: ['Polygon approvals checked', 'system'],
  opening_recorded: ['Market opening TWAP recorded', 'system'], opening_conflict: ['Conflicting opening data', 'attention'],
  oracle_snapshot_or_recovery: ['Chainlink feed resynchronized', 'system'], oracle_wrong_source_or_window: ['Invalid oracle source or window', 'attention'],
  oracle_client_queue_drop: ['Oracle updates were dropped', 'attention'], oracle_stream_disconnected: ['Chainlink feed disconnected', 'attention'],
  legacy_imported: ['Legacy state imported', 'system'], twap_frozen_signal: ['TWAP signal locked', 'order'],
  twap_signal_skip: ['Signal skipped', 'skip'], twap_budget_skip: ['Trading limit reached', 'skip'],
  twap_entry_skip: ['Entry skipped', 'skip'], twap_recheck_skip: ['Signal recheck failed', 'skip'],
  twap_final_signal_or_deadline_skip: ['Stopped before order submission', 'skip'], twap_market_unavailable: ['Market data temporarily unavailable', 'attention'],
  twap_live_intent: ['Order attempt recorded', 'order'], twap_ambiguous_post: ['Order needs reconciliation', 'attention'],
  twap_order_result: ['Order response received', 'order'], twap_fill_awaiting_reconciliation: ['Awaiting fill confirmation', 'attention'],
  twap_resolved: ['Market resolved', 'order'], twap_redeemed: ['Position redeemed', 'order'],
  twap_redeem_needs_review: ['Redemption needs review', 'attention'], twap_tick_error: ['Monitoring loop error', 'attention'],
  twap_paper_candidate: ['Paper-trading candidate', 'system'],
};
const reasons = {
  opening_missing_late_or_invalid: 'Opening TWAP missing, late or invalid', oracle_warmup_gap_or_conflict: 'Oracle feed warming up or missing data',
  oracle_stale_or_missing: 'Oracle price is stale or missing', twap_lead_below_5bp: 'TWAP lead is below 5 bp',
  spot_not_supporting_twap: 'Spot does not confirm the TWAP direction', direction_changed_before_submit: 'Direction changed before submission',
  reference_missing_stale_or_below_085: 'Reference price is missing, stale or below 0.85',
  reference_plus_1c_ge_one: 'Reference plus one cent reaches 1.00',
  ask_above_frozen_reference_cap: 'Best ask exceeds the price cap', stale_book_or_slow_request: 'Order book is stale or request is slow',
  insufficient_haircut_depth_inside_cap: 'Insufficient depth inside the price cap', winning_margin_too_small: 'Potential winning margin is too small',
  lifetime_submission_limit: 'Lifetime submission limit reached', pending_or_unresolved_position: 'An order or position is unresolved',
  legacy_attempt_needs_reconciliation: 'A legacy order needs reconciliation', daily_loss_stop_utc: 'Daily UTC loss stop is active',
  network_geoblock_rejected: 'Geographic eligibility check failed', market_not_accepting_orders: 'Market is not accepting orders',
};

let data = null;
let receivedAt = 0;
let range = 15;
let busy = false;
let chartState = null;

function setStatus(label, tone) {
  $('bot-status').dataset.tone = tone;
  $('bot-status').lastElementChild.textContent = label;
}

function renderOverview() {
  const totals = data.journal.totals;
  const heartbeat = data.heartbeat;
  const recent = heartbeat && heartbeat.age_seconds <= 130;
  const alive = recent && heartbeat.clock_ok;
  if (!heartbeat) setStatus('Waiting for heartbeat', 'muted');
  else if (!recent) setStatus('Heartbeat is stale', 'warn');
  else if (!alive) setStatus('Clock needs attention', 'warn');
  else setStatus('Bot online', 'good');

  $('attempts').textContent = totals ? `${totals.attempts} / ${data.limits.max_orders}` : '—';
  $('attempt-note').textContent = totals?.attempts >= data.limits.max_orders ? 'Lifetime limit reached' : 'Lifetime submission limit';
  $('positions').textContent = totals?.open_positions ?? '—';
  $('position-note').textContent = totals ? `${totals.pending} pending · ${totals.legacy_pending} legacy` : 'From the bot journal';
  const settled = totals ? totals.wins + totals.losses : 0;
  $('winrate').textContent = settled ? `${(100 * totals.wins / settled).toFixed(1)}%` : '—';
  $('result-note').textContent = settled ? `${totals.wins} wins · ${totals.losses} losses · ${settled} resolved` : 'No resolved markets yet';
  const count = recent && heartbeat.feed_connected ? Number(heartbeat.twap_fresh) + Number(heartbeat.spot_fresh) : 0;
  $('feeds').textContent = recent ? `${count} / 2` : '—';
  $('feed-note').textContent = recent ? `TWAP ${heartbeat.twap_fresh ? 'fresh' : 'stale'} · Spot ${heartbeat.spot_fresh ? 'fresh' : 'stale'}` : 'Based on the latest heartbeat';
  $('clock-status').textContent = recent ? (heartbeat.clock_ok ? 'Synced' : 'Out of sync') : '—';
  $('clock-status').className = recent ? (alive ? 'text-good' : 'text-warn') : '';
  $('heartbeat-time').textContent = time(heartbeat?.at);

  const account = data.account;
  $('balance').textContent = account ? price(account.balance_usd) : '—';
  $('account-note').textContent = account ?
    (account.age_seconds <= 120 ? `pUSD · updated ${time(account.at)} · ${account.age_seconds}s ago` : `Stale snapshot · ${account.age_seconds}s ago`) :
    (data.journal.state === 'ready' ? 'Waiting for a live CLOB balance snapshot' : 'Balance unavailable');
  const wallet = data.journal.wallet;
  $('wallet').textContent = wallet ? `Wallet · ${wallet.slice(0, 6)}…${wallet.slice(-4)}` : 'Wallet · not bound';
  $('wallet').title = wallet ?? '';

  const latestTwap = data.prices.twap.at(-1)?.[1];
  $('twap-price').textContent = price(latestTwap);
  $('spot-price').textContent = price(data.prices.spot.at(-1)?.[1]);
  $('opening-price').textContent = price(data.journal.opening);
  const latestTime = data.prices.twap.at(-1)?.[0];
  const usable = Number.isFinite(latestTime) && data.now_ms - latestTime < 5000 && latestTime >= data.market.start_ms;
  const lead = usable && data.journal.opening > 0 ? 10000 * (latestTwap / data.journal.opening - 1) : null;
  $('lead').textContent = lead === null ? '—' : `${lead >= 0 ? '+' : ''}${lead.toFixed(2)} bp`;
  $('lead').className = lead === null ? '' : (lead >= 0 ? 'text-good' : 'text-bad');
  $('last-updated').textContent = `Updated ${time(data.now_ms)} · UTC+7`;
  const notice = $('notice');
  notice.hidden = data.journal.state === 'ready';
  notice.textContent = data.journal.state === 'missing' ? 'The bot journal was not found in the mounted volume.' : 'The journal is temporarily unavailable. Prices and activity may still update.';
}

function updateClock() {
  if (!data) return;
  const now = data.now_ms + performance.now() - receivedAt;
  const market = data.market;
  $('market-time').textContent = `${shortTime.format(market.start_ms)} – ${shortTime.format(market.end_ms)} · ${dateFormat.format(market.start_ms)}`;
  $('entry-time').textContent = shortTime.format(market.entry_ms);
  $('market-progress').value = Math.min(900, Math.max(0, (now - market.start_ms) / 1000));
  const link = $('market-link');
  link.href = `https://polymarket.com/event/btc-updown-15m-${market.start_ms / 1000}`;
  link.hidden = false;
  if (now >= market.end_ms) {
    $('countdown').textContent = '--:--';
    $('countdown-label').textContent = 'Waiting for the next market';
    return;
  }
  const phase = now < market.entry_ms ? ['Until entry window', market.entry_ms] :
    now <= market.entry_end_ms ? ['Entry window is open', market.entry_end_ms] : ['Until market close', market.end_ms];
  const seconds = Math.max(0, Math.ceil((phase[1] - now) / 1000));
  $('countdown').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  $('countdown-label').textContent = phase[0];
}

function svg(tag, attributes, label) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  if (label !== undefined) node.textContent = label;
  return node;
}

function renderChart() {
  if (!data) return;
  const chart = $('chart');
  chart.replaceChildren();
  $('chart-tooltip').hidden = true;
  chartState = null;
  const end = data.now_ms;
  const start = end - range * 60000;
  const series = Object.entries(data.prices).map(([kind, points]) => [kind, points.filter(([at]) => at >= start && at <= end)]);
  const values = series.flatMap(([, points]) => points.map(([, value]) => value));
  $('chart-empty').hidden = values.length > 0;
  if (!values.length) return;
  const opening = data.journal.opening;
  if (Number.isFinite(opening)) values.push(opening);
  const low = Math.min(...values), high = Math.max(...values);
  const padding = Math.max(1, (high - low) * .12);
  const min = low - padding, max = high + padding;
  const w = Math.max(260, chart.clientWidth), h = Math.max(140, chart.clientHeight);
  const left = 3, right = w - 68, top = 9, bottom = h - 24;
  const x = at => left + (at - start) * (right - left) / (end - start);
  const y = value => top + (max - value) * (bottom - top) / (max - min);
  chart.setAttribute('viewBox', `0 0 ${w} ${h}`);
  for (let i = 0; i <= 4; i++) {
    const row = top + i * (bottom - top) / 4;
    chart.append(svg('line', {x1:left, x2:right, y1:row, y2:row, stroke:'#24344b'}));
    chart.append(svg('text', {x:right+8, y:row+4, fill:'#9aabc2', 'font-size':10, 'font-family':'monospace'}, Math.round(max-i*(max-min)/4).toLocaleString('en-US')));
  }
  const ticks = w < 470 ? 3 : 6;
  for (let i = 0; i < ticks; i++) {
    const at = start + i * (end-start) / (ticks-1);
    chart.append(svg('text', {x:x(at), y:h-5, fill:'#9aabc2', 'font-size':10, 'font-family':'monospace', 'text-anchor':i===0?'start':i===ticks-1?'end':'middle'}, shortTime.format(at)));
  }
  if (Number.isFinite(opening)) {
    const openingStart = Math.max(start, data.market.start_ms);
    chart.append(svg('line', {x1:x(openingStart), x2:right, y1:y(opening), y2:y(opening), stroke:'#f4c77a', 'stroke-dasharray':'4 4', opacity:'.8'}));
  }
  for (const [kind, points] of series) {
    if (!points.length) continue;
    const path = points.map(([at,value], i) => `${!i || at-points[i-1][0]>12000 ? 'M' : 'L'}${x(at).toFixed(2)},${y(value).toFixed(2)}`).join(' ');
    chart.append(svg('path', {d:path, fill:'none', stroke:colors[kind], 'stroke-width':kind==='twap'?2.1:1.6, 'stroke-linejoin':'round', 'stroke-linecap':'round'}));
    const [at,value] = points.at(-1);
    chart.append(svg('circle', {cx:x(at), cy:y(value), r:3, fill:colors[kind], stroke:'#101a29', 'stroke-width':1}));
  }
  const cursor = svg('line', {x1:0,x2:0,y1:top,y2:bottom,stroke:'#788ca9','stroke-dasharray':'3 3',visibility:'hidden'});
  chart.append(cursor);
  chartState = {start, end, left, right, w, series, cursor};
}

function showChartTooltip(event) {
  if (!chartState) return;
  const {start,end,left,right,w,series,cursor} = chartState;
  const rect = $('chart').getBoundingClientRect();
  const pos = Math.min(right, Math.max(left, (event.clientX - rect.left) * w / rect.width));
  const at = start + (pos-left) * (end-start) / (right-left);
  const lines = [time(at)];
  for (const [kind, points] of series) {
    const nearest = points.reduce((best, point) => !best || Math.abs(point[0]-at) < Math.abs(best[0]-at) ? point : best, null);
    lines.push(`${kind === 'twap' ? 'TWAP' : 'Spot'}  ${nearest && Math.abs(nearest[0]-at)<=8000 ? price(nearest[1]) : '—'}`);
  }
  cursor.setAttribute('x1',pos);
  cursor.setAttribute('x2',pos);
  cursor.setAttribute('visibility','visible');
  const tip = $('chart-tooltip');
  tip.textContent = lines.join('\n');
  tip.hidden = false;
  tip.style.left = `${Math.max(0, Math.min(rect.width-tip.offsetWidth, pos*rect.width/w+10))}px`;
}

function badge(label, tone) {
  const item = document.createElement('span');
  item.className = 'badge';
  item.dataset.tone = tone;
  item.textContent = label;
  return item;
}

function renderOrders() {
  if (!data) return;
  const filter = $('order-filter').value;
  const query = $('search').value.trim().toLowerCase().replace(/^#/, '');
  const all = data.journal.orders;
  const orders = all.filter(order => (filter === 'all' || (filter === 'pending' ? pending.has(order.status) : order.status === filter))
      && (!query || `${order.id} ${order.slug ?? ''}`.toLowerCase().includes(query)));
  $('order-count').textContent = data.journal.totals ? `${orders.length} / ${data.journal.totals.attempts}` : '—';
  const body = $('order-rows');
  body.replaceChildren();
  for (const order of orders) {
    const row = document.createElement('tr');
    const add = (value, css = '') => {
      const cell = row.insertCell();
      cell.className = css;
      if (value instanceof Node) cell.append(value); else cell.textContent = value;
    };
    add(`#${order.id}`, 'mono');
    add(`${dateFormat.format(order.created_ms)} ${time(order.created_ms)}`, 'mono');
    if (order.slug) {
      const link = document.createElement('a');
      link.href = `https://polymarket.com/event/${order.slug}`;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = `${shortTime.format(Number(order.slug.split('-').at(-1)) * 1000)} · BTC 15m ↗`;
      link.title = order.slug;
      add(link);
    } else add('—');
    add(order.side ? order.side.toUpperCase() : '—', order.side === 'up' ? 'text-good' : order.side === 'down' ? 'text-warn' : '');
    add(price(order.budget), 'mono');
    add(Number.isFinite(order.shares) ? order.shares.toFixed(2) : '—', 'mono');
    add(Number.isFinite(order.notional) ? price(order.notional) : '—', 'mono');
    add(Number.isFinite(order.estimated_fee) ? price(order.estimated_fee) : '—', 'mono');
    add(Number.isFinite(order.max_cost) ? price(order.max_cost) : '—', 'mono');
    add(Number.isFinite(order.cap) ? orderPrice.format(order.cap) : '—', 'mono');
    add(badge(...orderStates[order.status]));
    const outcome = order.status === 'resolved' ? (order.won === 1 ? 'Win' : order.won === 0 ? 'Loss' : '—') : '—';
    add(outcome, outcome === 'Win' ? 'text-good' : outcome === 'Loss' ? 'text-bad' : '');
    const redemption = order.redeem_status === 'confirmed' ? 'Redeemed' :
      order.redeem_status === 'started' ? 'In progress' :
      order.redeem_status === 'ambiguous_check_wallet' ? 'Review needed' :
      order.redeem_status === 'zero_token_balance_or_already_redeemed' ? 'No balance / done' :
      order.redeem_status === 'not_requested' ? 'Not requested' : order.redeem_status;
    add(redemption, order.redeem_status === 'confirmed' ? 'text-good' : order.redeem_status === 'ambiguous_check_wallet' ? 'text-warn' : '');
    const detail = document.createElement('details');
    detail.className = 'order-detail';
    const summary = document.createElement('summary');
    summary.textContent = 'View';
    detail.append(summary);
    const quote = document.createElement('span');
    quote.textContent = `Reference ${Number.isFinite(order.reference_price) ? orderPrice.format(order.reference_price) : '—'}`;
    const entry = document.createElement('span');
    entry.textContent = `Signed average ${Number.isFinite(order.notional) && Number.isFinite(order.shares) && order.shares > 0 ? orderPrice.format(order.notional / order.shares) : '—'} per share`;
    const book = document.createElement('span');
    book.textContent = `Final bid / ask ${Number.isFinite(order.best_bid) ? orderPrice.format(order.best_bid) : '—'} / ${Number.isFinite(order.best_ask) ? orderPrice.format(order.best_ask) : '—'}`;
    const settledAt = document.createElement('span');
    settledAt.textContent = `Resolved ${Number.isFinite(order.settled_ms) ? `${dateFormat.format(order.settled_ms)} ${time(order.settled_ms)} UTC+7` : '—'}`;
    detail.append(quote, entry, book, settledAt);
    add(detail);
    body.append(row);
  }
  const empty = $('orders-empty');
  empty.hidden = orders.length > 0;
  empty.querySelector('strong').textContent = data.journal.state !== 'ready' ? 'Journal is not ready' : all.length ? 'No matching orders' : 'No order attempts yet';
  empty.querySelector('span').textContent = data.journal.state !== 'ready' ? 'Check the data volume and bot status.' : all.length ? 'Try another filter or search term.' : 'Orders appear when the bot records an eligible signal.';
}

function renderEvents() {
  if (!data) return;
  const filter = $('event-filter').value;
  const rows = $('event-rows');
  rows.replaceChildren();
  for (const event of data.events) {
    const [label,tone] = eventLabels[event.event];
    if (filter !== 'all' && filter !== tone) continue;
    const item = document.createElement('li');
    const at = document.createElement('time');
    at.className = 'event-time';
    at.textContent = time(event.at);
    const dot = document.createElement('i');
    dot.className = 'event-dot'; dot.dataset.tone = tone;
    const detail = document.createElement('div');
    detail.className = 'event-detail';
    const title = document.createElement('strong');
    title.textContent = label + (event.attempt_id === null ? '' : ` #${event.attempt_id}`);
    detail.append(title);
    if (event.reason || event.won !== null) {
      const context = document.createElement('span');
      context.textContent = event.reason ? (reasons[event.reason] ?? event.reason) : (event.won ? 'Win' : 'Loss');
      detail.append(context);
    }
    const market = document.createElement('span');
    market.className = 'event-market'; market.textContent = event.slug ?? '';
    item.append(at,dot,detail,market);
    rows.append(item);
  }
  $('events-empty').hidden = rows.children.length > 0;
  $('events-empty').textContent = 'No matching activity.';
}

async function refresh() {
  if (busy) return;
  busy = true;
  $('refresh').disabled = true;
  try {
    const response = await fetch('/api/status', {cache:'no-store', signal:AbortSignal.timeout(5000)});
    if (response.status === 401) { window.location.replace('/login'); return; }
    if (!response.ok) throw new Error('Dashboard API unavailable');
    data = await response.json();
    receivedAt = performance.now();
    renderOverview(); updateClock(); renderChart(); renderOrders(); renderEvents();
  } catch {
    setStatus('Connection lost', 'bad');
    $('notice').hidden = false;
    $('notice').textContent = 'Dashboard API is unavailable. Check the network connection and dashboard container.';
  } finally {
    busy = false;
    $('refresh').disabled = false;
  }
}

document.querySelectorAll('[data-range]').forEach(button => button.addEventListener('click', () => {
  range = Number(button.dataset.range);
  document.querySelectorAll('[data-range]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
  renderChart();
}));
$('chart').addEventListener('pointermove', showChartTooltip);
$('chart').addEventListener('pointerleave', () => {
  $('chart-tooltip').hidden = true;
  chartState?.cursor.setAttribute('visibility','hidden');
});
$('refresh').addEventListener('click', refresh);
$('logout').addEventListener('click', async () => {
  try { await fetch('/api/logout', {method:'POST', credentials:'same-origin', cache:'no-store'}); } finally { window.location.replace('/login'); }
});
$('search').addEventListener('input', renderOrders);
$('order-filter').addEventListener('change', renderOrders);
$('event-filter').addEventListener('change', renderEvents);
new ResizeObserver(renderChart).observe($('chart-wrap'));
setInterval(refresh,10000);
setInterval(updateClock,1000);
refresh();
