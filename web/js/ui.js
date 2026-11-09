// 页面上的面板：顶栏、动态、住户、设置、聊天、住户卡片。
import { api, esc, hhmm, mdhm, clockText, toast } from './util.js';
import { exportGlb } from './avatar.js';
import { Replay } from './replay.js';
import { prefsPanel } from './prefs.js';

const $ = (id) => document.getElementById(id);
const S = { residents: new Map(), home: {}, feed: [], feedOldest: null, chat: [], pending: [], world: null, people: null };
const STATUS = { idle: '醒着', busy: '在忙', asleep: '睡着了', offline: '离线' };
const KIND_ICON = { activity: '⚡', sleep: '☾', wake: '☀', system: '!', chat: '💬', together: '👥', interact: '♥',
  weather: '☂', festival: '✦', event: '✧', visit: '⌂', note: '✉', goal: '★', party: '🎉', movein: '📦' };
const NEED_LABEL = { energy: '精力', hunger: '饱腹', social: '社交', fun: '开心' };
const MEM_KIND = { auto: '', owner: '你教的', together: '一起', summary: '整理', chat: '聊过' };

export function replay() { return S.replay; }

export function init({ world, people, state }) {
  S.world = world; S.people = people;
  S.replay = new Replay(world, people, async () => {
    const st = await api('/api/state');
    st.residents.forEach((r) => people.update(r));
    world.setHour(new Date(Date.now() + st.home.utc_offset * 1000).getUTCHours() + new Date().getUTCMinutes() / 60);
    world.setWeather(st.home.weather.kind);
  });
  setHome(state.home);
  state.residents.forEach((r) => S.residents.set(r.id, r));
  setPending(state.pending || []);
  bindChrome();
  renderWho(); renderPeople(); renderChips(); renderSettings();
  loadFeed(); loadChat();
}

export function resync(state) {
  setHome(state.home);
  S.residents.clear();
  state.residents.forEach((r) => S.residents.set(r.id, r));
  setPending(state.pending || []);
  renderWho(); renderPeople(); renderChips(); renderSettings();
  loadFeed(); loadChat();
}

// ---------------------------------------------------------------- 住户和顶栏
function nameOf(id) {
  if (id === 'owner') return S.home.owner || '我';
  return S.residents.get(id)?.name || id || '小窝';
}
function colorOf(id) { return S.residents.get(id)?.color || '#8a8594'; }
function avatarStyle(id) {
  const r = S.residents.get(id);
  const img = r?.images?.front ? `background-image:url('/skin/${r.images.front}');` : '';
  return `--c:${colorOf(id)};${img}`;
}

export function setHome(home) {
  S.home = home;
  $('home-name').textContent = home.name || '小窝';
  document.title = home.name || '小窝';
  const mode = [];
  if (home.mock) mode.push('模拟住户');
  if (home.fast) mode.push('加速');
  if (home.paused) mode.push('全屋暂停中');
  $('home-mode').textContent = mode.join(' · ');
  $('home-mode').classList.toggle('hidden', !mode.length);
  if (home.weather) {
    $('home-weather').textContent = `${home.weather.icon} ${home.weather.label}${home.festival ? ` · ${home.festival}` : ''}`;
    S.world?.homeOffset !== undefined && (S.world.homeOffset = home.utc_offset);
    S.world?.setWeather(home.weather.kind);
    S.world?.setFestival(home.festival || '');
  }
  const unread = home.unread_notes || 0;
  $('notes-badge').textContent = unread;
  $('notes-badge').classList.toggle('hidden', !unread);
  renderSettings();
}

export function tickClock() { $('home-clock').textContent = `小窝时间 · ${clockText()}`; }

export function resident(r) {
  S.residents.set(r.id, r);
  renderWho(); renderPeople(); renderTyping();
  if (S.cardId === r.id) refreshCard(false);
}

function renderWho() {
  const all = [...S.residents.values()];
  const awake = all.filter((r) => r.status === 'idle' || r.status === 'busy').map((r) => r.name);
  const asleep = all.filter((r) => r.status === 'asleep').map((r) => r.name);
  let t = awake.length ? `在家：${awake.join('、')}` : '都睡了';
  if (awake.length && asleep.length) t += `（${asleep.join('、')} 在睡）`;
  $('home-who').textContent = t;
}

