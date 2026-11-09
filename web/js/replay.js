// 回放：拖时间轴看某一天谁在哪、在做什么。回放时场景不跟实时走，退出后恢复。
import { api, esc, hhmm, toast } from './util.js';

const SPEEDS = [60, 300, 900];
const $ = (id) => document.getElementById(id);

export class Replay {
  constructor(world, people, onExit) {
    Object.assign(this, { world, people, onExit, data: null, playing: false, speed: 300, t: 0 });
    world.ticks.push((dt) => this.tick(dt));
    $('rp-exit').addEventListener('click', () => this.close());
    $('rp-play').addEventListener('click', () => this.setPlaying(!this.playing));
    $('rp-prev').addEventListener('click', () => this.shift(-1));
    $('rp-next').addEventListener('click', () => this.shift(1));
    $('rp-speed').addEventListener('click', () => {
      this.speed = SPEEDS[(SPEEDS.indexOf(this.speed) + 1) % SPEEDS.length];
      this.renderSpeed();
    });
    $('rp-range').addEventListener('input', (e) => { this.setPlaying(false); this.seek(Number(e.target.value), true); });
  }

  get active() { return !!this.data; }

  today() { return new Date(Date.now() + this.world.homeOffset * 1000).toISOString().slice(0, 10); }

  async open(day) {
    const data = await api(`/api/replay${day ? `?day=${day}` : ''}`);
    if (!data.trace.length && !data.initial.length) { toast('这一天没有足迹'); if (!this.data) return; }
    this.data = data;
    this.last = new Map();
    this.fed = 0;
    this.people.replaying = true;
    document.body.classList.add('replaying');
    $('replay').classList.remove('hidden');
    $('rp-day').textContent = data.day;
    this.end = Math.min(data.end, Date.now() / 1000);
    $('rp-range').min = data.start; $('rp-range').max = this.end;
    const first = data.trace[0]?.ts ?? data.start;
    this.renderSpeed();
    this.seek(data.initial.length ? data.start : Math.max(data.start, first - 30), true);
    this.setPlaying(true);
  }

  shift(n) {
    const d = new Date(`${this.data.day}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + n);
    const day = d.toISOString().slice(0, 10);
    if (day > this.today()) { toast('还没到这一天'); return; }
    this.open(day).catch((e) => toast(e.message));
  }

  close() {
    this.data = null;
    this.setPlaying(false);
    this.people.replaying = false;
    this.world.hourOverride = null;
    this.world.weatherOverride = null;
    document.body.classList.remove('replaying');
    $('replay').classList.add('hidden');
    this.onExit();
  }

  setPlaying(on) {
    this.playing = on;
    $('rp-play').textContent = on ? '暂停' : '播放';
  }

  renderSpeed() { $('rp-speed').textContent = `${this.speed / 60} 分钟/秒`; }

  tick(dt) {
    if (!this.data || !this.playing) return;
    const t = this.t + dt * this.speed;
    if (t >= this.end) { this.seek(this.end, false); this.setPlaying(false); return; }
    this.seek(t, false);
  }

  rowAt(id, t) {
    const list = this.byId.get(id) || [];
    let found = null;
    for (const row of list) { if (row.ts > t) break; found = row; }
    return found;
  }

  seek(t, jump) {
    const d = this.data;
    if (jump || !this.byId || this.byIdDay !== d) {
      this.byIdDay = d;
      this.byId = new Map();
      for (const row of [...d.initial, ...d.trace]) {
        if (!this.byId.has(row.id)) this.byId.set(row.id, []);
        this.byId.get(row.id).push(row);
      }
    }
    this.t = t;
    $('rp-range').value = t;
    $('rp-time').textContent = hhmm(t);
    const secs = t - d.start;
    this.world.hourOverride = (secs / 3600) % 24;
    this.world.weatherOverride = d.weather[Math.min(d.weather.length - 1, Math.floor(secs / 3600 / d.block_hours))];
    this.world.setHour(this.world.hourOverride);
    this.world.setWeather(this.world.weatherOverride);
    for (const id of this.byId.keys()) {
      const row = this.rowAt(id, t);
      if (row && (jump || this.last.get(id) !== row)) {
        this.last.set(id, row);
        this.people.replayTo(row, jump);
      }
    }
    this.caption(t, jump);
  }

  caption(t, jump) {
    const f = this.data.feed;
    if (jump) { this.fed = 0; while (this.fed < f.length && f[this.fed].ts <= t) this.fed++; }
    while (this.fed < f.length && f[this.fed].ts <= t) {
      const row = f[this.fed++];
      if (row.resident) this.people.say(row.resident, row.text);
    }
    const row = this.fed ? f[this.fed - 1] : null;
    const name = row?.resident ? (this.people.list.get(row.resident)?.data.name || '') : '';
    $('rp-caption').innerHTML = row ? `<b>${esc(hhmm(row.ts))}</b> ${esc(name)} ${esc(row.text)}` : '这时候还没发生什么';
  }
}
