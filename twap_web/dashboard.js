'use strict';

const $ = id => document.getElementById(id);
const zone = 'Asia/Ho_Chi_Minh';
const timeFormat = new Intl.DateTimeFormat('vi-VN', {timeZone: zone, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'});
const shortTime = new Intl.DateTimeFormat('vi-VN', {timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23'});
const dateFormat = new Intl.DateTimeFormat('vi-VN', {timeZone: zone, day: '2-digit', month: '2-digit'});
const usd = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', minimumFractionDigits: 2});
const orderPrice = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: 4});
const price = value => Number.isFinite(value) ? usd.format(value) : '—';
const time = value => Number.isFinite(value) ? timeFormat.format(value) : '—';
const colors = {twap: '#66edc3', spot: '#78aaff'};
const pending = new Set(['reserved', 'submitted', 'ambiguous']);
const orderStates = {
  reserved: ['Giữ lượt thử', 'warn'], submitted: ['Đã gửi', 'blue'], ambiguous: ['Cần đối soát', 'warn'],
  open: ['Đang mở', 'good'], resolved: ['Đã chốt', 'blue'], rejected: ['Bị từ chối', 'bad'],
  aborted_before_submit: ['Dừng trước gửi', 'muted'], unknown: ['Chưa xác định', 'muted'],
};
const eventLabels = {
  twap_started: ['Khởi động bot', 'system'], polygon_rpc_ready: ['Đã kiểm tra approvals Polygon', 'system'],
  opening_recorded: ['Ghi nhận TWAP mở phiên', 'system'], opening_conflict: ['Dữ liệu opening mâu thuẫn', 'attention'],
  oracle_snapshot_or_recovery: ['Đồng bộ lại luồng Chainlink', 'system'], oracle_wrong_source_or_window: ['Nguồn hoặc cửa sổ oracle không hợp lệ', 'attention'],
  oracle_client_queue_drop: ['Luồng oracle bị hụt dữ liệu', 'attention'], oracle_stream_disconnected: ['Mất kết nối Chainlink', 'attention'],
  legacy_imported: ['Đã nạp trạng thái cũ', 'system'], twap_frozen_signal: ['Chốt tín hiệu TWAP', 'order'],
  twap_signal_skip: ['Bỏ qua tín hiệu', 'skip'], twap_budget_skip: ['Giới hạn giao dịch', 'skip'],
  twap_entry_skip: ['Bỏ qua điểm vào', 'skip'], twap_recheck_skip: ['Kiểm tra lại tín hiệu không đạt', 'skip'],
  twap_final_signal_or_deadline_skip: ['Dừng trước thời điểm gửi', 'skip'], twap_market_unavailable: ['Tạm thiếu dữ liệu market', 'attention'],
  twap_live_intent: ['Ghi nhận lượt thử lệnh', 'order'], twap_ambiguous_post: ['Lệnh cần đối soát', 'attention'],
  twap_order_result: ['Nhận phản hồi lệnh', 'order'], twap_fill_awaiting_reconciliation: ['Chờ xác nhận khớp lệnh', 'attention'],
  twap_resolved: ['Market đã phân giải', 'order'], twap_redeemed: ['Đã nhận tiền vị thế', 'order'],
  twap_redeem_needs_review: ['Cần đối soát thu hồi vị thế', 'attention'], twap_tick_error: ['Lỗi vòng theo dõi', 'attention'],
  twap_paper_candidate: ['Tín hiệu paper', 'system'],
};
const reasons = {
  opening_missing_late_or_invalid: 'Thiếu opening hợp lệ', oracle_warmup_gap_or_conflict: 'Luồng oracle đang làm ấm hoặc thiếu dữ liệu',
  oracle_stale_or_missing: 'Giá oracle đã cũ hoặc bị thiếu', twap_lead_below_5bp: 'Chênh TWAP dưới 5 bp',
  spot_not_supporting_twap: 'Spot chưa củng cố hướng TWAP', direction_changed_before_submit: 'Đổi hướng trước khi gửi',
  reference_missing_stale_or_below_085: 'Giá tham chiếu thiếu, cũ hoặc dưới 0,85',
  reference_plus_1c_ge_one: 'Giá tham chiếu cộng 1 cent chạm 1 USD',
  ask_above_frozen_reference_cap: 'Giá ask vượt giá trần', stale_book_or_slow_request: 'Sổ lệnh cũ hoặc phản hồi chậm',
  insufficient_haircut_depth_inside_cap: 'Thiếu độ sâu trong giá trần', winning_margin_too_small: 'Biên lợi nhuận quá thấp',
  lifetime_submission_limit: 'Đã hết lượt thử của đợt chạy', pending_or_unresolved_position: 'Còn lệnh hoặc vị thế cần xử lý',
  legacy_attempt_needs_reconciliation: 'Còn lệnh cũ cần đối soát', daily_loss_stop_utc: 'Đã dừng mua theo giới hạn lỗ trong ngày UTC',
  network_geoblock_rejected: 'Kiểm tra geography không đạt', market_not_accepting_orders: 'Market không nhận lệnh',
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
  if (!heartbeat) setStatus('Chờ heartbeat', 'muted');
  else if (!recent) setStatus('Heartbeat đã cũ', 'warn');
  else if (!alive) setStatus('Clock cần kiểm tra', 'warn');
  else setStatus('Bot đang chạy', 'good');

  $('attempts').textContent = totals ? `${totals.attempts} / ${data.limits.max_orders}` : '—';
  $('attempt-note').textContent = totals?.attempts >= data.limits.max_orders ? 'Đã dùng hết lượt thử' : 'Lượt thử ghi trong journal';
  $('positions').textContent = totals?.open_positions ?? '—';
  $('position-note').textContent = totals ? `${totals.pending} chờ đối soát · ${totals.legacy_pending} lệnh cũ` : 'Theo trạng thái trong journal';
  $('results').textContent = totals ? `${totals.wins} / ${totals.losses}` : '—';
  const settled = totals ? totals.wins + totals.losses : 0;
  $('result-note').textContent = settled ? `Thắng / thua · ${Math.round(100 * totals.wins / settled)}% thắng` : 'Thắng / thua đã xác nhận';
  const count = recent && heartbeat.feed_connected ? Number(heartbeat.twap_fresh) + Number(heartbeat.spot_fresh) : 0;
  $('feeds').textContent = recent ? `${count} / 2` : '—';
  $('feed-note').textContent = recent ? `TWAP ${heartbeat.twap_fresh ? 'mới' : 'đang chờ'} · Spot ${heartbeat.spot_fresh ? 'mới' : 'đang chờ'}` : 'Theo heartbeat gần nhất';
  $('clock-status').textContent = recent ? (heartbeat.clock_ok ? 'Đồng bộ' : 'Lệch giờ') : '—';
  $('clock-status').className = recent ? (alive ? 'text-good' : 'text-warn') : '';
  $('heartbeat-time').textContent = time(heartbeat?.at);

  const latestTwap = data.prices.twap.at(-1)?.[1];
  $('twap-price').textContent = price(latestTwap);
  $('spot-price').textContent = price(data.prices.spot.at(-1)?.[1]);
  $('opening-price').textContent = price(data.journal.opening);
  const latestTime = data.prices.twap.at(-1)?.[0];
  const usable = Number.isFinite(latestTime) && data.now_ms - latestTime < 5000 && latestTime >= data.market.start_ms;
  const lead = usable && data.journal.opening > 0 ? 10000 * (latestTwap / data.journal.opening - 1) : null;
  $('lead').textContent = lead === null ? '—' : `${lead >= 0 ? '+' : ''}${lead.toFixed(2)} bp`;
  $('lead').className = lead === null ? '' : (lead >= 0 ? 'text-good' : 'text-bad');
  $('last-updated').textContent = `Cập nhật ${time(data.now_ms)} · UTC+7`;
  const notice = $('notice');
  notice.hidden = data.journal.state === 'ready';
  notice.textContent = data.journal.state === 'missing' ? 'Chưa tìm thấy journal của bot trong volume.' : 'Tạm thời chưa đọc được journal. Giá và nhật ký vẫn có thể cập nhật.';
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
    $('countdown-label').textContent = 'Chờ dữ liệu phiên mới';
    return;
  }
  const phase = now < market.entry_ms ? ['Đến cửa sổ xét lệnh', market.entry_ms] :
    now <= market.entry_end_ms ? ['Cửa sổ xét lệnh đang mở', market.entry_end_ms] : ['Đến lúc đóng phiên', market.end_ms];
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
    add(Number.isFinite(order.cap) ? orderPrice.format(order.cap) : '—', 'mono');
    add(badge(...orderStates[order.status]));
    const outcome = order.status === 'resolved' ? (order.won === 1 ? 'Thắng' : order.won === 0 ? 'Thua' : '—') : '—';
    add(outcome, outcome === 'Thắng' ? 'text-good' : outcome === 'Thua' ? 'text-bad' : '');
    body.append(row);
  }
  const empty = $('orders-empty');
  empty.hidden = orders.length > 0;
  empty.querySelector('strong').textContent = data.journal.state !== 'ready' ? 'Journal chưa sẵn sàng' : all.length ? 'Không có lệnh phù hợp' : 'Chưa có lượt thử lệnh';
  empty.querySelector('span').textContent = data.journal.state !== 'ready' ? 'Kiểm tra volume dữ liệu và trạng thái bot.' : all.length ? 'Thử đổi bộ lọc hoặc từ khóa.' : 'Lịch sử sẽ xuất hiện khi bot ghi nhận tín hiệu đủ điều kiện.';
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
      context.textContent = event.reason ? (reasons[event.reason] ?? event.reason) : (event.won ? 'Thắng' : 'Thua');
      detail.append(context);
    }
    const market = document.createElement('span');
    market.className = 'event-market'; market.textContent = event.slug ?? '';
    item.append(at,dot,detail,market);
    rows.append(item);
  }
  $('events-empty').hidden = rows.children.length > 0;
  $('events-empty').textContent = 'Chưa có sự kiện phù hợp.';
}

async function refresh() {
  if (busy) return;
  busy = true;
  $('refresh').disabled = true;
  try {
    const response = await fetch('/api/status', {cache:'no-store', signal:AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error('Dashboard API unavailable');
    data = await response.json();
    receivedAt = performance.now();
    renderOverview(); updateClock(); renderChart(); renderOrders(); renderEvents();
  } catch {
    setStatus('Mất kết nối', 'bad');
    $('notice').hidden = false;
    $('notice').textContent = 'Không đọc được dashboard API. Kiểm tra phiên SSH và container dashboard.';
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
$('search').addEventListener('input', renderOrders);
$('order-filter').addEventListener('change', renderOrders);
$('event-filter').addEventListener('change', renderEvents);
new ResizeObserver(renderChart).observe($('chart-wrap'));
setInterval(refresh,10000);
setInterval(updateClock,1000);
refresh();