function renderPeople() {
  $('people').innerHTML = [...S.residents.values()].map((r) => `
    <div class="pp" data-id="${esc(r.id)}" style="--c:${esc(r.color)}">
      <div class="av" style="${avatarStyle(r.id)}"></div>
      <div class="nm">${esc(r.name)}<small>${esc(r.model_label)}</small></div>
      <div class="st"><span class="dot ${esc(r.status)}"></span>${esc(STATUS[r.status] || r.status)} · ${esc(r.status === 'offline' ? (r.note || r.ready_info) : (r.place ? r.place + ' · ' : '') + r.activity)}</div>
      <div class="ac">${esc(r.access_label)} · 今日 ${r.calls_today}/${r.daily_calls} 次</div>
    </div>`).join('');
  $('people').querySelectorAll('.pp').forEach((el) => el.addEventListener('click', () => openCard(el.dataset.id)));
}

function renderChips() {
  $('chips').innerHTML = [...S.residents.values()].map((r) => `<button type="button" style="--c:${esc(r.color)}" data-name="${esc(r.name)}">@${esc(r.name)}</button>`).join('');
  $('chips').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => mention(b.dataset.name)));
}

function mention(name) {
  const inp = $('say-text');
  const tag = `@${name} `;
  if (!inp.value.includes(tag)) inp.value = (inp.value && !inp.value.endsWith(' ') ? inp.value + ' ' : inp.value) + tag;
  inp.focus();
}

// ---------------------------------------------------------------- 动态
async function loadFeed(more = false) {
  const q = more && S.feedOldest ? `?before=${S.feedOldest}` : '';
  const { items } = await api('/api/feed' + q);
  if (!more) S.feed = [];
  S.feed.push(...items);
  S.feedOldest = items.length ? items[items.length - 1].id : S.feedOldest;
  renderFeed(items.length === 40);
}

function feedItem(f) {
  const link = f.url ? ` · <a href="${esc(f.url)}" target="_blank" rel="noopener">原链接</a>` : '';
  const detail = f.detail ? `「${esc(f.detail)}」` : '';
  const who = f.resident ? nameOf(f.resident) : '小窝';
  return `<div class="fi ${esc(f.kind)}" data-id="${f.id}">
    <div class="av" style="${avatarStyle(f.resident)}"></div>
    <div class="who">${esc(who)}<span class="when">${KIND_ICON[f.kind] || ''} ${mdhm(f.ts)}</span></div>
    <button class="more" title="展开">⌄</button>
    <div class="txt">${esc(f.text)}</div>
    <div class="detail">${detail}${link}</div>
    ${f.kind === 'activity' ? `<button class="seen ${f.seen ? 'done' : ''}">${f.seen ? '已看到' : '看到了'}</button>` : ''}
  </div>`;
}

function renderFeed(hasMore) {
  $('feed').innerHTML = S.feed.map(feedItem).join('') + (hasMore ? '<button class="older">更早的动态</button>' : '');
  bindFeed($('feed'));
  $('feed').querySelector('.older')?.addEventListener('click', () => loadFeed(true));
}

function bindFeed(root) {
  root.querySelectorAll('.fi').forEach((el) => {
    if (el.dataset.bound) return;
    el.dataset.bound = '1';
    el.querySelector('.more').addEventListener('click', () => el.classList.toggle('open'));
    el.querySelector('.txt').addEventListener('click', () => el.classList.toggle('open'));
    el.querySelector('.av').addEventListener('click', () => { const f = S.feed.find((x) => x.id == el.dataset.id); if (f?.resident) openCard(f.resident); });
    const seen = el.querySelector('.seen:not(.done)');
    if (seen) seen.addEventListener('click', async () => {
      await api(`/api/feed/${el.dataset.id}/seen`, { method: 'POST' });
      seen.textContent = '已看到'; seen.classList.add('done');
    });
  });
}

export function addFeed(f) {
  S.feed.unshift(f);
  const wrap = document.createElement('div');
  wrap.innerHTML = feedItem(f);
  const el = wrap.firstElementChild;
  $('feed').prepend(el);
  bindFeed($('feed'));
}

export function updateFeed(f) {
  const i = S.feed.findIndex((x) => x.id === f.id);
  if (i >= 0) S.feed[i] = f;
  const el = $('feed').querySelector(`.fi[data-id="${f.id}"]`);
  if (el && f.seen) { const b = el.querySelector('.seen'); if (b) { b.textContent = '已看到'; b.classList.add('done'); } }
}

