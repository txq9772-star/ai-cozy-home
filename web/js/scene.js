// 场景：小岛、房子（地板、墙、门窗、家具、房间名牌）、灯光和昼夜、相机。
// 房子完全由 /api/layout 的数据画出来，前端不认识具体房间。
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { buildFurniture, box, mat } from './furniture.js';

const ROOM_ICON = { bed: '🛏', books: '📚', pot: '🍳', sofa: '🛋', game: '🎮', box: '📦', park: '🎠', lake: '🦆', tree: '🌳' };
export const GROUND_Y = -0.5;      // 屋外草地的高度（屋里地板是 0）
const FLOOR = { wood: '#c9a37a', wood2: '#b2885f', tile: '#d3cfdc', carpet: '#bcb3cc', concrete: '#a9a8b2', grass: '#83ad62' };
const WALL = '#dcd8e8', WALL_TOP = '#8d88a8', WALL_OUT = '#c3bdd8';
const EXT_H = 2.5, INT_H = 2.0, LOW_H = 0.35;

let dotTex = null;
function dot() {
  if (dotTex) return dotTex;
  const c = document.createElement('canvas'); c.width = c.height = 32;
  const x = c.getContext('2d');
  const g = x.createRadialGradient(16, 16, 0, 16, 16, 16);
  g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.35, 'rgba(255,255,255,.8)'); g.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = g; x.fillRect(0, 0, 32, 32);
  dotTex = new THREE.CanvasTexture(c);
  return dotTex;
}

function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}
const lerp = (a, b, t) => a + (b - a) * t;
const ease = (t) => t * t * (3 - 2 * t);

export class World {
  constructor(stage, labels) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    stage.appendChild(this.renderer.domElement);
    this.css = new CSS2DRenderer();
    labels.appendChild(this.css.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(30, 1, 2, 700);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    Object.assign(this.controls, { enableDamping: true, dampingFactor: 0.08, minPolarAngle: 0.3, maxPolarAngle: 1.22,
      minDistance: 8, maxDistance: 280, screenSpacePanning: false, zoomToCursor: true });
    this.controls.addEventListener('change', () => this.updateCutaway());

    this.hemi = new THREE.HemisphereLight('#dbe8ff', '#5d6b4a', 1.2);
    this.sun = new THREE.DirectionalLight('#ffffff', 2);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    this.sun.shadow.bias = -0.0004;
    this.sun.shadow.normalBias = 0.04;
    this.scene.add(this.hemi, this.sun, this.sun.target);

    this.house = new THREE.Group();
    this.scene.add(this.house);
    this.env = new THREE.Group();
    this.scene.add(this.env);
    this.ticks = [(dt) => { for (const r of this.rides.values()) r.update(dt); }, (dt) => { for (const t of this.tickers) t(dt); }];
    this.rides = new Map();
    this.tickers = [];
    this.props = [];
    this.touchables = [];
    this.decor = new Map();
    this.onTouch = () => {};
    this.pickables = [];
    this.walls = [];
    this.windows = [];
    this.roomLights = new Map();
    this.lamps = [];
    this.screens = [];
    this.lowWalls = false;
    this.night = 1;
    this.anim = null;
    this.timer = new THREE.Timer();
    this.onRoomClick = () => {};
    this.onPick = () => {};
    this.overcast = 0; this.overcastTo = 0;
    this.homeOffset = 0;
    this.makeSky();
    this.makeRain();
    this.resize();
    addEventListener('resize', () => this.resize());
    this.bindPick();
    this.renderer.setAnimationLoop(() => this.frame());
  }

  resize() {
    const w = innerWidth, h = innerHeight;
    this.renderer.setSize(w, h);
    this.css.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.fov = w < 760 ? 42 : 30;
    this.camera.updateProjectionMatrix();
  }

  frame() {
    this.timer.update();
    const dt = Math.min(this.timer.getDelta(), 0.1);
    if (this.anim) this.anim(dt);
    this.controls.update();
    for (const fn of this.ticks) fn(dt);
    this.renderer.render(this.scene, this.camera);
    this.css.render(this.scene, this.camera);
  }

