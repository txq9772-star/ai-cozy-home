// 住户在场景里的样子和走动。3D 小人（avatar.js）和 2D 立绘两种外观，可以切换。
// 走路：按房间的「父房间」关系找路——出门到父房间，再到走廊，再进目标房间，最后走到位置上。
import * as THREE from 'three';
import { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { buildAvatar } from './avatar.js';
import { loadModelAvatar, modelUrl } from './model.js';
import { faceAngle, box } from './furniture.js';
import { GROUND_Y } from './scene.js';
import { Grid } from './path.js';
import { esc } from './util.js';

const SPEED = 2.4;
const seatPos = new THREE.Vector3();
const USES = { tv: 'tv', pc: 'desk', desk: 'desk', stove: 'counter', fridge: 'fridge', water: 'plant', piano: 'piano', easel: 'easel', chess: 'chess', pet: 'cat', lake_feed: 'lake' };
const LOW_MOODS = new Set(['sleepy', 'hungry', 'lonely', 'bored']);
const s_ = Math.sin;
const ANIM = {
  read: (t) => ({ lean: 0.12 + s_(t * 0.8) * 0.02 }),
  type: (t) => ({ y: Math.abs(s_(t * 10)) * 0.008, lean: 0.1 }),
  sip: (t) => ({ lean: t % 5 < 1.2 ? -0.12 : 0.02 }),
  sweep: (t) => ({ lean: 0.14 + s_(t * 4) * 0.07, roll: s_(t * 4) * 0.08 }),
  stir: (t) => ({ roll: s_(t * 5) * 0.05, lean: 0.1 }),
  wash: (t) => ({ roll: s_(t * 7) * 0.05, lean: 0.14 }),
  water: (t) => ({ lean: 0.2 + s_(t * 1.2) * 0.04 }),
  stretch: (t) => { const k = s_(t * 0.9); return { sy: 1 + k * 0.05, lean: k < 0 ? -k * 0.45 : 0, roll: k > 0 ? s_(t * 0.45) * 0.22 : 0 }; },
  paint: (t) => ({ roll: s_(t * 3) * 0.06, lean: 0.06 }),
  piano: (t) => ({ y: Math.abs(s_(t * 6)) * 0.01, roll: s_(t * 5) * 0.06, lean: 0.1 }),
  chess: (t) => ({ lean: 0.14 + s_(t * 0.6) * 0.06 }),
  game: (t) => ({ y: Math.abs(s_(t * 6)) * 0.012, roll: s_(t * 2.5) * 0.07 }),
  doze: (t) => ({ lean: 0.16 + s_(t * 0.7) * 0.06 }),
  dance: (t) => ({ y: Math.abs(s_(t * 5)) * 0.12, roll: s_(t * 2.5) * 0.18, spin: s_(t * 1.25) * 0.6 }),
  look: (t) => ({ spin: s_(t * 0.6) * 0.35 }),
  nod: (t) => ({ lean: Math.max(0, s_(t * 3)) * 0.1 }),
  wave: (t) => ({ roll: s_(t * 8) * 0.1, y: Math.abs(s_(t * 8)) * 0.03 }),
  clap: (t) => ({ y: Math.abs(s_(t * 9)) * 0.07 }),
  yawn: (t) => ({ sy: 1 + s_(Math.min(t % 3, 1.5) * 2.1) * 0.04, lean: -0.12 }),
  shake: (t) => ({ roll: s_(t * 14) * 0.05 }),
  feed: (t) => ({ lean: 0.18 + Math.abs(s_(t * 2.2)) * 0.1 }),
  fish: (t) => ({ lean: 0.04 + s_(t * 0.5) * 0.03 }),
  pet: (t) => ({ lean: 0.2 + s_(t * 3) * 0.06 }),
  tidy: (t) => ({ lean: 0.35 + s_(t * 2) * 0.2, roll: s_(t) * 0.06 }),
};
const D = Math.PI / 180;
const both = (u, f) => ({ r: [u, f], l: [u, f] });
const GESTURE = {
  read: () => both(55, 70),
  type: (t) => ({ r: [45, 55 + s_(t * 11) * 6], l: [45, 55 - s_(t * 11) * 6] }),
  sip: (t) => (t % 5 < 1.2 ? { r: [70, 112], l: [8, 8] } : { r: [42, 50], l: [8, 8] }),
  sweep: (t) => ({ r: [38 + s_(t * 4) * 18, 30], l: [28 + s_(t * 4) * 12, 42] }),
  stir: (t) => ({ r: [58 + s_(t * 5) * 9, 44], l: [18, 25] }),
  wash: (t) => ({ r: [50 + s_(t * 7) * 8, 42], l: [50 - s_(t * 7) * 8, 42] }),
  water: () => ({ r: [78, 12], l: [10, 10] }),
  stretch: (t) => (s_(t * 0.9) > 0 ? both(165, 8) : both(75, 8)),
  paint: (t) => ({ r: [82 + s_(t * 3) * 14, 28], l: [12, 18] }),
  piano: (t) => ({ r: [55, 38 + s_(t * 7) * 12], l: [55, 38 - s_(t * 8) * 12] }),
  chess: (t) => (t % 6 < 1.3 ? { r: [68, 32], l: [20, 62] } : { r: [32, 72], l: [20, 62] }),
  game: (t) => ({ r: [50, 72 + s_(t * 9) * 5], l: [50, 72 - s_(t * 8) * 5] }),
  dance: (t) => ({ r: [110 + s_(t * 3) * 42, 38], l: [110 - s_(t * 3) * 42, 38] }),
  wave: (t) => ({ r: [150 + s_(t * 9) * 14, 26], l: [6, 6] }),
  clap: (t) => both(68, 58 + s_(t * 10) * 18),
  yawn: (t) => (t % 3 < 1.5 ? { r: [122, 128], l: [6, 6] } : both(6, 6)),
  feed: (t) => ({ r: [60 + Math.abs(s_(t * 2.2)) * 30, 12], l: [34, 62] }),
  fish: (t) => both(42 + s_(t * 0.5) * 3, 30),
  pet: (t) => ({ r: [60 + s_(t * 3) * 12, 20], l: [10, 10] }),
  tidy: (t) => both(52 + s_(t * 2) * 15, 30),
};
const HOLDING = () => ({ r: [55, 66], l: [8, 8] });
const AVOID = 0.66;
const kiteHand = new THREE.Vector3();
const GATE_WAIT = 1.1;        // 离门口这么近才排队
const GATE_GIVEUP = 6000;
const STUCK_MS = 2500;        // 这么久没离下一个点更近，就当被挡住了     // 等这么久（毫秒）还过不去就直接走
const gate = (pt, id, dir) => Object.assign(pt, { gate: id, dir });
const pass = (pt, id) => Object.assign(pt, { pass: id });
const vecs = (pts) => pts.map((q) => Object.assign(new THREE.Vector3(q[0], 0, q[1]), q.gate ? { gate: q.gate, dir: q.dir } : {}, q.pass ? { pass: q.pass } : {}));
const LIE_OFFSET = 0.45;
const LIE_DROP = 0.12;
const handQ = new THREE.Quaternion(), bodyQ = new THREE.Quaternion();

function propMesh(kind) {
  const g = new THREE.Group();
  const add = (w, h, d, c, x = 0, y = 0, z = 0) => g.add(box(w, h, d, c, x, y, z));
  switch (kind) {
    case 'book': add(0.26, 0.04, 0.2, '#b9473c'); add(0.24, 0.05, 0.18, '#f2ead8'); break;
    case 'cup': add(0.09, 0.11, 0.09, '#f2eee4'); add(0.03, 0.06, 0.02, '#f2eee4', 0.06, 0.03, 0); break;
    case 'phone': add(0.08, 0.15, 0.015, '#23252f'); break;
    case 'broom': add(0.03, 1.2, 0.03, '#a57c52', 0.12, -0.85, 0); add(0.3, 0.18, 0.08, '#d9b969', 0.12, -1.0, 0); break;
    case 'can': add(0.18, 0.16, 0.14, '#5aa7c9'); add(0.03, 0.03, 0.22, '#5aa7c9', 0, 0.12, 0.14); break;
    case 'spatula': add(0.025, 0.04, 0.3, '#6e4a33'); add(0.1, 0.012, 0.1, '#9a9aa8', 0, 0, 0.2); break;
    case 'brush': add(0.02, 0.02, 0.26, '#a57c52'); add(0.04, 0.03, 0.06, '#d9574a', 0, 0, 0.15); break;
    case 'bag': add(0.2, 0.2, 0.12, '#d9b969'); break;
    case 'pad': add(0.22, 0.05, 0.12, '#3a3c48'); break;
    case 'kite': add(0.12, 0.12, 0.12, '#d9b969'); break;      // 手里是线轴，风筝本身在 kiteMesh 里，飘在人前上方
    case 'disc': { const d = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.15, 0.03, 16), new THREE.MeshStandardMaterial({ color: '#f29a4a' })); d.rotation.z = Math.PI / 2; g.add(d); break; }
    case 'rod': { g.add(box(0.025, 0.025, 1.9, '#6e4a33', 0, 0.35, 0.95)); g.children[0].rotation.x = -0.35; const line = box(0.006, 1.3, 0.006, '#e8e8e8', 0, -0.72, 1.82); g.add(line); break; }
    default: break;
  }
  return g;
}
function kiteMesh() {
  const g = new THREE.Group();
  const k = new THREE.Mesh(new THREE.OctahedronGeometry(0.45, 0), new THREE.MeshStandardMaterial({ color: '#e0574a', roughness: 0.7 }));
  k.scale.set(1, 1.3, 0.1); g.add(k);
  for (let i = 0; i < 4; i++) { const t = box(0.12, 0.06, 0.02, i % 2 ? '#f6c84c' : '#5aa7c9', 0, -0.7 - i * 0.22, 0); t.rotation.z = i % 2 ? 0.4 : -0.4; g.add(t); }
  const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), new THREE.LineBasicMaterial({ color: '#f4f4f4' }));
  line.frustumCulled = false;
  return { g, line };
}