// ---------------------------------------------------------------- 聊天
async function loadChat() {
  const { items } = await api('/api/chat?limit=80');
  S.chat = items;
  $('msgs').innerHTML = items.length ? items.map(chatItem).join('') : '<div class="empty-chat">群里还没人说话</div>';
  renderTyping();
  scrollChat(true);
}

function chatItem(c) {
  const me = c.sender === 'owner';
  return `<div class="msg ${me ? 'me' : ''}" style="--c:${esc(colorOf(c.sender))}">
    <div class="who">${esc(nameOf(c.sender))}<span class="when">${hhmm(c.ts)}</span></div><div class="t">${esc(c.text)}</div></div>`;
}

function scrollChat(force) {
  const m = $('msgs');
  if (force || m.scrollHeight - m.scrollTop - m.clientHeight < 120) m.scrollTop = m.scrollHeight;
}

export function addChat(c) {
  S.chat.push(c);
  $('msgs').querySelector('.typing-row')?.remove();
  $('msgs').querySelector('.empty-chat')?.remove();
  $('msgs').insertAdjacentHTML('beforeend', chatItem(c));
  renderTyping();
  scrollChat(c.sender === 'owner');
}

function renderTyping() {
  $('msgs').querySelector('.typing-row')?.remove();
  const typing = [...S.residents.values()].filter((r) => r.typing).map((r) => r.name);
  if (typing.length) {
    $('msgs').insertAdjacentHTML('beforeend', `<div class="msg typing typing-row"><div class="t">${esc(typing.join('、'))} 正在输入…</div></div>`);
    scrollChat(false);
  }
}

export function setPending(list) {
  S.pending = list;
  $('pending-n').textContent = list.length ? `(${list.length})` : '';
  $('pending-list').innerHTML = list.length
    ? list.map((p) => `<div class="pi"><b style="color:${esc(colorOf(p.resident))}">${esc(nameOf(p.resident))}</b>：${esc(p.text)}</div>`).join('')
    : '<div class="pi">没有人在等</div>';
}

// ---------------------------------------------------------------- 住户卡片
export async function openCard(id) {
  S.cardId = id;
  await refreshCard(true);
}

function cardStatus(r) {
  const pct = Math.min(100, Math.round((r.calls_today * 100) / Math.max(1, r.daily_calls)));
  return `<div class="top">
      <div class="portrait">${r.images?.front ? `<img src="/skin/${esc(r.images.front)}" alt="">` : ''}</div>
      <div>
        <h3>${esc(r.name)}</h3>
        <div class="sub">${esc(r.model_label)} · ${esc(r.access_label)}</div>
        <div class="line"><span class="dot ${esc(r.status)}"></span>${esc(STATUS[r.status] || r.status)}</div>
        <div class="line">${esc(r.place || '')}${r.place ? ' · ' : ''}${esc(r.activity)}</div>
        <div class="line" style="font-size:13px;color:var(--ink-2)">今天调用 ${r.calls_today} / ${r.daily_calls} 次${r.fails_today ? `，失败 ${r.fails_today}` : ''}</div>
        <div class="bar"><i style="width:${pct}%"></i></div>
      </div>
    </div>
    ${r.note ? `<div class="note">${esc(r.note)}</div>` : ''}
    ${r.status !== 'offline' && r.needs ? `<div class="needs"><div class="mood">${esc(r.mood?.icon || '')} ${esc(r.mood?.label || '')}</div>
      ${Object.entries(NEED_LABEL).map(([k, n]) => `<div class="need"><span>${n}</span><b><i style="width:${r.needs[k]}%"></i></b></div>`).join('')}
      ${r.goal ? `<div class="goal">最近想${esc(r.goal.label)}<em>${r.goal.done}/${r.goal.need}</em></div>` : ''}</div>` : ''}`;
}

