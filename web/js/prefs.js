// 显示偏好：各类文字的大小、要不要显示房间名称。存在这个浏览器里，电脑和手机可以不一样。
const KEY = 'home-prefs';
const ITEMS = [
  { id: 'room', label: '房间名称', min: 60, max: 200 },
  { id: 'name', label: '住户名字', min: 60, max: 200 },
  { id: 'bubble', label: '对话气泡', min: 70, max: 200 },
  { id: 'emote', label: '头顶表情', min: 50, max: 250 },
  { id: 'ui', label: '面板文字', min: 80, max: 150 },
];
const fresh = () => ({ room: 100, name: 100, bubble: 100, emote: 100, ui: 100, hideRooms: false });
let prefs = fresh();

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (e) { /* 存不了就只在这次打开时生效 */ }
}

function apply() {
  const root = document.documentElement.style;
  for (const it of ITEMS) root.setProperty(`--fs-${it.id}`, String(prefs[it.id] / 100));
  document.body.classList.toggle('hide-rooms', prefs.hideRooms);
}

export function loadPrefs() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || '{}');
    for (const it of ITEMS) {
      const v = Number(saved[it.id]);
      if (Number.isFinite(v)) prefs[it.id] = Math.min(it.max, Math.max(it.min, v));
    }
    prefs.hideRooms = !!saved.hideRooms;
  } catch (e) { /* 读不到就用默认 */ }
  apply();
}

// 设置面板里的这一块。只建一次，面板重画时挪过去，拖动滑块不会被打断
export function prefsPanel() {
  const el = document.createElement('section');
  el.id = 'prefs';
  const sync = () => {
    for (const it of ITEMS) {
      el.querySelector(`[data-p=${it.id}]`).value = prefs[it.id];
      el.querySelector(`[data-v=${it.id}]`).textContent = `${prefs[it.id]}%`;
    }
    el.querySelector('[data-hide]').checked = prefs.hideRooms;
  };
  el.innerHTML = `<h4>文字大小</h4>
    ${ITEMS.map((it) => `<label class="pref"><span>${it.label}</span>
      <input type="range" data-p="${it.id}" min="${it.min}" max="${it.max}" step="5" aria-label="${it.label}大小"><em data-v="${it.id}"></em></label>`).join('')}
    <label class="pref-check"><input type="checkbox" data-hide> 隐藏房间名称</label>
    <div class="row"><button type="button" class="btn" data-reset>恢复默认</button></div>`;
  el.querySelectorAll('[data-p]').forEach((inp) => inp.addEventListener('input', () => {
    prefs[inp.dataset.p] = Number(inp.value);
    apply(); save(); sync();
  }));
  el.querySelector('[data-hide]').addEventListener('change', (e) => { prefs.hideRooms = e.target.checked; apply(); save(); });
  el.querySelector('[data-reset]').addEventListener('click', () => { prefs = fresh(); apply(); save(); sync(); });
  sync();
  return el;
}