const loader = new THREE.TextureLoader();
const texCache = new Map();
function tex(url, flip = false) {
  const k = url + (flip ? '#f' : '');
  if (!texCache.has(k)) {
    const t = loader.load(url);
    t.colorSpace = THREE.SRGBColorSpace;
    if (flip) { t.wrapS = THREE.RepeatWrapping; t.repeat.x = -1; t.offset.x = 1; }
    texCache.set(k, t);
  }
  return texCache.get(k);
}

export class People {
  constructor(world) {
    this.world = world;
    this.list = new Map();
    this.look = '3d';
    try { this.look = localStorage.getItem('home-look') || '3d'; } catch (e) { /* 忽略 */ }
    world.ticks.push((dt) => this.tick(dt));
  }

  setLayout(layout) {
    this.layout = layout;
    this.rooms = new Map(layout.rooms.map((r) => [r.id, r]));
    this.grids = new Map();
    for (const p of this.list.values()) {        // 布局变了：直接放到当前位置
      p.path = [];
      this.place(p, p.data, true);
    }
  }

  // ------------------------------------------------------------ 找路
  doorPts(room) {
    const d = room.door;
    if (!d) return null;
    const [x0, z0, x1, z1] = room.rect;
    const k = 0.8;
    let inside, door, outside;
    if (d.wall === 'n') { door = [d.at, z0]; inside = [d.at, z0 + k]; outside = [d.at, z0 - k]; }
    else if (d.wall === 's') { door = [d.at, z1]; inside = [d.at, z1 - k]; outside = [d.at, z1 + k]; }
    else if (d.wall === 'w') { door = [x0, d.at]; inside = [x0 + k, d.at]; outside = [x0 - k, d.at]; }
    else { door = [x1, d.at]; inside = [x1 - k, d.at]; outside = [x1 + k, d.at]; }
    if (room.parent === this.layout.hall && this.layout.style !== 'courtyard') outside[1] = this.layout.hall_z;
    return { inside, door, outside };
  }