async function refreshCard(full) {
  const id = S.cardId;
  if (!id) return;
  if (!full) {            // 住户状态刷新只更新上半截，不打断正在编辑的记忆
    S.cardData = { ...S.cardData, ...S.residents.get(id) };
    const live = $('card').querySelector('.live');
    if (live) live.innerHTML = cardStatus(S.cardData);
    return;
  }
  const r = await api(`/api/residents/${encodeURIComponent(id)}`);
  S.cardData = r;
  const card = $('card');
  card.style.setProperty('--c', r.color);
  card.innerHTML = `<button class="close" title="关闭">×</button>
    <div class="live">${cardStatus(r)}</div>
    <div class="mem">
      ${r.persona ? `<h4>性格</h4><div>${esc(r.persona)}</div>` : ''}
      ${relationsHtml(r.relations || [])}
      <h4>记得的事 <small id="mem-n"></small></h4>
      <ul class="mem-list" id="mem-list"></ul>
      <form class="mem-add" id="mem-add"><input id="mem-text" maxlength="200" placeholder="告诉${esc(r.name)}一件要记住的事" autocomplete="off"><button class="btn">记下</button></form>
    </div>
    <div class="acts">
      <button class="btn" data-i="wave">打招呼</button>
      <button class="btn" data-i="pat">摸摸头</button>
      <button class="btn" data-i="feed">投喂</button>
      <button class="btn" data-i="play">叫出门玩</button>
      <button class="btn primary" data-a="poke">去做点什么</button>
      <button class="btn" data-a="at">@${esc(r.name)}</button>
      <button class="btn" data-a="glb">导出 3D 形象 (.glb)</button>
    </div>`;
  card.classList.remove('hidden');
  card.querySelector('.close').onclick = closeCard;
  renderMemory(r.memory || []);
  $('mem-add').addEventListener('submit', async (e) => {
    e.preventDefault();
    const inp = $('mem-text'), text = inp.value.trim();
    if (!text) return;
    try { await api(`/api/residents/${encodeURIComponent(id)}/memory`, { method: 'POST', body: { text } }); inp.value = ''; await loadMemory(); } catch (err) { toast(err.message); }
  });
  card.querySelectorAll('[data-i]').forEach((b) => { b.onclick = async () => {
    try { toast((await api(`/api/residents/${encodeURIComponent(id)}/interact`, { method: 'POST', body: { action: b.dataset.i } })).message); } catch (err) { toast(err.message); }
  }; });
  card.querySelector('[data-a=poke]').onclick = async () => {
    const res = await api(`/api/residents/${encodeURIComponent(id)}/poke`, { method: 'POST' });
    toast(res.message);
  };
  card.querySelector('[data-a=at]').onclick = () => { closeCard(); $('panel-chat').classList.remove('min'); mention(r.name); };
  card.querySelector('[data-a=glb]').onclick = async () => {
    try { await exportGlb(r.avatar || {}, r.name, r.color); toast('已导出'); } catch (e) { toast('导出失败：' + e.message); }
  };
}

function closeCard() { S.cardId = null; $('card').classList.add('hidden'); }

function relationsHtml(rows) {
  if (!rows.length) return '<h4>和大家的关系</h4><div class="rel-none">还没怎么来往</div>';
  return `<h4>和大家的关系</h4><ul class="rel">${rows.map((x) => `<li>
    <span class="n">${esc(x.name)}</span><span class="b"><i style="width:${Math.min(100, x.score)}%"></i></span><em>${esc(x.label)}</em>
    ${x.note ? `<div class="w">${esc(x.note)}</div>` : ''}</li>`).join('')}</ul>`;
}

// ---------------------------------------------------------------- 留言
function panelOpen(id) { return !$(`panel-${id}`).classList.contains('hidden'); }

async function loadNotes() {
  const { items } = await api('/api/notes');
  const owner = S.home.owner || '我';
  const label = (id) => (id === 'owner' ? owner : nameOf(id));
  $('notes').innerHTML = items.length ? items.map((n) => {
    const fromMe = n.sender === 'owner';
    const state = fromMe ? (n.read_at ? '已读' : '还没看') : '';
    return `<div class="note ${fromMe ? 'me' : ''} ${!fromMe && !n.read_at ? 'new' : ''}" style="--c:${esc(colorOf(fromMe ? n.recipient : n.sender))}">
      <div class="who">${esc(label(n.sender))} → ${esc(label(n.recipient))}<span class="when">${mdhm(n.ts)}${state ? ` · ${state}` : ''}</span></div>
      <div class="t">${esc(n.text)}</div></div>`;
  }).join('') : '<div class="empty-chat">还没有留言</div>';
  if (items.some((n) => n.recipient === 'owner' && !n.read_at)) await api('/api/notes/read', { method: 'POST' });
}