  // ------------------------------------------------------------ 天空、星星、萤火
  makeSky() {
    const n = 500, pos = new Float32Array(n * 3), r = rng(7);
    for (let i = 0; i < n; i++) {
      const th = r() * Math.PI * 2, ph = r() * 1.2, R = 260;
      pos.set([Math.cos(th) * Math.sin(ph) * R, Math.cos(ph) * R * 0.8 + 20, Math.sin(th) * Math.sin(ph) * R], i * 3);
    }
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    this.stars = new THREE.Points(g, new THREE.PointsMaterial({ color: '#ffffff', size: 1.6, sizeAttenuation: true, transparent: true, map: dot(), depthWrite: false }));
    this.scene.add(this.stars);

    this.sea = new THREE.Mesh(new THREE.CircleGeometry(520, 64), new THREE.MeshStandardMaterial({ color: '#6fa8d6', roughness: 0.55 }));
    this.sea.rotation.x = -Math.PI / 2; this.sea.position.y = -3.2;
    this.scene.add(this.sea);

    // 云只放在岛外一圈，俯视时不挡房子
    this.cloudMat = new THREE.MeshStandardMaterial({ color: '#ffffff', roughness: 1, transparent: true, opacity: 0.92 });
    this.clouds = new THREE.Group();
    for (let i = 0; i < 12; i++) {
      const c = new THREE.Group(), th = (i / 12) * Math.PI * 2 + r() * 0.3, R2 = 95 + r() * 90;
      for (let j = 0; j < 4; j++) {
        const s = new THREE.Mesh(new THREE.IcosahedronGeometry(5 + r() * 4, 1), this.cloudMat);
        s.position.set((j - 1.5) * 6, r() * 2, r() * 5); s.scale.y = 0.55; c.add(s);
      }
      c.position.set(Math.cos(th) * R2, 10 + r() * 14, Math.sin(th) * R2);
      this.clouds.add(c);
    }
    this.scene.add(this.clouds);
    this.ticks.push((dt) => { this.clouds.rotation.y += dt * 0.006; });
  }