  chain(roomId) {
    const out = [];
    let r = this.rooms.get(roomId);
    let guard = 0;
    while (r && r.id !== this.layout.hall && guard++ < 20) { out.push(r.id); r = this.rooms.get(r.parent); }
    out.push(this.layout.hall);
    return out;
  }

  // 户外场地里的一段路：绕开设施
  detour(roomId, from, to) {
    const room = this.rooms.get(roomId);
    if (!room || (room.kind === 'hall' && !room.parts)) return [to];
    return this.grid(roomId).find(from, to);
  }

  grid(roomId) {
    if (!this.grids.has(roomId)) this.grids.set(roomId, new Grid(this.rooms.get(roomId)));
    return this.grids.get(roomId);
  }

  route(fromRoom, toRoom, to, from) {
    if (fromRoom === toRoom) return this.detour(toRoom, from, to);
    const pts = this.doors(fromRoom, toRoom, to);
    const first = this.detour(fromRoom, from, pts[0]);
    const last = pts.length > 1 ? this.detour(toRoom, pts[pts.length - 2], to) : [to];
    return [...first, ...pts.slice(1, -1), ...last];
  }

  doors(fromRoom, toRoom, to) {
    const A = this.chain(fromRoom), B = this.chain(toRoom);
    const common = A.find((x) => B.includes(x)) ?? this.layout.hall;
    const pts = [];
    for (const id of A) {
      if (id === common) break;
      const d = this.doorPts(this.rooms.get(id));
      if (d) pts.push(gate(d.inside, id, 'out'), d.door, pass(d.outside, id));
    }
    const down = [];
    for (const id of B) {
      if (id === common) break;
      const d = this.doorPts(this.rooms.get(id));
      if (d) down.unshift([gate(d.outside, id, 'in'), d.door, pass(d.inside, id)]);
    }
    if (common === this.layout.hall && this.rooms.get(common)?.parts && pts.length && down.length) {
      pts.push(...this.detour(common, pts[pts.length - 1], down[0][0]).slice(0, -1));
    }
    for (const seg of down) pts.push(...seg);
    pts.push(to);
    return pts;
  }