export function notesChanged() { if (panelOpen('notes')) loadNotes().catch(() => {}); }

function renderNoteTargets() {
  const sel = $('note-to'), keep = sel.value;
  sel.innerHTML = [...S.residents.values()].map((r) => `<option value="${esc(r.id)}">${esc(r.name)}</option>`).join('');
  if (keep) sel.value = keep;
}

// ---------------------------------------------------------------- 日报
function dayShift(day, n) {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

async function loadWeekly() {
  const d = await api(`/api/weekly${S.dailyDay ? `?end=${S.dailyDay}` : ''}`);
  $('daily-day').textContent = `${d.start.slice(5)} 到 ${d.end.slice(5)}`;
  if (d.empty) { $('daily').innerHTML = '<div class="empty-chat" style="padding:40px 0">这一周没有记录</div>'; return; }
  $('daily').innerHTML = `<div class="lead">${esc(d.lead)}<div class="sky">来过 ${d.visits} 次 · 留言 ${d.notes} 条</div></div>
    ${d.residents.map((p) => `<div class="dr" style="--c:${esc(colorOf(p.id))}"><b>${esc(p.name)}</b>
      <span>做了 ${p.things} 件事${p.place ? `，常在${esc(p.place)}` : ''}${p.friend ? `，和${esc(p.friend)}待得最多` : ''}${p.chats ? `，说了 ${p.chats} 句话` : ''}，调用 ${p.calls} 次${p.goals.length ? `<br>${p.goals.map(esc).join('；')}` : ''}</span></div>`).join('')}
    ${d.parties.length ? `<h4>这周凑的局</h4>${d.parties.map((m) => `<div class="dm"><span class="when">${mdhm(m.ts)}</span>${esc(m.text)}</div>`).join('')}` : ''}
    <button class="btn" id="week-back">回到这一天</button>`;
  $('week-back').onclick = () => loadDaily(S.dailyDay).catch((e) => toast(e.message));
}

async function loadDaily(day) {
  const d = await api(`/api/daily${day ? `?day=${day}` : ''}`);
  S.dailyDay = d.day; S.dailyToday = d.today;
  $('daily-day').textContent = d.today ? `今天 ${d.day.slice(5)}` : d.day;
  $('daily-next').disabled = d.today;
  if (d.empty) { $('daily').innerHTML = '<div class="empty-chat" style="padding:40px 0">这一天没有记录</div>'; return; }
  $('daily').innerHTML = `
    <div class="lead">${esc(d.lead)}<div class="sky">${d.weather.map(esc).join(' ')}${d.visits ? ` · 来过 ${d.visits} 次` : ''}${d.notes ? ` · 留言 ${d.notes} 条` : ''}</div></div>
    ${d.residents.map((p) => `<div class="dr" style="--c:${esc(colorOf(p.id))}"><b>${esc(p.name)}</b>
      <span>做了 ${p.things} 件事${p.places.length ? `，常在${esc(p.places.join('、'))}` : ''}${p.with.length ? `，和${esc(p.with.join('、'))}待过` : ''}${p.chats ? `，说了 ${p.chats} 句话` : ''}</span></div>`).join('')}
    ${d.moments.length ? `<h4>这天的片段</h4>${d.moments.map((m) => `<div class="dm"><span class="when">${hhmm(m.ts)}</span>${esc(m.who)} ${esc(m.text)}${m.detail ? `<small>${esc(m.detail)}</small>` : ''}</div>`).join('')}` : ''}
    <button class="btn" id="daily-replay">回放这一天</button>`;
  $('daily-replay').onclick = () => S.replay.open(d.day).catch((e) => toast(e.message));
}

// ---------------------------------------------------------------- 用量
const tokens = (n) => (n >= 10000 ? `${(n / 10000).toFixed(1)} 万` : String(n));

async function loadUsage() {
  const box = $('usage');
  if (!box) return;
  const u = await api('/api/usage?days=7');
  box.innerHTML = u.residents.map((x) => `<div class="use" style="--c:${esc(x.color)}">
      <b>${esc(x.name)}</b><span>今天 ${x.today_calls}/${x.daily_calls} 次 · ${tokens(x.today_tokens)} token</span>
      <span class="b"><i style="width:${Math.min(100, (x.today_calls * 100) / Math.max(1, x.daily_calls))}%"></i></span>
      <small>近 ${u.days} 天 ${x.calls} 次，${tokens(x.input_tokens + x.output_tokens)} token${x.cost != null ? `，约 ${x.cost} ${esc(x.currency)}` : ''}${x.fails ? `，失败 ${x.fails}` : ''}</small></div>`).join('')
    + (u.budget.calls || u.budget.cost ? `<div class="hintline">全屋预算：今天 ${u.budget.used_calls}${u.budget.calls ? `/${u.budget.calls}` : ''} 次${u.budget.cost ? `，约 ${u.budget.used_cost}/${u.budget.cost}` : ''}${u.budget.state === 'out' ? '，用完了，只回你的话' : u.budget.state === 'low' ? '，快用完了，少写感想' : ''}</div>` : '')
    + `<div class="hintline">${u.saving ? '现在没人看页面，住户少调用一些模型。' : '有人在看页面，住户按平常的频率调用模型。'}</div>`;
}

// ---------------------------------------------------------------- 记忆管理
async function loadMemory() {
  if (!S.cardId) return;
  const { items } = await api(`/api/residents/${encodeURIComponent(S.cardId)}/memory`);
  renderMemory(items);
}

export function memoryChanged(id) {
  if (id !== S.cardId || $('mem-list')?.querySelector('input')) return;   // 正在改的时候先不刷
  loadMemory().catch(() => {});
}

function memoryItem(m) {
  const tag = m.merged ? '已整理' : MEM_KIND[m.kind] || '';
  return `<li class="${m.pinned ? 'pinned' : ''} ${m.merged ? 'merged' : ''}" data-id="${m.id}">
    <span class="t">${esc(m.text)}</span>${tag ? `<em>${esc(tag)}</em>` : ''}
    <span class="ops"><button data-m="pin" title="${m.pinned ? '取消置顶' : '置顶：一定会想起来'}">${m.pinned ? '★' : '☆'}</button><button data-m="edit" title="改">✎</button><button data-m="del" title="忘掉">×</button></span></li>`;
}

function renderMemory(items) {
  const list = $('mem-list');
  if (!list) return;
  $('mem-n').textContent = items.length ? `${items.length} 条` : '';
  list.innerHTML = items.length ? items.map(memoryItem).join('') : '<li class="none">还没记住什么</li>';
  list.querySelectorAll('li[data-id]').forEach((li) => {
    const mid = li.dataset.id, row = items.find((x) => String(x.id) === mid);
    const patch = async (body) => { try { await api(`/api/memory/${mid}`, { method: 'PATCH', body }); await loadMemory(); } catch (e) { toast(e.message); } };
    li.querySelector('[data-m=pin]').onclick = () => patch({ pinned: !row.pinned });
    li.querySelector('[data-m=del]').onclick = async () => {
      if (!confirm(`忘掉这条？\n${row.text}`)) return;
      try { await api(`/api/memory/${mid}`, { method: 'DELETE' }); await loadMemory(); } catch (e) { toast(e.message); }
    };
    li.querySelector('[data-m=edit]').onclick = () => {
      const inp = document.createElement('input');
      inp.value = row.text; inp.maxLength = 200;
      li.replaceChildren(inp); inp.focus();
      let done = false;
      const finish = async (save) => {
        if (done) return; done = true;
        const text = inp.value.trim();
        inp.remove();
        if (save && text && text !== row.text) await patch({ text }); else await loadMemory();
      };
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') finish(true); if (e.key === 'Escape') { e.stopPropagation(); finish(false); } });
      inp.addEventListener('blur', () => finish(true));
    };
  });
}

// ---------------------------------------------------------------- 设置
function renderSettings() {
  const el = $('settings');
  if (!el || !S.world) return;
  const h = S.home;
  const srcs = (h.sources || []).map((s) => `${esc(s.name)}：${s.items} 条${s.error ? `（${esc(s.error)}）` : ''}`).join('<br>') || '没有内容来源';
  el.innerHTML = `
    <section><h4>全屋</h4><div class="row">
      ${h.paused ? '<button class="btn primary" data-a="resume">恢复</button>' : '<button class="btn danger" data-a="pause">全屋暂停</button>'}
      <button class="btn" data-a="recheck">重新检查接入</button>
      <button class="btn" data-a="reload">重新读取配置</button>
      <button class="btn" data-a="gather">叫大家出门</button>
      <button class="btn" data-a="party">凑个局</button></div>
      <div class="kv">暂停后住户不调用模型，也不换地方。改了 home.yaml、房间模板或活动后点「重新读取配置」。</div></section>
    <section><h4>天气</h4><div class="row">
      <button class="btn" data-w="clear">放晴</button><button class="btn" data-w="cloudy">多云</button><button class="btn" data-w="rain">下雨</button>
      <button class="btn" data-w="auto" ${h.weather?.forced ? '' : 'disabled'}>跟随自然</button></div></section>
    <section><h4>调用用量</h4><div id="usage" class="kv">读取中…</div></section>
    <section><h4>显示</h4><div class="row">
      <button class="btn ${S.people.look === '3d' ? 'primary' : ''}" data-a="look3d">3D 小人</button>
      <button class="btn ${S.people.look === '2d' ? 'primary' : ''}" data-a="look2d">立绘</button>
      <button class="btn ${S.world.lowWalls ? 'primary' : ''}" data-a="walls">${S.world.lowWalls ? '内墙：矮' : '内墙：正常'}</button></div></section>
    <section id="prefs-slot"></section>
    <section><h4>住户接入</h4><div class="kv">${[...S.residents.values()].map((r) =>
      `<div><span class="dot ${esc(r.status)}"></span><b>${esc(r.name)}</b> <span>${esc(r.access_label)}</span>${r.status === 'offline' ? `<br><span>${esc(r.note || r.ready_info)}</span>` : ''}</div>`).join('')}</div></section>
    ${h.move_in ? `<section><h4>办入住</h4><form class="movein" id="movein">
      <input name="id" placeholder="id，比如 glm" autocomplete="off"><input name="name" placeholder="名字" autocomplete="off">
      <input name="model_label" placeholder="显示的模型名" autocomplete="off"><input name="color" type="color" value="#8aa0b8" aria-label="颜色">
      <input name="base_url" placeholder="接口地址 https://…" autocomplete="off"><input name="model" placeholder="模型名" autocomplete="off">
      <input name="api_key_env" placeholder="key 的环境变量名，如 GLM_API_KEY" autocomplete="off">
      <textarea name="persona" rows="2" placeholder="性格"></textarea>
      <div class="row"><button type="button" class="btn" data-m="check">试接</button><button type="submit" class="btn primary">入住</button></div></form>
      <div class="kv">key 只从运行小窝的机器的环境变量读。办好的住户存在数据库里，home.yaml 不变。</div></section>` : ''}
    <section><h4>内容来源</h4><div class="kv">${srcs}</div></section>
    <section><h4>关于</h4><div class="kv">时区 ${esc(h.tz || '')}${h.mock ? ' · 模拟住户：不调用模型' : ''}${h.fast ? ' · 加速' : ''}</div></section>`;
  S.prefsEl = S.prefsEl || prefsPanel();
  $('prefs-slot').replaceWith(S.prefsEl);
  const act = async (a) => {
    try {
      if (a === 'pause' || a === 'resume') setHome(await api('/api/pause', { method: 'POST', body: { paused: a === 'pause' } }));
      else if (a === 'recheck') { await api('/api/recheck', { method: 'POST' }); toast('正在重新检查'); }
      else if (a === 'reload') { const r = await api('/api/reload', { method: 'POST' }); toast(r.message || '已重新读取'); }
      else if (a === 'gather') toast((await api('/api/gather', { method: 'POST' })).message);
      else if (a === 'party') toast((await api('/api/party', { method: 'POST' })).message);
      else if (a === 'look3d' || a === 'look2d') { S.people.setLook(a === 'look3d' ? '3d' : '2d'); renderSettings(); }
      else if (a === 'walls') { S.world.lowWalls = !S.world.lowWalls; S.world.updateCutaway(); renderSettings(); }
    } catch (e) { toast(e.message); }
  };
  el.querySelectorAll('[data-a]').forEach((b) => b.addEventListener('click', () => act(b.dataset.a)));
  el.querySelectorAll('[data-w]').forEach((b) => b.addEventListener('click', async () => {
    try { toast((await api('/api/weather', { method: 'POST', body: { kind: b.dataset.w } })).message); } catch (e) { toast(e.message); }
  }));
  const form = $('movein');
  if (form) {
    const body = () => { const f = new FormData(form), g = (k) => String(f.get(k) || '').trim();
      return { id: g('id'), name: g('name'), model_label: g('model_label'), color: g('color'), persona: g('persona'),
        driver: { type: 'openai_api', base_url: g('base_url'), model: g('model'), api_key_env: g('api_key_env') } }; };
    form.querySelector('[data-m=check]').addEventListener('click', async () => {
      try { toast('试接中…'); toast((await api('/api/movein/check', { method: 'POST', body: body() })).message, 6000); } catch (e) { toast(e.message); }
    });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      try { toast((await api('/api/movein', { method: 'POST', body: body() })).message, 6000); } catch (err) { toast(err.message); }
    });
  }
  if (panelOpen('settings')) loadUsage().catch(() => {});
}