  // ------------------------------------------------------------ 天气和节日
  makeRain() {
    const n = 1400, r = rng(23);
    this.drops = new Float32Array(n * 6);
    this.dropSpeed = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const x = (r() - 0.5) * 130, y = r() * 40 - 3, z = (r() - 0.5) * 130;
      this.drops.set([x, y, z, x + 0.05, y + 0.9, z], i * 6);
      this.dropSpeed[i] = 26 + r() * 12;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(this.drops, 3));
    this.rain = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: '#dfe9f7', transparent: true, opacity: 0.55, depthWrite: false }));
    this.rain.visible = false; this.rain.frustumCulled = false;
    this.scene.add(this.rain);
    this.ticks.push((dt) => this.stepWeather(dt));
  }

  setWeather(kind) {
    this.weatherKind = kind;
    const shown = this.weatherOverride ?? kind;
    this.overcastTo = shown === 'rain' ? 1 : shown === 'cloudy' ? 0.42 : 0;
    this.rain.visible = shown === 'rain';
  }

  stepWeather(dt) {
    if (Math.abs(this.overcast - this.overcastTo) > 0.004) {
      this.overcast += Math.sign(this.overcastTo - this.overcast) * Math.min(dt * 0.5, Math.abs(this.overcastTo - this.overcast));
      this.applySky();
    }
    if (!this.rain.visible) return;
    const p = this.drops;
    for (let i = 0; i < this.dropSpeed.length; i++) {
      const fall = this.dropSpeed[i] * dt, k = i * 6;
      p[k + 1] -= fall; p[k + 4] -= fall;
      if (p[k + 1] < -3) { p[k + 1] += 42; p[k + 4] += 42; }
    }
    this.rain.geometry.attributes.position.needsUpdate = true;
  }

  setFestival(name) {
    if (name === this.festival) return;
    this.festival = name;
    this.buildFestival();
  }

  // 门口拉一串灯笼，只在节日那天有
  buildFestival() {
    if (this.bunting) { this.env.remove(this.bunting); this.bunting = null; }
    const ent = this.layout?.rooms.find((x) => x.entrance);
    if (!this.festival || !ent) return;
    const g = new THREE.Group();
    const cx = ent.entrance.at, z = ent.rect[3] + 1.25, H = 3.1, W = 1.45;
    for (const s of [-1, 1]) g.add(box(0.1, H - GROUND_Y, 0.1, '#7a5238', cx + s * W, GROUND_Y, z));
    g.add(box(W * 2 + 0.1, 0.07, 0.07, '#7a5238', cx, H, z));
    const cols = ['#d9483b', '#f0b13c', '#d9483b', '#4fa56b', '#d9483b'];
    cols.forEach((c, i) => {
      const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.19, 12, 10), mat(c, { emissive: c, emissiveIntensity: 0.55, flatShading: false }));
      lamp.scale.y = 0.85;
      lamp.position.set(cx - W * 0.8 + (W * 1.6 * i) / (cols.length - 1), H - 0.32, z);
      g.add(lamp, box(0.02, 0.2, 0.02, '#c9b28a', lamp.position.x, H - 0.17, z));
    });
    this.bunting = g;
    this.env.add(g);
  }

  // 草地贴图：只有亮度变化，颜色由 material.color 决定（昼夜渐变）
  grassMaterial(w, d) {
    const c = document.createElement('canvas'); c.width = c.height = 256;
    const x = c.getContext('2d'), r = rng(11);
    x.fillStyle = '#d8d8d8'; x.fillRect(0, 0, 256, 256);
    for (let i = 0; i < 2400; i++) {
      const v = 170 + Math.floor(r() * 85);
      x.fillStyle = `rgb(${v},${v},${v})`;
      x.fillRect(r() * 256, r() * 256, 2 + r() * 5, 2 + r() * 5);
    }
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(w / 9, d / 9);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    return new THREE.MeshStandardMaterial({ color: '#6f9a4f', roughness: 0.95, map: t });
  }

  // ------------------------------------------------------------ 房子
  setLayout(layout) {
    this.layout = layout;
    this.rooms = new Map(layout.rooms.map((r) => [r.id, r]));
    for (const grp of [this.house, this.env]) {
      grp.traverse((o) => { if (o.isCSS2DObject) o.element.remove(); });
      grp.clear();
    }
    this.walls = []; this.windows = []; this.lamps = []; this.screens = []; this.pools = []; this.roomLights.clear(); this.rides.clear();
    this.tickers = []; this.props = []; this.touchables = []; this.decor.clear();
    const [x0, z0, x1, z1] = layout.house;
    this.center = new THREE.Vector3((x0 + x1) / 2, 0, (z0 + z1) / 2);
    this.size = { w: x1 - x0, d: z1 - z0 };
    const [ix0, iz0, ix1, iz1] = layout.island;
    this.islandCenter = new THREE.Vector3((ix0 + ix1) / 2, 0, (iz0 + iz1) / 2);
    this.islandSize = { w: ix1 - ix0, d: iz1 - iz0 };
    this.buildIsland(layout);
    // 房基一直埋到草地下面，不留缝
    this.house.add(box(this.size.w + 0.6, 0.56, this.size.d + 0.6, '#8a86a3', this.center.x, -0.62, this.center.z));
    for (const r of layout.rooms) this.buildRoom(r);
    this.buildWalls(layout);
    const S = Math.max(this.islandSize.w, this.islandSize.d) / 2 + 6;
    Object.assign(this.sun.shadow.camera, { left: -S, right: S, top: S, bottom: -S, near: 1, far: 220 });
    this.sun.shadow.camera.updateProjectionMatrix();
    this.sun.position.set(this.islandCenter.x + 30, 50, this.islandCenter.z + 22);
    this.sun.target.position.copy(this.islandCenter);
    if (!this.placed) { this.viewAll(true); this.placed = true; }
    this.buildFestival();
    this.applySky();
    this.updateCutaway();
  }

  buildIsland(layout) {
    const [ix0, iz0, ix1, iz1] = layout.island;
    const w = ix1 - ix0, d = iz1 - iz0, cx = (ix0 + ix1) / 2, cz = (iz0 + iz1) / 2;
    this.grass = this.grassMaterial(w, d);
    // 泥土顶面比草皮底面还低一点：两个面重合就是白天地面闪烁的原因
    this.env.add(box(w, 1.4, d, '#5b4433', cx, -2.1, cz));
    const top = box(w + 0.02, 0.16, d + 0.02, this.grass, cx, GROUND_Y - 0.16, cz);
    top.castShadow = false; this.env.add(top);
    const [hx0, hz0, hx1, hz1] = layout.house;
    const r = rng(layout.rooms.length * 31 + Math.round(w));
    const yards = layout.rooms.filter((x) => x.kind === 'outdoor');
    const inHouse = (x, z) => (x > hx0 - 2.2 && x < hx1 + 2.2 && z > hz0 - 2.2 && z < hz1 + 2.2)
      || yards.some((y) => x > y.rect[0] - 1.6 && x < y.rect[2] + 1.6 && z > y.rect[1] - 1.6 && z < y.rect[3] + 1.6);
    const entrance = layout.rooms.find((x) => x.entrance);
    const ent = entrance ? { x: entrance.entrance.at, z: entrance.rect[3] } : null;
    const nearPath = (x, z) => ent && Math.abs(x - ent.x) < 2 && z > ent.z;
    let placed = 0, tries = 0;
    while (placed < 22 && tries++ < 400) {
      const x = lerp(ix0 + 1.2, ix1 - 1.2, r()), z = lerp(iz0 + 1.2, iz1 - 1.2, r());
      if (inHouse(x, z) || nearPath(x, z)) continue;
      const kind = ['pine', 'round', 'autumn', 'round', 'pine'][Math.floor(r() * 5)];
      this.env.add(this.tree(x, z, kind, 0.8 + r() * 0.6));
      placed++;
    }
    for (let i = 0; i < 7; i++) {
      const x = lerp(ix0 + 0.8, ix1 - 0.8, r()), z = lerp(iz0 + 0.8, iz1 - 0.8, r());
      if (inHouse(x, z)) continue;
      const rock = new THREE.Mesh(new THREE.DodecahedronGeometry(0.5 + r() * 0.4, 0), mat('#6f7280'));
      rock.position.set(x, -0.5, z); rock.scale.y = 0.6; rock.rotation.y = r() * 3; rock.castShadow = true;
      this.env.add(rock);
    }
    if (ent) {
      // 门口两级台阶，再接一条踏脚石小路
      this.env.add(box(1.9, 0.3, 0.3, '#b9b5c4', ent.x, GROUND_Y, ent.z + 0.45));
      this.env.add(box(1.9, 0.15, 0.3, '#c7c3d0', ent.x, GROUND_Y, ent.z + 0.75));
      for (let i = 0; i < 5; i++) {
        const s = box(0.9, 0.05, 0.55, '#c7c3d0', ent.x, GROUND_Y, ent.z + 1.4 + i * 0.95);
        s.castShadow = false; this.env.add(s);
      }
    }
    // 萤火
    const n = 40, pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) pos.set([lerp(ix0, ix1, r()), 0.3 + r() * 3, lerp(iz0, iz1, r())], i * 3);
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    this.flies = new THREE.Points(g, new THREE.PointsMaterial({ color: '#ffd77a', size: 0.22, transparent: true, opacity: 0.8, map: dot(), depthWrite: false }));
    this.env.add(this.flies);
  }

  tree(x, z, kind, s) {
    const g = new THREE.Group();
    g.add(box(0.28 * s, 1.4 * s, 0.28 * s, '#5a3d2b', 0, 0, 0));
    if (kind === 'pine') {
      for (let i = 0; i < 3; i++) {
        const c = new THREE.Mesh(new THREE.ConeGeometry((1.5 - i * 0.35) * s, 1.5 * s, 7), mat('#2f5a3a'));
        c.position.y = (1.4 + i * 0.8) * s; c.castShadow = true; g.add(c);
      }
    } else {
      const c = new THREE.Mesh(new THREE.IcosahedronGeometry(1.35 * s, 0), mat(kind === 'autumn' ? '#b5632f' : '#3f6e3c'));
      c.position.y = 2.3 * s; c.castShadow = true; g.add(c);
    }
    g.position.set(x, -0.6, z);
    return g;
  }

  buildRoom(r) {
    const [x0, z0, x1, z1] = r.rect;
    const outdoor = r.kind === 'outdoor';
    if (!outdoor) {
      for (const [a0, b0, a1, b1] of r.parts || [r.rect]) {
        const floor = box(a1 - a0 - 0.02, 0.06, b1 - b0 - 0.02, FLOOR[r.floor] || FLOOR.wood, (a0 + a1) / 2, -0.06, (b0 + b1) / 2);
        floor.castShadow = false;
        this.house.add(floor);
      }
    }
    for (const f of r.furniture || []) {
      const obj = buildFurniture(f);
      if (outdoor) obj.position.y = GROUND_Y;
      this.house.add(obj);
      obj.traverse((o) => {
        if (o.userData.glow) this.lamps.push(o);
        if (o.userData.screen) this.screens.push(o.userData.screen);
      });
      if (f.ride && obj.userData.ride) this.rides.set(f.ride, obj.userData.ride);
      this.props.push({ room: r.id, type: f.type, x: f.x, z: f.z, obj, on: false });
      if (obj.userData.tick) this.tickers.push(obj.userData.tick);
      if (obj.userData.touchKind) {
        obj.traverse((o) => { if (o.isMesh) o.userData.touchOf = { room: r.id, obj }; });
        this.touchables.push(obj);
      }
      if (f.type === 'lamp_post') this.lightPool(f.x, f.z);
    }
    if (r.kind !== 'hall' && r.kind !== 'court' && !outdoor) {
      const light = new THREE.PointLight('#ffcf8a', 0, Math.max(x1 - x0, z1 - z0) * 1.2, 1.6);
      light.position.set((x0 + x1) / 2, 2.3, (z0 + z1) / 2);
      this.house.add(light);
      this.roomLights.set(r.id, { light, on: true });
    }
    if (r.label) {
      const el = document.createElement('div');
      el.className = 'room-tag';
      el.innerHTML = `<i>${ROOM_ICON[r.icon] || '·'}</i>${r.name}`;
      el.addEventListener('click', () => this.onRoomClick(r));
      const tag = new CSS2DObject(el);
      tag.position.set(r.label[0], (outdoor ? GROUND_Y : 0) + 0.25, r.label[1]);
      this.house.add(tag);
    }
  }

  nearestProp(room, type, x, z) {
    let best = null, bd = Infinity;
    for (const p of this.props) {
      if (p.room !== room || p.type !== type) continue;
      const d = (p.x - x) ** 2 + (p.z - z) ** 2;
      if (d < bd) { bd = d; best = p; }
    }
    return best;
  }

  // 住户添的小东西，摆在卧室靠墙的空处
  setDecor(roomId, items) {
    const r = this.rooms?.get(roomId);
    if (!r) return;
    const key = (items || []).join(',');
    const old = this.decor.get(roomId);
    if (old?.key === key) return;
    if (old) this.house.remove(old.group);
    const [x0, z0, x1, z1] = r.rect;
    const fz = (z) => (r.flip ? z0 + z1 - z : z);
    const slots = [[x1 - 0.55, fz(z1 - 0.55)], [x0 + 0.55, fz(z1 - 0.6)], [x0 + 1.55, fz(z1 - 0.6)], [x0 + 0.6, fz(z1 - 1.7)], [x1 - 0.6, fz(z0 + 2.4)], [x0 + 0.6, fz(z0 + 3.5)]];
    const group = new THREE.Group();
    (items || []).slice(0, slots.length).forEach((type, i) => group.add(buildFurniture({ type, x: slots[i][0], z: slots[i][1] })));
    this.house.add(group);
    this.decor.set(roomId, { key, group });
  }

  // 路灯照在地上的一圈光。用贴图假装，比真灯省得多，手机也跑得动
  lightPool(x, z) {
    const m = new THREE.Mesh(new THREE.CircleGeometry(4.2, 28),
      new THREE.MeshBasicMaterial({ color: '#ffcf8a', map: dot(), transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
    m.rotation.x = -Math.PI / 2;
    m.position.set(x, GROUND_Y + 0.07, z);
    this.house.add(m);
    this.pools.push(m);
  }

  // 墙：把所有房间的边合并成线段，再在门的位置开口
  buildWalls(layout) {
    const [hx0, hz0, hx1, hz1] = layout.house;
    const dw = layout.door_width || 1.6;
    const lines = new Map();     // key -> {axis, at, spans:[[a,b]], cuts:[[a,b]]}
    const key = (axis, at) => `${axis}:${at.toFixed(3)}`;
    const add = (axis, at, a, b) => {
      const k = key(axis, at);
      if (!lines.has(k)) lines.set(k, { axis, at, spans: [], cuts: [] });
      lines.get(k).spans.push([Math.min(a, b), Math.max(a, b)]);
    };
    const cut = (r, d) => {
      if (!d) return;
      const [x0, z0, x1, z1] = r.rect;
      const at = { n: ['h', z0], s: ['h', z1], w: ['v', x0], e: ['v', x1] }[d.wall];
      const k = key(at[0], at[1]);
      if (lines.has(k)) lines.get(k).cuts.push([d.at - dw / 2, d.at + dw / 2]);
    };
    const indoor = layout.rooms.filter((r) => r.kind !== 'outdoor');
    for (const r of indoor) {
      for (const [x0, z0, x1, z1] of r.parts || [r.rect]) {
        add('h', z0, x0, x1); add('h', z1, x0, x1); add('v', x0, z0, z1); add('v', x1, z0, z1);
      }
    }
    for (const r of indoor) { cut(r, r.door); cut(r, r.entrance); }
    for (const g of layout.hall_gaps || []) lines.get(key(g.axis, g.at))?.cuts.push([g.a, g.b]);
    const eps = 0.01;
    for (const ln of lines.values()) {
      const spans = ln.spans.sort((a, b) => a[0] - b[0]);
      const merged = [];
      for (const s of spans) {
        const last = merged[merged.length - 1];
        if (last && s[0] <= last[1] + eps) last[1] = Math.max(last[1], s[1]); else merged.push([...s]);
      }
      let segs = merged;
      for (const c of ln.cuts) {
        const next = [];
        for (const [a, b] of segs) {
          if (c[1] <= a || c[0] >= b) { next.push([a, b]); continue; }
          if (c[0] - a > 0.05) next.push([a, c[0]]);
          if (b - c[1] > 0.05) next.push([c[1], b]);
        }
        segs = next;
      }
      let side = null;
      if (ln.axis === 'h' && Math.abs(ln.at - hz0) < eps) side = 'n';
      if (ln.axis === 'h' && Math.abs(ln.at - hz1) < eps) side = 's';
      if (ln.axis === 'v' && Math.abs(ln.at - hx0) < eps) side = 'w';
      if (ln.axis === 'v' && Math.abs(ln.at - hx1) < eps) side = 'e';
      for (const [a, b] of segs) this.wall(ln.axis, ln.at, a, b, side, ln.cuts);
    }
    // 大门的门板（开着）
    for (const r of layout.rooms) {
      if (!r.entrance) continue;
      const door = box(0.08, 2.1, dw - 0.1, '#5a3b2a', 0, 0, 0);
      const g = new THREE.Group(); g.add(door);
      door.position.set(0, 1.05, (dw - 0.1) / 2);
      g.position.set(r.entrance.at - dw / 2 + 0.05, 0, r.rect[3]);
      g.rotation.y = -Math.PI * 0.62;       // 向屋里开，贴着墙，不挡门洞
      this.house.add(g);
    }
  }

  wall(axis, at, a, b, side, cuts) {
    const len = b - a, ext = !!side, th = ext ? 0.24 : 0.16;
    const g = new THREE.Group();
    const mid = (a + b) / 2;
    if (axis === 'h') g.position.set(mid, 0, at); else { g.position.set(at, 0, mid); g.rotation.y = Math.PI / 2; }
    const h = ext ? EXT_H : INT_H;
    const body = box(len + th * 0.5, 1, th, ext ? WALL_OUT : WALL, 0, 0, 0);
    const cap = box(len + th * 0.5, 0.05, th + 0.02, WALL_TOP, 0, 0, 0);
    g.add(body, cap);
    const win = new THREE.Group();
    if (ext && len > 2.2) {
      const n = Math.max(1, Math.floor(len / 3.4));
      for (let i = 0; i < n; i++) {
        const cx = -len / 2 + (len / n) * (i + 0.5);
        win.add(box(1.1, 0.95, th + 0.04, '#6b4a35', cx, 1.0, 0));
        for (const s of [-1, 1]) {
          const pane = new THREE.Mesh(new THREE.PlaneGeometry(0.95, 0.8), this.windowMat());
          pane.position.set(cx, 1.475, s * (th / 2 + 0.03));
          if (s < 0) pane.rotation.y = Math.PI;
          win.add(pane);
        }
      }
    }
    g.add(win);
    const w = { g, body, cap, win, side, h, ext };
    this.walls.push(w);
    this.house.add(g);
    this.setWallHeight(w, h);
  }

  windowMat() {
    if (!this._winMat) this._winMat = new THREE.MeshStandardMaterial({ color: '#9fc3e6', emissive: '#ffcf7a', emissiveIntensity: 0, roughness: 0.3 });
    return this._winMat;
  }

  setWallHeight(w, h) {
    w.body.scale.y = h; w.body.position.y = h / 2;
    w.cap.position.y = h;
    w.win.visible = h > 1.9;
  }

  updateCutaway() {
    if (!this.center) return;
    const v = this.camera.position.clone().sub(this.controls.target); v.y = 0; v.normalize();
    for (const w of this.walls) {
      let h = w.h;
      if (w.ext) {
        const near = (w.side === 's' && v.z > 0.25) || (w.side === 'n' && v.z < -0.25) || (w.side === 'e' && v.x > 0.25) || (w.side === 'w' && v.x < -0.25);
        if (near) h = LOW_H;
      } else if (this.lowWalls) h = 0.8;
      if (Math.abs(w.body.scale.y - h) > 0.001) this.setWallHeight(w, h);
    }
  }

  // ------------------------------------------------------------ 昼夜
  setHour(hour) {
    if (this.hourOverride != null) hour = this.hourOverride;
    // 0 = 白天，1 = 夜里；黎明 5:30–7:00、黄昏 17:30–19:30 渐变
    let n;
    if (hour >= 7 && hour < 17.5) n = 0;
    else if (hour >= 19.5 || hour < 5.5) n = 1;
    else if (hour < 7) n = 1 - ease((hour - 5.5) / 1.5);
    else n = ease((hour - 17.5) / 2);
    if (this.forceSky != null) n = this.forceSky;
    if (Math.abs(n - this.night) > 0.005) { this.night = n; this.applySky(); }
  }

  applySky() {
    const n = this.night, o = this.overcast;
    const c = (day, night) => new THREE.Color(day).lerp(new THREE.Color(night), n);
    this.scene.background = c('#a9cbe8', '#1c2546').lerp(c('#8b95a3', '#171d33'), o);
    this.scene.fog = new THREE.Fog(this.scene.background, 160 - o * 50, 420 - o * 120);
    this.hemi.color = c('#e4eeff', '#4a5a96'); this.hemi.groundColor = c('#7d8f62', '#232838');
    this.hemi.intensity = lerp(1.5, 1.5, n) * (1 - o * 0.12);
    if (this.sea) { this.sea.material.emissive.set('#1b2a58'); this.sea.material.emissiveIntensity = n * 0.75; }
    for (const m of this.pools || []) m.material.opacity = n * 0.6;
    this.sun.color = c('#fff2dc', '#a8b8ff'); this.sun.intensity = lerp(2.6, 0.55, n) * (1 - o * 0.62);
    if (this.grass) this.grass.color = c('#7fae59', '#4d6e42');
    if (this.sea) this.sea.material.color = c('#6fa8d6', '#141c3a').lerp(c('#71808f', '#10162c'), o);
    if (this.cloudMat) { this.cloudMat.opacity = 0.92 * (1 - n * 0.85); this.cloudMat.color = c('#ffffff', '#39436b').lerp(c('#a4abb6', '#2b3350'), o); }
    if (this.stars) this.stars.material.opacity = n;
    if (this.flies) this.flies.material.opacity = n * 0.85;
    if (this._winMat) { this._winMat.emissiveIntensity = n * 0.9; this._winMat.color = c('#a9cdee', '#ffe2a8'); }
    for (const l of this.lamps) l.userData.glow.forEach((m) => { m.emissiveIntensity = l.userData.off ? 0 : n * 1.2; });
    this.refreshLights();
  }

  lightRooms(onSet) { // onSet：有人醒着待着的房间
    for (const [id, rl] of this.roomLights) {
      const r = this.rooms.get(id);
      rl.on = onSet.has(id) || !(r?.owner || r?.vacant);
    }
    this.refreshLights();
  }

  refreshLights() {
    for (const [id, rl] of this.roomLights) {
      const own = this.rooms.get(id)?.owner;
      rl.light.intensity = this.night * (rl.on ? (own ? 6 : 8) : 0.5);
    }
  }

  // ------------------------------------------------------------ 相机
  tweenTo(target, pos, secs = 0.8) {
    const t0 = this.controls.target.clone(), p0 = this.camera.position.clone();
    let t = 0;
    this.anim = (dt) => {
      t = Math.min(1, t + dt / secs);
      const k = ease(t);
      this.controls.target.lerpVectors(t0, target, k);
      this.camera.position.lerpVectors(p0, pos, k);
      this.updateCutaway();
      if (t >= 1) this.anim = null;
    };
  }

  viewAll(instant = false) {
    const dist = Math.max(this.islandSize.w, this.islandSize.d) * (innerWidth < innerHeight ? 2.8 : 2.0) + 10;
    const target = this.islandCenter.clone().add(new THREE.Vector3(0, 0, 0.6));
    const az = this.azimuth ?? Math.PI / 4;
    this.azimuth = az;
    const pos = new THREE.Vector3(Math.sin(az) * dist * 0.62, dist * 0.78, Math.cos(az) * dist * 0.62).add(target);
    if (instant) { this.controls.target.copy(target); this.camera.position.copy(pos); this.updateCutaway(); }
    else this.tweenTo(target, pos);
  }

  rotate(dir) {
    const off = this.camera.position.clone().sub(this.controls.target);
    const sph = new THREE.Spherical().setFromVector3(off);
    const start = sph.theta, end = start + dir * Math.PI / 2;
    let t = 0;
    this.anim = (dt) => {
      t = Math.min(1, t + dt / 0.6);
      sph.theta = lerp(start, end, ease(t));
      this.camera.position.copy(new THREE.Vector3().setFromSpherical(sph).add(this.controls.target));
      this.updateCutaway();
      if (t >= 1) { this.anim = null; this.azimuth = end; }
    };
  }

  focusRoom(r) {
    const [x0, z0, x1, z1] = r.rect;
    const target = new THREE.Vector3((x0 + x1) / 2, 0, (z0 + z1) / 2);
    const dist = Math.max(x1 - x0, z1 - z0) * 1.6 + 8;
    const off = this.camera.position.clone().sub(this.controls.target).normalize().multiplyScalar(dist);
    this.tweenTo(target, target.clone().add(off));
  }

  // ------------------------------------------------------------ 点选
  bindPick() {
    const ray = new THREE.Raycaster(), p = new THREE.Vector2();
    let down = null;
    const el = this.renderer.domElement;
    el.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
    el.addEventListener('pointerup', (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 6) return;
      p.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
      ray.setFromCamera(p, this.camera);
      const hit = ray.intersectObjects(this.pickables, false)[0];
      if (hit) { this.onPick(hit.object.userData.pick); return; }
      const got = ray.intersectObjects(this.touchables, true)[0];
      const of = got?.object.userData.touchOf;
      if (!of) return;
      of.obj.userData.touch?.(got.point);
      if (of.obj.userData.touchKind === 'lamp') this.applySky();
      this.onTouch(of.room, of.obj.userData.touchKind, got.point);
    });
  }
}