  spotOf(data) {
    const room = this.rooms?.get(data.room);
    const s = room?.spots?.[data.spot];
    if (s && data.pose === 'lie') {          // 躺下时头放到枕头上；南排的床是反过来的
      const bed = this.world.nearestProp(room.id, 'bed', s.x, s.z);
      if (bed) {
        const flip = Math.abs(bed.obj.rotation.y) > 1;
        return { x: bed.x, z: bed.z + (flip ? LIE_OFFSET : -LIE_OFFSET), face: s.face, room: room.id, lieYaw: flip ? Math.PI : 0 };
      }
    }
    if (s) return { x: s.x, z: s.z, face: s.face, room: room.id, ride: s.ride, seat: s.seat ?? 0, y: s.y };
    if (room) return { x: (room.rect[0] + room.rect[2]) / 2, z: (room.rect[1] + room.rect[3]) / 2, face: 's', room: room.id };
    return { x: 0, z: 0, face: 's', room: data.room };
  }

  // ------------------------------------------------------------ 住户
  // 回放时把住户摆到那一刻；jump 是拖时间轴，直接到位
  replayTo(row, jump) {
    const p = this.list.get(row.id);
    if (!p) return;
    const { ts, ...state } = row;
    this.place(p, { ...p.data, anim: '', emote: '', prop: '', ...state, roam: false, typing: false }, jump);
    this.decorate(p);
    this.refreshRoomLights();
  }

  update(data) {
    let p = this.list.get(data.id);
    if (p && this.replaying) { p.data = { ...p.data, avatar: data.avatar }; return; }
    if (!p) { p = this.create(data); this.place(p, data, true); }
    else this.place(p, data, false);
    this.decorate(p);
    this.refreshRoomLights();
    if (data.bedroom) this.world.setDecor(data.bedroom, data.decor);
  }

  // 服务器发来的一个小动作：表情、转头、挪两步
  act(data) {
    const p = this.list.get(data.id);
    if (!p || this.replaying) return;
    if (data.anim) { p.actAnim = data.anim; p.actUntil = performance.now() + 3200; }
    if (data.emote) this.pop(p, data.emote);
    if (data.face) { p.faceId = data.face; p.faceUntil = performance.now() + 4000; }
    const pose = p.data.pose || 'stand';
    if (pose === 'stand' && !p.path.length && !p.rideId && !p.data.roam && !p.backPt && Math.random() < 0.4 && this.rooms) {
      const pt = this.grid(p.room).randomNear(p.pos.x, p.pos.z, 1.8);
      if (pt) {
        p.backPt = [p.pos.x, p.pos.z]; p.backAt = performance.now() + 5500;
        p.path = this.detour(p.room, [p.pos.x, p.pos.z], pt).map(([x, z]) => new THREE.Vector3(x, 0, z));
      }
    }
  }

  pop(p, text) {
    const el = p.popEl;
    el.textContent = text;
    el.classList.remove('go');
    void el.offsetWidth;
    el.classList.add('go');
  }