// ---------------------------------------------------------------- 外框
function bindChrome() {
  document.querySelectorAll('.rail [data-panel]').forEach((b) => b.addEventListener('click', () => {
    const id = b.dataset.panel;
    const was = b.classList.contains('on');
    document.querySelectorAll('.rail [data-panel]').forEach((x) => x.classList.remove('on'));
    document.querySelectorAll('.panel.side').forEach((p) => p.classList.add('hidden'));
    if (!was) {
      b.classList.add('on'); $('panel-' + id).classList.remove('hidden');
      if (id === 'settings') renderSettings();
      if (id === 'notes') { renderNoteTargets(); loadNotes().catch((e) => toast(e.message)); }
      if (id === 'daily') loadDaily().catch((e) => toast(e.message));
    }
  }));
  $('open-replay').addEventListener('click', () => {
    if (S.replay.active) S.replay.close(); else S.replay.open().catch((e) => toast(e.message));
  });
  $('daily-prev').addEventListener('click', () => loadDaily(dayShift(S.dailyDay, -1)).catch((e) => toast(e.message)));
  $('daily-next').addEventListener('click', () => { if (!S.dailyToday) loadDaily(dayShift(S.dailyDay, 1)).catch((e) => toast(e.message)); });
  $('daily-week').addEventListener('click', () => loadWeekly().catch((e) => toast(e.message)));
  $('note-add').addEventListener('submit', async (e) => {
    e.preventDefault();
    const inp = $('note-text'), text = inp.value.trim();
    if (!text) return;
    try { await api('/api/notes', { method: 'POST', body: { to: $('note-to').value, text } }); inp.value = ''; await loadNotes(); } catch (err) { toast(err.message); }
  });
  document.querySelectorAll('.panel.side [data-close]').forEach((b) => b.addEventListener('click', () => {
    b.closest('.panel').classList.add('hidden');
    document.querySelectorAll('.rail [data-panel]').forEach((x) => x.classList.remove('on'));
  }));
  $('toggle-look').addEventListener('click', () => { S.people.setLook(S.people.look === '3d' ? '2d' : '3d'); renderSettings(); toast(S.people.look === '3d' ? '3D 小人' : '立绘'); });
  $('toggle-sky').addEventListener('click', () => {
    const w = S.world;
    w.forceSky = w.forceSky == null ? (w.night > 0.5 ? 0 : 1) : null;
    w.night = -1;
    toast(w.forceSky == null ? '跟随小窝时间' : w.forceSky ? '预览：夜晚' : '预览：白天');
  });
  $('rot-left').addEventListener('click', () => S.world.rotate(-1));
  $('rot-right').addEventListener('click', () => S.world.rotate(1));
  $('view-all').addEventListener('click', () => S.world.viewAll());
  $('chat-min').addEventListener('click', () => $('panel-chat').classList.toggle('min'));
  $('say').addEventListener('submit', async (e) => {
    e.preventDefault();
    const inp = $('say-text');
    const text = inp.value.trim();
    if (!text) return;
    inp.value = '';
    try { await api('/api/chat', { method: 'POST', body: { text } }); } catch (err) { toast(err.message); inp.value = text; }
  });
  addEventListener('keydown', (e) => { if (e.key === 'Escape') closeCard(); });
  if (innerWidth < 760) {
    $('panel-feed').classList.add('hidden');
    document.querySelector('.rail [data-panel=feed]').classList.remove('on');
    $('panel-chat').classList.add('min');
  }
}
