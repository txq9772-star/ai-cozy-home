// 入口：拉数据、搭场景、接实时推送。
import { World } from './scene.js';
import { People } from './people.js';
import * as ui from './ui.js';
import { api, syncClock, homeHour, getToken, toast } from './util.js';
import { loadPrefs } from './prefs.js';

loadPrefs();

const world = new World(document.getElementById('stage'), document.getElementById('labels'));
const people = new People(world);
world.onPick = (id) => ui.openCard(id);
world.onRoomClick = (room) => world.focusRoom(room);
world.onTouch = (room, kind) => { api('/api/touch', { method: 'POST', body: { room, kind } }).catch(() => {}); };
window.__home = { world, people };     // 调试用

async function boot() {
  const [state, layout] = await Promise.all([api('/api/state'), api('/api/layout')]);
  syncClock(state.home);
  world.setHour(homeHour());
  world.setLayout(layout);
  people.setLayout(layout);
  state.residents.forEach((r) => people.update(r));
  world.setFarm(state.farm);
  ui.init({ world, people, state });
  ui.tickClock();
  window.__home.replay = ui.replay();
  setInterval(() => { ui.tickClock(); world.setHour(homeHour()); }, 1000);
  connect();
}

let retry = 0;
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const t = getToken();
  const ws = new WebSocket(`${proto}://${location.host}/ws${t ? `?token=${encodeURIComponent(t)}` : ''}`);
  ws.onopen = async () => {
    if (retry > 0 && !window.__home.replay?.active) {          // 断线重连：重新拉一次全量，补上断开期间的变化
      const state = await api('/api/state');
      syncClock(state.home);
      state.residents.forEach((r) => people.update(r));
      world.setFarm(state.farm);
      ui.resync(state);
    }
    retry = 0;
  };
  ws.onmessage = (ev) => {
    const { type, data } = JSON.parse(ev.data);
    switch (type) {
      case 'resident': people.update(data); ui.resident(data); break;
      case 'feed': ui.addFeed(data); break;
      case 'feed_update': ui.updateFeed(data); break;
      case 'chat': ui.addChat(data); if (data.sender !== 'owner') people.say(data.sender, data.text); break;
      case 'bubble': people.say(data.id, data.text); break;
      case 'act': people.act(data); break;
      case 'memory': ui.memoryChanged(data.resident); break;
      case 'pending': ui.setPending(data); break;
      case 'notes': ui.notesChanged(); break;
      case 'home': syncClock(data); ui.setHome(data); break;
      case 'farm': world.setFarm(data); ui.setFarm(data); break;
      case 'layout':
        world.setLayout(data); people.setLayout(data);
        api('/api/state').then((st) => { people.prune(new Set(st.residents.map((r) => r.id))); ui.resync(st); });
        break;
      default: break;
    }
  };
  ws.onclose = () => {
    retry++;
    setTimeout(connect, Math.min(15000, 1000 * retry));
  };
}

boot().catch((e) => { console.error(e); toast('打不开小窝：' + e.message, 10000); });