  create(data) {
    const root = new THREE.Group();
    const p = { id: data.id, data, root, path: [], pos: root.position, yaw: 0, room: data.room };
    p.fx = new THREE.Group(); root.add(p.fx);
    p.hold = new THREE.Group();
    p.gest = { r: [0, 0], l: [0, 0] };
    p.fxLean = 0; p.fxRoll = 0; p.fxY = 0; p.fxSy = 1; p.fxSpin = 0; p.t = Math.random() * 10; p.roamAt = 0;
    p.avatar = buildAvatar(data.avatar || {}, data.color);
    p.fx.add(p.avatar.root);
    p.avatar.hand.add(p.hold);
    p.sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: data.images?.front ? tex('/skin/' + data.images.front) : null, color: data.images?.front ? '#fff' : data.color, transparent: true, alphaTest: 0.1 }));
    p.sprite.center.set(0.5, 0);
    p.sprite.scale.set(1.25, 1.75, 1);
    root.add(p.sprite);
    const hit = new THREE.Mesh(new THREE.BoxGeometry(0.8, 1.7, 0.8), new THREE.MeshBasicMaterial({ visible: false }));
    hit.position.y = 0.85; hit.userData.pick = data.id;
    root.add(hit);
    this.world.pickables.push(hit);
    p.tagEl = document.createElement('div'); p.tagEl.className = 'name-tag';
    p.tagEl.addEventListener('click', () => this.world.onPick(data.id));
    p.tag = new CSS2DObject(p.tagEl); p.tag.position.y = 1.85; root.add(p.tag);
    p.bubbleEl = document.createElement('div'); p.bubbleEl.className = 'bubble hidden';
    p.bubble = new CSS2DObject(p.bubbleEl); p.bubble.position.y = 2.25; root.add(p.bubble);
    p.emoteEl = document.createElement('div'); p.emoteEl.className = 'emote hidden';
    p.emote = new CSS2DObject(p.emoteEl); root.add(p.emote);
    p.popEl = document.createElement('div'); p.popEl.className = 'pop';
    p.popObj = new CSS2DObject(p.popEl); root.add(p.popObj);
    this.world.scene.add(root);
    this.applyLook(p);
    this.list.set(data.id, p);
    if (data.model) this.useModel(p, data);
    return p;
  }

  // 模型加载完替换程序小人；失败或没配 model 时一直用程序小人
  async useModel(p, data) {
    try {
      const model = await loadModelAvatar(modelUrl(data.model), data.avatar || {}, data.color);
      if (this.list.get(p.id) !== p) return;
      p.fx.remove(p.avatar.root);
      p.avatar = model;
      p.fx.add(model.root);
      model.hand.add(p.hold);
      this.applyLook(p);
      this.decorate(p);
    } catch (e) {
      console.warn('模型加载失败，继续用程序小人', data.model, e);
    }
  }

  place(p, data, instant) {
    const prev = p.data;
    p.data = data;
    const s = this.spotOf(data);
    const target = [s.x, s.z];
    p.face = s.face;
    p.rideId = s.ride; p.seat = s.seat; p.lieYaw = s.lieYaw ?? 0; p.seatY = s.y || 0;
    if ((prev?.prop || '') !== (data.prop || '') || !p.propBuilt) {
      p.hold.clear();
      if (data.prop) p.hold.add(propMesh(data.prop));
      p.propBuilt = true;
      if (p.kite) { p.root.remove(p.kite.g, p.kite.line); p.kite = null; }
      if (data.prop === 'kite') { p.kite = kiteMesh(); p.root.add(p.kite.g, p.kite.line); }
    }
    const moved = !prev || prev.room !== data.room || prev.spot !== data.spot;
    if (instant || !this.rooms) {
      p.pos.set(target[0], 0, target[1]);
      p.path = []; p.room = data.room; p.backPt = null;
      this.leaveGate(p);
    } else if (moved) {
      this.leaveGate(p);
      p.path = vecs(this.route(p.room, data.room, target, [p.pos.x, p.pos.z]));
      p.room = data.room;
      p.backPt = null;
    }
  }

  decorate(p) {
    const d = p.data;
    const asleep = d.status === 'asleep', off = d.status === 'offline';
    let icon = '';
    if (asleep) icon = '<em>💤</em>';
    else if (off) icon = '<em>· 离线</em>';
    else if (LOW_MOODS.has(d.mood?.key)) icon = `<em>${d.mood.icon}</em>`;
    p.tagEl.style.setProperty('--c', d.color);
    p.tagEl.innerHTML = `${esc(d.name)}${icon}`;
    p.tagEl.classList.toggle('off', off);
    p.avatar.setAsleep(asleep);
    p.avatar.setDim(off);
    p.sprite.material.opacity = off ? 0.45 : 1;
    const emo = !asleep && !off ? d.emote || '' : '';
    if (p.emoteText !== emo) { p.emoteText = emo; p.emoteEl.textContent = emo; p.emoteEl.classList.toggle('hidden', !emo); }
    if (d.typing) this.showBubble(p, '· · ·', 0, true);
    else if (p.bubbleTyping) this.hideBubble(p);
  }

  showBubble(p, text, ms = 7000, typing = false) {
    p.bubbleEl.textContent = text;
    p.bubbleEl.classList.toggle('typing', typing);
    p.bubbleEl.classList.remove('hidden');
    p.bubbleTyping = typing;
    clearTimeout(p.bubbleTimer);
    if (ms) p.bubbleTimer = setTimeout(() => this.hideBubble(p), ms);
  }

  hideBubble(p) { p.bubbleEl.classList.add('hidden'); p.bubbleTyping = false; }

  say(id, text) {
    const p = this.list.get(id);
    if (p) this.showBubble(p, text.length > 60 ? text.slice(0, 60) + '…' : text);
  }

  prune(ids) {
    for (const [id, p] of this.list) {
      if (ids.has(id)) continue;
      this.world.scene.remove(p.root);
      p.tagEl.remove(); p.bubbleEl.remove(); p.emoteEl.remove(); p.popEl.remove();
      this.world.pickables = this.world.pickables.filter((h) => h.userData.pick !== id);
      this.list.delete(id);
    }
  }

  setLook(look) {
    this.look = look;
    try { localStorage.setItem('home-look', look); } catch (e) { /* 忽略 */ }
    for (const p of this.list.values()) this.applyLook(p);
  }

  applyLook(p) {
    const three = this.look === '3d' || !p.data.images?.front;
    p.avatar.root.visible = three;
    p.sprite.visible = !three;
  }

  refreshRoomLights() {
    const on = new Set();
    for (const p of this.list.values()) if (p.data.status === 'idle' || p.data.status === 'busy') on.add(p.data.room);
    this.world.lightRooms(on);
  }

  // 门外是下两级台阶到草地；栈桥这类木板台子上要站高一点
  groundY(x, z) {
    const h = this.layout?.house;
    const y = !h || z <= h[3] + 0.3 ? 0 : Math.max(GROUND_Y, ((z - h[3] - 0.3) / 0.6) * GROUND_Y);
    for (const d of this.decks()) if (Math.abs(x - d.x) < d.w / 2 && Math.abs(z - d.z) < d.len / 2) return y + d.top;
    return y;
  }

  decks() {
    const props = this.world.props || [];
    if (this.deckOf !== props.length) {
      this.deckOf = props.length;
      this.deckList = props.filter((q) => q.obj.userData.deck).map((q) => ({ x: q.x, z: q.z, ...q.obj.userData.deck }));
    }
    return this.deckList;
  }

  // ------------------------------------------------------------ 每帧
  tick(dt) {
    const cam = this.world.camera;
    const now = performance.now();
    this.useClock = (this.useClock || 0) + dt;
    if (this.useClock > 0.4 && this.rooms) { this.useClock = 0; this.updateUses(); }
    for (const p of this.list.values()) {
      p.t += dt;
      let walking = false;
      p.waiting = false;
      if (p.path.length) {
        const next = p.path[0];
        const dx = next.x - p.pos.x, dz = next.z - p.pos.z;
        const dist = Math.hypot(dx, dz);
        const step = SPEED * dt * (this.replaying ? 2.5 : 1);
        if (next.gate && p.gate !== next.gate && dist < GATE_WAIT && !this.replaying && !this.enterGate(p, next.gate, next.dir, now)) {
          p.waiting = true;                                  // 门口有人反方向过来：在门外等一下
          p.yawTarget = Math.atan2(dx, dz);
        } else {
          if (next !== p.stuckPt || dist < p.stuckD - 0.05) { p.stuckPt = next; p.stuckD = dist; p.stuckAt = now; }
          else if (now - p.stuckAt > STUCK_MS) { p.ghostUntil = now + 2000; p.stuckAt = now; }   // 被人挡着绕了半天：先不让了，直接走过去
          if (dist <= step || (p.path.length > 1 && dist < 0.2)) {
            p.pos.x = next.x; p.pos.z = next.z; p.path.shift();
            if (next.pass && next.pass === p.gate) this.leaveGate(p);
          } else { p.pos.x += (dx / dist) * step; p.pos.z += (dz / dist) * step; }
          if (dist > 0.001) p.yawTarget = Math.atan2(dx, dz);
          walking = p.path.length > 0;
        }
        if (!p.path.length) this.leaveGate(p);
      }
      const ride = !walking && !p.waiting && p.rideId ? this.world.rides.get(p.rideId) : null;
      if (walking) p.wasWalking = true;
      else if (p.wasWalking) { p.wasWalking = false; p.settleAt = now + 320; }     // 先转过身，再坐下
      let pose = walking ? 'walk' : (p.waiting || (p.settleAt > now && !p.rideId) ? 'stand' : (p.data.pose || 'stand'));
      if (ride) {
        ride.occ[p.seat] = true;
        ride.seats[p.seat]?.getWorldPosition(seatPos);
        p.pos.lerp(seatPos, 1 - Math.exp(-dt * 16));
        pose = ride.pose?.(p.seat) ?? pose;
        walking = pose === 'walk';
      } else {
        p.pos.y = this.groundY(p.pos.x, p.pos.z) + (!walking && !p.waiting && !p.path.length && pose === p.data.pose ? p.seatY : 0);
      }
      if (!p.path.length) {
        p.yawTarget = ride?.yaw?.(p.seat) ?? (pose === 'lie' ? p.lieYaw : faceAngle(p.face));
        const other = p.faceId && now < p.faceUntil ? this.list.get(p.faceId) : null;
        if (other && !ride && pose !== 'lie') p.yawTarget = Math.atan2(other.pos.x - p.pos.x, other.pos.z - p.pos.z);
      }
      this.freeWalk(p, now, ride, walking);
      this.bodyFx(p, now, dt, ride, walking, pose);
      let dy = (p.yawTarget ?? 0) - p.yaw;
      dy = Math.atan2(Math.sin(dy), Math.cos(dy));
      p.yaw += dy * Math.min(1, dt * 10);
      p.avatar.root.rotation.y = p.yaw + p.fxSpin;
      p.avatar.setWalking(walking);
      p.avatar.setPose(walking ? 'stand' : pose);
      p.avatar.update(dt);
      const lying = !walking && pose === 'lie';
      p.tag.position.set(0, lying ? 1.35 : (pose === 'sit' ? 2.0 : pose === 'sit_floor' ? 1.6 : 1.85), lying ? -0.1 : 0);
      p.bubble.position.set(0, p.tag.position.y + 0.4, p.tag.position.z);
      p.emote.position.set(0.72, p.tag.position.y + 0.02, p.tag.position.z);
      p.popObj.position.set(0, p.tag.position.y + 0.3, p.tag.position.z);
      const far = cam.position.distanceTo(p.pos) > 85;
      if (p.far !== far) { p.far = far; p.emoteEl.classList.toggle('far', far); p.tagEl.classList.toggle('far', far); }
      if (p.sprite.visible) this.spriteView(p, cam, walking, pose);
    }
    this.separate(now, dt);
  }

  // 门口一次只走一个方向：同方向的可以跟着过，反方向的在门外等；等太久就直接走，免得卡死
  enterGate(p, id, dir, now) {
    this.gates ||= new Map();
    let g = this.gates.get(id);
    if (g) for (const q of g.who) if (q.gate !== id || !q.path.length) g.who.delete(q);
    if (!g || !g.who.size || g.dir === dir || now - (p.waitFrom || now) > GATE_GIVEUP) {
      if (!g || !g.who.size) { g = { dir, who: new Set() }; this.gates.set(id, g); }
      g.who.add(p); p.gate = id; p.waitFrom = 0;
      return true;
    }
    p.waitFrom ||= now;
    return false;
  }

  leaveGate(p) {
    if (p.gate) this.gates?.get(p.gate)?.who.delete(p);
    p.gate = null; p.waitFrom = 0;
  }

  // 走路时别穿过别人，迎面碰上会打个招呼
  separate(now, dt) {
    if (this.replaying) return;
    const all = [...this.list.values()];
    const moving = (q) => q.path.length && !q.waiting;
    const arriving = (q) => q.path.length === 1 && Math.hypot(q.path[0].x - q.pos.x, q.path[0].z - q.pos.z) < 0.7;
    const heading = (q) => { const n = q.path[0], x = n.x - q.pos.x, z = n.z - q.pos.z, l = Math.hypot(x, z) || 1; return [x / l, z / l]; };
    for (const a of all) {
      if (!moving(a) || arriving(a) || now < (a.ghostUntil || 0)) continue;    // 快到座位了就别再被挤开
      for (const b of all) {
        if (a === b || b.rideId && !b.path.length) continue;
        const dx = a.pos.x - b.pos.x, dz = a.pos.z - b.pos.z, d = Math.hypot(dx, dz);
        if (d >= AVOID || d < 1e-4) continue;
        const both = moving(b);
        const k = ((AVOID - d) * (both ? 0.5 : 1)) / d;
        a.pos.x += dx * k; a.pos.z += dz * k;
        if (!both) continue;
        const [ax, az] = heading(a), [bx, bz] = heading(b);
        if (ax * bx + az * bz < -0.3) { a.pos.x += (-dz / d) * dt * 1.6; a.pos.z += (dx / d) * dt * 1.6; }   // 迎面碰上各往右让一点；同方向就跟在后面，不绕圈
        if (now > (a.nodAt || 0) && now > (b.nodAt || 0) && Math.random() < 0.25) {
          a.nodAt = b.nodAt = now + 45000;
          this.pop(a, '👋');
        }
      }
    }
  }

  // 边走边做的事：在屋里转悠；挪两步之后回到原位
  freeWalk(p, now, ride, walking) {
    if (this.replaying || ride || walking || p.path.length || !this.rooms) return;
    const d = p.data;
    if (p.backPt && now > p.backAt) {
      const home = p.backPt; p.backPt = null;
      p.path = this.detour(p.room, [p.pos.x, p.pos.z], home).map(([x, z]) => new THREE.Vector3(x, 0, z));
      return;
    }
    if (d.roam && (d.status === 'idle' || d.status === 'busy') && now > p.roamAt && p.room === d.room) {
      p.roamAt = now + 2500 + Math.random() * 5000;
      const pt = this.grid(p.room).randomNear(p.pos.x, p.pos.z, 7);
      if (pt) p.path = this.detour(p.room, [p.pos.x, p.pos.z], pt).map(([x, z]) => new THREE.Vector3(x, 0, z));
    }
  }

  bodyFx(p, now, dt, ride, walking, pose) {
    const d = p.data;
    const name = p.actUntil > now ? p.actAnim : d.anim;
    const fn = !ride && !walking && pose !== 'lie' && d.status !== 'asleep' && d.status !== 'offline' ? ANIM[name] : null;
    const v = fn ? fn(p.t) : {};
    const k = pose.startsWith('sit') ? 0.55 : 1;
    const q = Math.min(1, dt * 9);
    p.fxLean += ((v.lean || 0) * k - p.fxLean) * q;
    p.fxRoll += ((v.roll || 0) * k - p.fxRoll) * q;
    p.fxY += ((v.y || 0) - p.fxY) * q;
    p.fxSy += ((v.sy || 1) - p.fxSy) * q;
    p.fxSpin += ((v.spin || 0) - p.fxSpin) * q;
    const c = Math.cos(p.yaw), n = Math.sin(p.yaw);
    p.fx.rotation.set(p.fxLean * c + p.fxRoll * n, 0, -p.fxLean * n + p.fxRoll * c);
    p.fx.position.y = p.fxY - (pose === 'lie' && !walking ? LIE_DROP : 0);
    p.fx.scale.y = p.fxSy;
    const showing = !ride && pose !== 'lie' && p.avatar.root.visible && (!walking || d.roam);
    p.hold.visible = showing && d.status !== 'asleep';
    const gfn = fn ? (GESTURE[name] || (d.prop ? HOLDING : null)) : null;
    const g = gfn ? gfn(p.t) : null;
    const seat = pose.startsWith('sit') ? 0.75 : 1;
    for (const side of ['r', 'l']) {
      for (const i of [0, 1]) {
        const to = g && !walking ? g[side][i] * D * (i ? 1 : seat) : 0;
        p.gest[side][i] += (to - p.gest[side][i]) * q;
      }
    }
    const idle = Math.abs(p.gest.r[0]) + Math.abs(p.gest.r[1]) + Math.abs(p.gest.l[0]) + Math.abs(p.gest.l[1]) < 0.004;
    p.avatar.setGesture?.(idle ? null : p.gest);
    if (p.kite) this.flyKite(p, now, p.hold.visible);
    if (p.hold.visible && p.hold.children.length) {                   // 东西跟着手走，但保持正着拿
      p.avatar.root.updateWorldMatrix(true, true);
      p.avatar.hand.getWorldQuaternion(handQ);
      p.avatar.root.getWorldQuaternion(bodyQ);
      p.hold.quaternion.copy(handQ.invert().multiply(bodyQ));
    }
  }

  // 风筝飘在面朝的方向，线从手里拉过去
  flyKite(p, now, on) {
    const { g, line } = p.kite;
    g.visible = line.visible = on;
    if (!on) return;
    const t = now / 1000, f = [Math.sin(p.yaw), Math.cos(p.yaw)];
    g.position.set(f[0] * 3.2 + Math.sin(t * 0.7) * 0.5 * f[1], 4.2 + Math.sin(t * 1.3) * 0.25, f[1] * 3.2 - Math.sin(t * 0.7) * 0.5 * f[0]);
    g.rotation.set(0, p.yaw, Math.sin(t * 1.1) * 0.25);
    p.hold.getWorldPosition(kiteHand);
    p.root.worldToLocal(kiteHand);
    const a = line.geometry.attributes.position;
    a.setXYZ(0, kiteHand.x, kiteHand.y, kiteHand.z);
    a.setXYZ(1, g.position.x, g.position.y - 0.4, g.position.z);
    a.needsUpdate = true;
  }

  updateUses() {
    const want = new Map();
    for (const p of this.list.values()) {
      const d = p.data;
      if (p.path.length || d.status === 'offline') continue;
      const s = this.rooms.get(d.room)?.spots?.[d.spot];
      if (d.status === 'asleep') {
        const bed = s && !p.sprite.visible && this.world.nearestProp(d.room, 'bed', s.x, s.z);
        if (bed) want.set(bed, { x: p.pos.x, z: p.pos.z });
        continue;
      }
      for (const tag of s?.tags || []) {
        const type = USES[tag];
        const prop = type && this.world.nearestProp(d.room, type, s.x, s.z);
        if (prop) want.set(prop, { x: p.pos.x, z: p.pos.z });
      }
    }
    for (const prop of this.world.props) {
      if (!prop.obj.userData.setUse) continue;
      const u = want.get(prop), on = !!u;
      if (on !== prop.on || (on && prop.type !== 'bed')) { prop.on = on; prop.obj.userData.setUse(on, u); }
    }
  }

  spriteView(p, cam, walking, pose) {
    const imgs = p.data.images || {};
    const toCam = new THREE.Vector3().subVectors(cam.position, p.pos); toCam.y = 0; toCam.normalize();
    const f = new THREE.Vector3(Math.sin(p.yaw), 0, Math.cos(p.yaw));
    const right = new THREE.Vector3().crossVectors(cam.up, toCam).normalize().negate();
    const dot = f.dot(toCam);
    let url = imgs.front, flip = false;
    if (dot < -0.45 && imgs.back) url = imgs.back;
    else if (dot <= 0.45 && imgs.side) { url = imgs.side; flip = f.dot(right) < 0; }
    const m = p.sprite.material;
    const t = tex('/skin/' + url, flip);
    if (m.map !== t) { m.map = t; m.needsUpdate = true; }
    const lying = !walking && pose === 'lie';
    m.rotation = lying ? Math.PI / 2 : 0;
    const bob = walking ? Math.abs(Math.sin(performance.now() / 110)) * 0.05 : 0;
    p.sprite.position.set(0, lying ? 0.55 : (pose.startsWith('sit') ? 0.22 : 0) + bob, lying ? 0.7 : 0);
    p.sprite.center.set(0.5, lying ? 0.5 : 0);
  }
}
