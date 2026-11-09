// 小工具：接口请求、时间、转义
let token = '';
try { token = localStorage.getItem('home-token') || ''; } catch (e) { /* 隐私模式 */ }

export function getToken() { return token; }

export async function api(path, opts = {}) {
  const headers = { 'content-type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['x-home-token'] = token;
  const res = await fetch(path, { ...opts, headers, body: opts.body && typeof opts.body !== 'string' ? JSON.stringify(opts.body) : opts.body });
  if (res.status === 401) {
    const t = prompt('这个小窝设了访问口令，请输入：');
    if (t) {
      token = t.trim();
      try { localStorage.setItem('home-token', token); } catch (e) { /* 忽略 */ }
      return api(path, opts);
    }
    throw new Error('需要访问口令');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
  return data;
}

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// 小窝时间：服务器给 now 和时区偏移，本地按差值往前走
const clock = { skew: 0, offset: 0 };
export function syncClock(home) {
  clock.skew = home.now * 1000 - Date.now();
  clock.offset = home.utc_offset * 1000;
}
export function homeDate(ts) {             // 返回一个「按小窝时区读 UTC 字段」的 Date
  const ms = ts ? ts * 1000 : Date.now() + clock.skew;
  return new Date(ms + clock.offset);
}
const pad = (n) => String(n).padStart(2, '0');
export function hhmm(ts) { const d = homeDate(ts); return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; }
export function mdhm(ts) { const d = homeDate(ts); return `${d.getUTCMonth() + 1}月${d.getUTCDate()}日 ${hhmm(ts)}`; }
export function clockText() {
  const d = homeDate();
  let h = d.getUTCHours(); const ap = h < 12 ? 'AM' : 'PM'; h = h % 12 || 12;
  return `${pad(d.getUTCMonth() + 1)}/${pad(d.getUTCDate())}, ${pad(h)}:${pad(d.getUTCMinutes())} ${ap}`;
}
export function homeHour() { const d = homeDate(); return d.getUTCHours() + d.getUTCMinutes() / 60; }

let toastTimer = 0;
export function toast(text, ms = 2600) {
  const el = document.getElementById('toast');
  el.textContent = text;
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), ms);
}
