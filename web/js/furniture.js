// 家具登记表：type → 造型函数。加新家具 = 在 FURNITURE 里加一个函数。
// 约定：spec 里 x/z 是绝对坐标，w 沿 x、d 沿 z；物件默认「正面朝 +z（朝南/朝屏幕）」，face / rot 决定转向。
// 没登记的 type 会画成一个灰盒子，不会报错。
import * as THREE from 'three';

const mats = new Map();
export function mat(color, opts = {}) {
  const key = color + JSON.stringify(opts);
  if (!mats.has(key)) mats.set(key, new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0, flatShading: true, ...opts }));
  return mats.get(key);
}

export function box(w, h, d, color, x = 0, y = 0, z = 0, opts) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), typeof color === 'string' ? mat(color, opts) : color);
  m.position.set(x, y + h / 2, z);
  m.castShadow = true; m.receiveShadow = true;
  return m;
}

const FACE = { s: 0, e: Math.PI / 2, n: Math.PI, w: -Math.PI / 2 };
export const faceAngle = (f) => FACE[f] ?? 0;

const WOOD = '#9c6b45', WOOD_D = '#6e4a33', WOOD_L = '#c7996b', METAL = '#5b5e6e', WHITE = '#ecebef';

function chair(s) {
  const g = new THREE.Group();
  const c = s.color || '#3e6fb5';
  g.add(box(0.5, 0.08, 0.5, c, 0, 0.42, 0));
  g.add(box(0.5, 0.55, 0.08, c, 0, 0.5, -0.22));
  g.add(box(0.06, 0.42, 0.06, METAL, 0, 0, 0));
  g.add(box(0.44, 0.04, 0.44, METAL, 0, 0.02, 0));
  return g;
}

function desk(s) {
  const g = new THREE.Group();
  const w = s.w || 1.5, d = s.d || 0.8;
  g.add(box(w, 0.06, d, s.color || WOOD, 0, 0.72, 0));
  for (const [lx, lz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) g.add(box(0.06, 0.72, 0.06, WOOD_D, lx * (w / 2 - 0.08), 0, lz * (d / 2 - 0.08)));
  if (s.monitor) {
    g.add(box(0.7, 0.42, 0.05, '#2a2c38', 0, 0.98, -d / 2 + 0.18));
    const sm = new THREE.MeshStandardMaterial({ color: '#20232e', emissive: '#4c86c9', emissiveIntensity: 0, roughness: 0.5 });
    const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.62, 0.34), sm);
    scr.position.set(0, 1.19, -d / 2 + 0.21); g.add(scr);
    let on = false, t = 0;
    g.userData.setUse = (v) => { on = v; sm.color.set(v ? '#7fb2e8' : '#20232e'); if (!v) sm.emissiveIntensity = 0; };
    g.userData.tick = (dt) => { if (on) { t += dt; sm.emissiveIntensity = 0.6 + Math.sin(t * 9) * 0.05; } };
    g.add(box(0.08, 0.2, 0.08, '#2a2c38', 0, 0.78, -d / 2 + 0.18));
    g.add(box(0.46, 0.03, 0.16, '#3a3c48', 0, 0.78, 0.05));
  }
  return g;
}

function bed(s) {
  const g = new THREE.Group();
  const w = s.w || 2, d = s.d || 3;
  g.add(box(w, 0.32, d, WOOD, 0, 0, 0));
  g.add(box(w, 0.9, 0.12, WOOD_D, 0, 0, -d / 2 + 0.06));
  g.add(box(w - 0.12, 0.2, d - 0.2, '#f4f1ec', 0, 0.32, 0.04));
  g.add(box(w * 0.55, 0.14, 0.45, '#ffffff', 0, 0.52, -d / 2 + 0.45));
  g.add(box(w - 0.06, 0.08, d * 0.55, s.color || '#8fa4d8', 0, 0.52, d * 0.18));
  return g;
}

function shelf(s) {
  const g = new THREE.Group();
  const w = s.w || 0.6, d = s.d || 1.8, h = s.h || 1.7;
  g.add(box(w, h, d, WOOD_L, 0, 0, 0));
  const cols = ['#c0504a', '#3e6fb5', '#e3b23c', '#5d9b6a', '#8a6bbd', '#d97c3a'];
  const n = Math.floor(h / 0.45);
  for (let i = 0; i < n; i++) {
    const y = 0.15 + i * 0.45;
    let p = -d / 2 + 0.12;
    while (p < d / 2 - 0.2) {
      const bw = 0.08 + Math.random() * 0.08, bh = 0.22 + Math.random() * 0.12;
      const along = d > w;
      g.add(box(along ? w + 0.04 : bw, bh, along ? bw : d + 0.04, cols[(i * 7 + Math.round(p * 31)) % cols.length], along ? 0 : p, y, along ? p : 0));
      p += bw + 0.03;
    }
  }
  return g;
}

function sofa(s) {
  const g = new THREE.Group();
  const w = s.w || 3, d = s.d || 1, c = s.color || '#d4a03a';
  g.add(box(w, 0.4, d, c, 0, 0, 0));
  g.add(box(w, 0.55, 0.28, c, 0, 0.35, -d / 2 + 0.14));
  g.add(box(0.26, 0.3, d, c, -w / 2 + 0.13, 0.35, 0));
  g.add(box(0.26, 0.3, d, c, w / 2 - 0.13, 0.35, 0));
  const pillow = new THREE.Color(c).offsetHSL(0, 0, 0.12).getStyle();
  g.add(box(0.5, 0.36, 0.14, '#4d6fb8', -w / 2 + 0.6, 0.42, -d / 2 + 0.34));
  g.add(box(0.5, 0.36, 0.14, pillow, w / 2 - 0.6, 0.42, -d / 2 + 0.34));
  return g;
}

function armchair(s) { return sofa({ ...s, w: 1.1, d: 0.95 }); }

function table(s) {
  const g = new THREE.Group();
  const w = s.w || 2, d = s.d || 1.2;
  g.add(box(w, 0.07, d, WOOD_L, 0, 0.72, 0));
  for (const [lx, lz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) g.add(box(0.07, 0.72, 0.07, WOOD_D, lx * (w / 2 - 0.1), 0, lz * (d / 2 - 0.1)));
  g.add(box(0.2, 0.12, 0.2, '#e9e2d5', -0.3, 0.79, 0));
  return g;
}

function coffee_table(s) {
  const g = new THREE.Group();
  const w = s.w || 1.8, d = s.d || 0.9;
  g.add(box(w, 0.08, d, WOOD_D, 0, 0.36, 0));
  g.add(box(w - 0.2, 0.36, d - 0.2, '#4a3426', 0, 0, 0));
  g.add(box(0.3, 0.05, 0.22, '#3e6fb5', 0.3, 0.44, 0.05));
  return g;
}

function rug(s) {
  const r = new THREE.Mesh(new THREE.BoxGeometry(s.w || 2, 0.03, s.d || 1.5), mat(s.color || '#b9a7cf'));
  r.position.y = 0.015; r.receiveShadow = true;
  return r;
}

function mat_(s) { return rug({ ...s, color: s.color || '#8b5a3c' }); }

function lamp(s) {
  const g = new THREE.Group();
  g.add(box(0.36, 0.05, 0.36, METAL, 0, 0, 0));
  g.add(box(0.05, 1.3, 0.05, METAL, 0, 0.05, 0));
  const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.26, 0.3, 8, 1, true), new THREE.MeshStandardMaterial({ color: '#f6e3b8', roughness: 0.85, flatShading: true, emissive: '#ffcf7a', emissiveIntensity: 0.0, side: THREE.DoubleSide }));
  shade.position.y = 1.45; g.add(shade);
  g.userData.glow = [shade.material];
  g.userData.light = { y: 1.4, intensity: 3.5, distance: 6 };
  g.userData.touchKind = 'lamp';
  g.userData.touch = () => { g.userData.off = !g.userData.off; };
  return g;
}

function plant(s) {
  const g = new THREE.Group();
  const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.15, 0.32, 7), mat('#b5653e'));
  pot.position.y = 0.16; pot.castShadow = true; g.add(pot);
  const leaf = new THREE.Mesh(new THREE.IcosahedronGeometry(0.34, 0), mat(s.color || '#4f8d4a'));
  leaf.position.y = 0.62; leaf.scale.set(1, 1.25, 1); leaf.castShadow = true; g.add(leaf);
  const drops = [0, 1, 2].map(() => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.035, 6, 5), mat('#7fc6ee')); m.visible = false; g.add(m); return m; });
  let on = false, t = 0, wig = 0, grow = 1;
  g.userData.setUse = (v) => { on = v; if (!v) drops.forEach((m) => { m.visible = false; }); };
  g.userData.touchKind = 'plant';
  g.userData.touch = () => { wig = 1.6; };
  g.userData.tick = (dt) => {
    t += dt; wig = Math.max(0, wig - dt);
    leaf.rotation.z = Math.sin(t * 9) * 0.14 * Math.min(1, wig);
    if (on) {
      grow = Math.min(1.25, grow + dt * 0.012);
      leaf.scale.set(grow, 1.25 * grow, grow);
      drops.forEach((m, i) => { const k = (t * 1.2 + i / 3) % 1; m.visible = true; m.position.set(Math.sin(i * 2.1) * 0.22, 1.25 - k * 0.8, Math.cos(i * 2.1) * 0.22); });
    }
  };
  return g;
}

function bookshelf(s) { return shelf({ ...s, h: s.h || 2 }); }

function cabinet(s) {
  const g = new THREE.Group();
  const w = s.w || 2, d = s.d || 0.6, h = s.h || 0.9;
  g.add(box(w, h, d, '#5a3e2e', 0, 0, 0));
  g.add(box(w - 0.1, 0.04, 0.02, '#c9a77c', 0, h * 0.55, d / 2));
  return g;
}

function fridge(s) {
  const g = new THREE.Group();
  const w = s.w || 1, d = s.d || 0.9, h = s.h || 2.1;
  g.add(box(w, h, d, '#c9c9d2', 0, 0, -0.03));
  const inside = box(w - 0.14, h - 0.2, 0.02, '#fff4d8', 0, 0.1, d / 2 - 0.05, { emissive: '#ffe9b0', emissiveIntensity: 0.5 });
  g.add(inside);
  const hinge = new THREE.Group(); hinge.position.set(-w / 2, 0, d / 2); g.add(hinge);
  hinge.add(box(w, h, 0.07, WHITE, w / 2, 0, 0));
  hinge.add(box(w - 0.04, 0.02, 0.02, '#b8b8c4', w / 2, h * 0.62, 0.04));
  hinge.add(box(0.05, 0.4, 0.05, '#9a9aa8', w - 0.15, h * 0.7, 0.06));
  let open = false, to = 0, timer = 0;
  g.userData.setUse = (v) => { open = v; };
  g.userData.touchKind = 'fridge';
  g.userData.touch = () => { timer = 2.5; };
  g.userData.tick = (dt) => {
    timer = Math.max(0, timer - dt);
    to = open || timer > 0 ? -1.2 : 0;
    hinge.rotation.y += (to - hinge.rotation.y) * Math.min(1, dt * 6);
  };
  return g;
}

function counter(s) {
  const g = new THREE.Group();
  const w = s.w || 4, d = s.d || 0.8;
  g.add(box(w, 0.86, d, '#d9d4c9', 0, 0, 0));
  g.add(box(w + 0.04, 0.06, d + 0.04, '#7c7f90', 0, 0.86, 0));
  const sx = s.stove_at ?? w / 4;
  g.add(box(0.8, 0.03, 0.55, '#2f3038', sx, 0.92, 0));
  for (const [a, b] of [[-0.18, -0.12], [0.18, -0.12], [-0.18, 0.12], [0.18, 0.12]]) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.08, 0.015, 4, 10), mat('#888'));
    ring.rotation.x = Math.PI / 2; ring.position.set(sx + a, 0.96, b); g.add(ring);
  }
  g.add(box(0.5, 0.18, 0.4, '#c6cbd6', sx - 1.3, 0.92, 0));
  const pot = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.12, 0.16, 8), mat('#b9473c'));
  pot.position.set(sx + 0.18, 1.04, -0.12); g.add(pot);
  const fire = new THREE.Mesh(new THREE.ConeGeometry(0.08, 0.14, 6), mat('#ff9a3c', { emissive: '#ff7a1c', emissiveIntensity: 1.4 }));
  fire.position.set(sx + 0.18, 1.0, -0.12); fire.visible = false; g.add(fire);
  const puffs = [0, 1, 2].map(() => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.09, 7, 6), new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0, depthWrite: false })); g.add(m); return m; });
  let on = false, t = 0;
  g.userData.setUse = (v) => { on = v; fire.visible = v; if (!v) puffs.forEach((m) => { m.material.opacity = 0; }); };
  g.userData.tick = (dt) => {
    if (!on) return;
    t += dt;
    fire.scale.y = 0.8 + Math.sin(t * 22) * 0.25;
    pot.position.x = sx + 0.18 + Math.sin(t * 30) * 0.004;
    puffs.forEach((m, i) => { const k = (t * 0.45 + i / 3) % 1; m.position.set(sx + 0.18 + Math.sin(k * 7 + i) * 0.06, 1.15 + k * 0.85, -0.12); m.scale.setScalar(0.7 + k * 1.3); m.material.opacity = (1 - k) * 0.45; });
  };
  return g;
}

function tv(s) {
  const g = new THREE.Group();
  const w = s.w || 2.4;
  g.add(box(w, 0.5, 0.5, '#4a3426', 0, 0, 0));
  g.add(box(w * 0.82, w * 0.48, 0.08, '#1d1f2a', 0, 0.62, -0.05));
  const sm = new THREE.MeshStandardMaterial({ color: '#14151d', emissive: '#2f4fd0', emissiveIntensity: 0, roughness: 0.4 });
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(w * 0.76, w * 0.42), sm);
  scr.position.set(0, 0.62 + w * 0.24, 0); g.add(scr);
  let used = false, forced = null, t = 0, next = 0;
  const paint = () => { const live = forced ?? used; sm.color.set(live ? '#3557c9' : '#14151d'); if (!live) sm.emissiveIntensity = 0; };
  g.userData.setUse = (v) => { if (v !== used) forced = null; used = v; paint(); };
  g.userData.touchKind = 'tv';
  g.userData.touch = () => { forced = !(forced ?? used); paint(); };
  g.userData.tick = (dt) => {
    if (!(forced ?? used)) return;
    t += dt;
    if (t > next) { next = t + 0.8 + Math.random() * 2.2; sm.emissive.setHSL(Math.random(), 0.65, 0.45); }
    sm.emissiveIntensity = 0.75 + Math.sin(t * 17) * 0.08;
  };
  return g;
}

function beanbag(s) {
  const m = new THREE.Mesh(new THREE.IcosahedronGeometry(0.55, 1), mat(s.color || '#c0504a'));
  m.scale.set(1.1, 0.55, 1.1); m.position.y = 0.28; m.castShadow = true;
  const g = new THREE.Group(); g.add(m); return g;
}

function boxes(s) {
  const g = new THREE.Group();
  const c = ['#b98d5e', '#a77a4c', '#c79d6c'];
  const set = [[0, 0, 0, 0.9], [0.95, 0, 0.1, 0.8], [0.4, 0.82, 0.05, 0.75], [-0.1, 0, 0.95, 0.7], [0.5, 1.5, 0, 0.55]];
  set.forEach(([x, y, z, sz], i) => {
    const b = box(sz, sz * 0.82, sz, c[i % 3], x - 0.4, y, z - 0.3);
    b.rotation.y = (i % 2 ? 0.12 : -0.08); g.add(b);
    g.add(box(sz * 1.01, 0.02, 0.12, '#e8d6b5', x - 0.4, y + sz * 0.82, z - 0.3));
  });
  return g;
}

// ---------------------------------------------------------------- 游乐场
// 能坐上去的设施在 g.userData.ride 里放一个控制器：
//   seats[i]  住户跟着走的锚点（它的世界坐标就是住户脚下的位置）
//   occ[i]    这一帧有没有人（people.js 每帧置 true，update 读完清掉）
//   update(dt)、pose(i)、yaw(i)  后两个可以没有
const RED = '#d9574a', YELLOW = '#efc24a', BLUE = '#4f86d9', STEEL = '#8a8fa3';
const SEAT_DROP = 0.47;     // 坐姿时屁股比脚底高这么多

function makeRide(n, fields) { return { seats: [], occ: new Array(n).fill(false), ...fields }; }
function clearOcc(r) { r.occ.fill(false); }
function anchor(parent, x, y, z) { const a = new THREE.Object3D(); a.position.set(x, y, z); parent.add(a); return a; }
const approach = (v, to, step) => (Math.abs(to - v) <= step ? to : v + Math.sign(to - v) * step);

function bar(a, b, r, color) {
  const A = new THREE.Vector3(...a), B = new THREE.Vector3(...b), d = B.clone().sub(A);
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, d.length(), 8), mat(color, { flatShading: false }));
  m.position.copy(A).addScaledVector(d, 0.5);
  m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d.normalize());
  m.castShadow = true;
  return m;
}

function swing(s) {
  const g = new THREE.Group();
  const H = 2.4, W = 2;
  for (const sx of [-1, 1]) {
    g.add(bar([sx * W * 1.05, 0, -0.8], [sx * W * 1.05, H, 0], 0.06, RED), bar([sx * W * 1.05, 0, 0.8], [sx * W * 1.05, H, 0], 0.06, RED));
  }
  g.add(bar([-W * 1.05, H, 0], [W * 1.05, H, 0], 0.06, YELLOW));
  const pivots = [-1, 1].map((sx) => {
    const p = new THREE.Group(); p.position.set(sx, H, 0); g.add(p);
    p.add(box(0.62, 0.05, 0.3, BLUE, 0, -H + 0.47, 0));
    for (const rx of [-0.27, 0.27]) p.add(bar([rx, 0, 0], [rx, -H + 0.5, 0], 0.012, '#54586a'));
    return p;
  });
  const st = [{ a: 0, t: 0 }, { a: 0, t: 1.1 }];
  const ride = makeRide(2, { update(dt) {
    pivots.forEach((p, i) => {
      st[i].a = approach(st[i].a, this.occ[i] ? 0.46 : 0, dt * (this.occ[i] ? 0.35 : 0.2));
      st[i].t += dt * 2.0;
      p.rotation.x = st[i].a * Math.sin(st[i].t);
    });
    clearOcc(this);
  } });
  ride.seats = pivots.map((p) => anchor(p, 0, -H + 0.47 + 0.05 - SEAT_DROP, 0));
  g.userData.ride = ride;
  return g;
}

function seesaw(s) {
  const g = new THREE.Group();
  const Y = 0.72, L = 1.7;
  g.add(box(0.5, Y, 0.34, STEEL, 0, 0, 0));
  const beam = new THREE.Group(); beam.position.y = Y; g.add(beam);
  beam.add(box(L * 2 + 0.2, 0.08, 0.34, YELLOW, 0, -0.02, 0));
  for (const sx of [-1, 1]) {
    beam.add(box(0.48, 0.05, 0.36, RED, sx * L, 0.05, 0));
    beam.add(bar([sx * (L - 0.42), 0, -0.14], [sx * (L - 0.42), 0.48, -0.14], 0.025, BLUE), bar([sx * (L - 0.42), 0, 0.14], [sx * (L - 0.42), 0.48, 0.14], 0.025, BLUE));
    beam.add(bar([sx * (L - 0.42), 0.48, -0.14], [sx * (L - 0.42), 0.48, 0.14], 0.025, BLUE));
  }
  let t = 0;
  const TILT = 0.2;
  const ride = makeRide(2, { update(dt) {
    t += dt * 2.1;
    let to = 0;
    if (this.occ[0] && this.occ[1]) to = TILT * Math.sin(t);
    else if (this.occ[0]) to = TILT;      // 左边有人：左端压下（绕 z 轴正转）
    else if (this.occ[1]) to = -TILT;
    beam.rotation.z = approach(beam.rotation.z, to, dt * 1.2);
    clearOcc(this);
  }, yaw(i) { return i ? -Math.PI / 2 : Math.PI / 2; } });
  ride.seats = [-1, 1].map((sx) => anchor(beam, sx * L, 0.1 - SEAT_DROP, 0));
  g.userData.ride = ride;
  return g;
}

function slide(s) {
  const g = new THREE.Group();
  const H = 1.7, zTop = -1.3, zEnd = 1.9, LOW = 0.55;
  for (const [x, z] of [[-0.5, -1.9], [0.5, -1.9], [-0.5, -1.0], [0.5, -1.0]]) g.add(box(0.08, H + 0.7, 0.08, RED, x, 0, z));
  g.add(box(1.1, 0.08, 1.0, YELLOW, 0, H - 0.08, -1.45));
  for (const i of [0, 1, 2, 3, 4, 5]) g.add(box(1.0, 0.05, 0.08, STEEL, 0, 0.28 * i + 0.14, -2.0));
  g.add(box(1.25, 0.08, 1.15, BLUE, 0, H + 0.7, -1.45));
  const len = Math.hypot(zEnd - zTop, H - LOW), ang = Math.atan2(H - LOW, zEnd - zTop);
  const chute = new THREE.Group();
  chute.position.set(0, (H + LOW) / 2, (zTop + zEnd) / 2); chute.rotation.x = ang; g.add(chute);
  chute.add(box(0.9, 0.05, len, YELLOW, 0, -0.03, 0));
  for (const sx of [-1, 1]) chute.add(box(0.06, 0.2, len, RED, sx * 0.47, -0.04, 0));
  g.add(box(0.07, LOW, 0.07, STEEL, -0.4, 0, zEnd - 0.2), box(0.07, LOW, 0.07, STEEL, 0.4, 0, zEnd - 0.2));

  // 一圈：绕到梯子 → 爬上去 → 坐好 → 滑下来 → 站起来
  const F = 0, B = Math.PI, E = Math.PI / 2, W = -Math.PI / 2;
  const P = [
    { p: [0, 0, zEnd + 0.7], t: 1.4, pose: 'stand', yaw: E },
    { p: [1.15, 0, zEnd + 0.4], t: 2.2, pose: 'walk', yaw: B },
    { p: [1.15, 0, -2.6], t: 1.0, pose: 'walk', yaw: W },
    { p: [0, 0, -2.6], t: 1.2, pose: 'walk', yaw: B },
    { p: [0, H - 0.04, -1.8], t: 0.8, pose: 'stand', yaw: F },
    { p: [0, H - 0.04, -1.25], t: 0.8, pose: 'sit', yaw: F },
    { p: [0, H - SEAT_DROP, -1.25], t: 1.5, pose: 'sit', yaw: F },
    { p: [0, LOW - SEAT_DROP, zEnd], t: 0.5, pose: 'sit', yaw: F },
    { p: [0, 0, zEnd + 0.7], t: 0, pose: 'stand', yaw: F },
  ];
  const total = P.slice(0, -1).reduce((a, x) => a + x.t, 0);
  const a0 = anchor(g, ...P[0].p);
  let time = 0, seg = 0, idle = true;
  const ride = makeRide(1, {
    update(dt) {
      if (this.occ[0]) { idle = false; time = (time + dt) % total; } else if (!idle) { time = 0; idle = true; }
      let t = time; seg = 0;
      while (seg < P.length - 2 && t >= P[seg].t) { t -= P[seg].t; seg++; }
      const k = P[seg].t ? Math.min(1, t / P[seg].t) : 1, A = P[seg].p, C = P[seg + 1].p;
      a0.position.set(A[0] + (C[0] - A[0]) * k, A[1] + (C[1] - A[1]) * k, A[2] + (C[2] - A[2]) * k);
      clearOcc(this);
    },
    pose() { return P[seg].pose; },
    yaw() { return P[seg].yaw; },
  });
  ride.seats = [a0];
  g.userData.ride = ride;
  return g;
}

function carousel(s) {
  const g = new THREE.Group();
  const R = 1.7;
  const base = new THREE.Mesh(new THREE.CylinderGeometry(R + 0.15, R + 0.2, 0.1, 28), mat(STEEL));
  base.position.y = 0.05; base.receiveShadow = true; g.add(base);
  const disc = new THREE.Group(); disc.position.y = 0.1; g.add(disc);
  const top = new THREE.Mesh(new THREE.CylinderGeometry(R, R, 0.1, 28), mat(YELLOW));
  top.position.y = 0.05; top.castShadow = true; top.receiveShadow = true; disc.add(top);
  disc.add(bar([0, 0, 0], [0, 1.5, 0], 0.07, RED));
  const cols = [RED, BLUE, '#5aa76a'];
  const seats = [0, 1, 2].map((i) => {
    const th = (i / 3) * Math.PI * 2, x = Math.sin(th) * 1.15, z = Math.cos(th) * 1.15;
    const seat = box(0.5, 0.36, 0.5, cols[i], x, 0.1, z);
    seat.rotation.y = th; disc.add(seat);
    disc.add(bar([x * 0.55, 1.05, z * 0.55], [0, 1.45, 0], 0.03, STEEL), bar([x * 0.55, 0.1, z * 0.55], [x * 0.55, 1.05, z * 0.55], 0.03, STEEL));
    return anchor(disc, x, 0.46 - SEAT_DROP, z);
  });
  let spin = 0;
  const ride = makeRide(3, { update(dt) {
    spin = approach(spin, this.occ.some(Boolean) ? 0.9 : 0, dt * 0.5);
    disc.rotation.y += spin * dt;
    clearOcc(this);
  }, yaw(i) { return disc.rotation.y + (i / 3) * Math.PI * 2 + Math.PI / 2; } });
  ride.seats = seats;
  g.userData.ride = ride;
  return g;
}

function sandbox(s) {
  const g = new THREE.Group();
  const w = s.w || 4, d = s.d || 3.2;
  g.add(box(w - 0.2, 0.14, d - 0.2, '#e8d29b', 0, 0, 0));
  for (const sz of [-1, 1]) g.add(box(w, 0.26, 0.16, WOOD, 0, 0, sz * (d / 2 - 0.08)));
  for (const sx of [-1, 1]) g.add(box(0.16, 0.26, d - 0.3, WOOD, sx * (w / 2 - 0.08), 0, 0));
  const hill = new THREE.Mesh(new THREE.ConeGeometry(0.5, 0.35, 9), mat('#dcc184'));
  hill.position.set(0.2, 0.3, -0.5); hill.castShadow = true; g.add(hill);
  const pail = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.11, 0.24, 10), mat(RED));
  pail.position.set(-0.9, 0.26, 0.7); pail.castShadow = true; g.add(pail);
  return g;
}

function bench(s) {
  const g = new THREE.Group();
  const w = s.w || 2.2;
  g.add(box(w, 0.07, 0.5, WOOD, 0, 0.44, 0));
  g.add(box(w, 0.42, 0.06, WOOD, 0, 0.62, -0.26));
  for (const sx of [-1, 1]) g.add(box(0.08, 0.46, 0.46, METAL, sx * (w / 2 - 0.2), 0, 0));
  return g;
}

function lamp_post(s) {
  const g = new THREE.Group();
  g.add(bar([0, 0, 0], [0, 3, 0], 0.06, METAL));
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.22, 12, 10), mat('#f6e3b8', { emissive: '#ffcf7a', emissiveIntensity: 0, flatShading: false }));
  head.position.y = 3.1; g.add(head);
  g.userData.glow = [head.material];
  return g;
}

function fence(s) {
  // 沿 x 或 z 的一段矮栅栏，len 是长度，gap_at/gap 留出口
  const g = new THREE.Group();
  const len = s.len || 6, n = Math.round(len / 0.8);
  const hasGap = (x) => s.gap_at != null && Math.abs(x - s.gap_at) < (s.gap || 2) / 2;
  for (let i = 0; i <= n; i++) {
    const x = -len / 2 + (len / n) * i;
    if (!hasGap(x)) g.add(box(0.1, 0.72, 0.1, '#e9dfc9', x, 0, 0));
  }
  const pieces = s.gap_at == null ? [[-len / 2, len / 2]] : [[-len / 2, s.gap_at - (s.gap || 2) / 2], [s.gap_at + (s.gap || 2) / 2, len / 2]];
  for (const [a, b] of pieces) for (const y of [0.3, 0.56]) g.add(box(b - a, 0.06, 0.05, '#e9dfc9', (a + b) / 2, y, 0));
  return g;
}

// ---------------------------------------------------------------- 屋里新添的
function piano(s) {
  const g = new THREE.Group();
  g.add(box(2.0, 1.15, 0.55, '#1d1b22', 0, 0, 0));
  g.add(box(2.0, 0.08, 0.5, '#26242c', 0, 0.68, 0.45));
  g.add(box(1.86, 0.03, 0.26, '#f4f1ea', 0, 0.76, 0.56));
  for (let i = 0; i < 13; i++) if (i % 7 !== 2 && i % 7 !== 6) g.add(box(0.06, 0.035, 0.15, '#17161b', -0.84 + i * 0.14, 0.785, 0.5));
  g.add(box(0.1, 0.68, 0.1, '#1d1b22', -0.92, 0, 0.62), box(0.1, 0.68, 0.1, '#1d1b22', 0.92, 0, 0.62));
  g.add(box(0.9, 0.46, 0.38, '#5a3e2e', 0, 0, 1.05));
  const notes = [0, 1, 2].map(() => { const m = box(0.09, 0.14, 0.03, '#ffd77a', 0, 0, 0, { emissive: '#ffb84a', emissiveIntensity: 0.8 }); m.visible = false; g.add(m); return m; });
  let on = false, t = 0, burst = 0;
  g.userData.setUse = (v) => { on = v; };
  g.userData.touchKind = 'piano';
  g.userData.touch = () => { burst = 1.8; };
  g.userData.tick = (dt) => {
    t += dt; burst = Math.max(0, burst - dt);
    const live = on || burst > 0;
    notes.forEach((m, i) => { m.visible = live; if (live) { const k = (t * 0.55 + i / 3) % 1; m.position.set(Math.sin(k * 8 + i) * 0.55, 1.3 + k * 1.1, 0.2); } });
  };
  return g;
}

function easel(s) {
  const g = new THREE.Group();
  g.add(bar([-0.4, 0, 0.2], [0, 1.7, 0], 0.03, WOOD_D), bar([0.4, 0, 0.2], [0, 1.7, 0], 0.03, WOOD_D), bar([0, 0, -0.45], [0, 1.7, 0], 0.03, WOOD_D));
  g.add(box(0.9, 0.05, 0.14, WOOD_L, 0, 0.72, 0.18));
  const board = new THREE.Group(); board.position.set(0, 0.75, 0.16); board.rotation.x = -0.14; g.add(board);
  board.add(box(0.95, 0.75, 0.03, '#f6f1e6', 0, 0, 0));
  const cols = ['#d9574a', '#4f86d9', '#efc24a', '#5aa76a', '#8a6bbd'];
  const dabs = cols.map((c, i) => { const m = box(0.12 + i * 0.04, 0.09 + (i % 2) * 0.06, 0.012, c, -0.28 + i * 0.13, 0.12 + ((i * 3) % 5) * 0.1, 0.02); m.visible = false; board.add(m); return m; });
  let on = false, t = 0, n = 0;
  g.userData.setUse = (v) => { on = v; };
  g.userData.tick = (dt) => { if (!on) return; t += dt; if (t > 2.5 && n < dabs.length) { t = 0; dabs[n++].visible = true; } };
  return g;
}

function chess(s) {
  const g = new THREE.Group();
  g.add(box(0.2, 0.68, 0.2, WOOD_D, 0, 0, 0), box(0.9, 0.05, 0.9, WOOD_L, 0, 0.68, 0));
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) g.add(box(0.17, 0.012, 0.17, (i + j) % 2 ? '#3a2e28' : '#e8dcc6', -0.27 + i * 0.18, 0.73, -0.27 + j * 0.18));
  const pieces = [[-0.27, -0.27, '#f2eee4'], [0.09, -0.09, '#f2eee4'], [0.27, 0.27, '#2b2622'], [-0.09, 0.09, '#2b2622']].map(([x, z, c]) => { const m = new THREE.Mesh(new THREE.ConeGeometry(0.05, 0.16, 7), mat(c)); m.position.set(x, 0.82, z); g.add(m); return m; });
  let on = false, t = 0, i = 0;
  g.userData.setUse = (v) => { on = v; };
  g.userData.tick = (dt) => { if (!on) return; t += dt; if (t > 3) { t = 0; const m = pieces[i++ % pieces.length]; m.position.x = Math.max(-0.27, Math.min(0.27, m.position.x + (Math.random() < 0.5 ? 0.18 : -0.18))); } };
  return g;
}

function cat(s) {
  const g = new THREE.Group();
  const bed = new THREE.Mesh(new THREE.CylinderGeometry(0.46, 0.4, 0.14, 12), mat('#c98f6a')); bed.position.y = 0.07; bed.receiveShadow = true; g.add(bed);
  const pad = new THREE.Mesh(new THREE.CylinderGeometry(0.36, 0.36, 0.03, 12), mat('#f1e0c8')); pad.position.y = 0.15; g.add(pad);
  const pet = new THREE.Group(); g.add(pet);
  const C = '#e0a050', D = '#b9783a';
  pet.add(box(0.2, 0.17, 0.46, C, 0, 0.1, 0));
  pet.add(box(0.2, 0.18, 0.2, C, 0, 0.21, 0.3));
  for (const sx of [-1, 1]) {
    const ear = new THREE.Mesh(new THREE.ConeGeometry(0.05, 0.1, 4), mat(D)); ear.position.set(sx * 0.07, 0.43, 0.3); pet.add(ear);
    pet.add(box(0.03, 0.03, 0.01, '#222', sx * 0.05, 0.3, 0.405));
    pet.add(box(0.05, 0.1, 0.05, D, sx * 0.06, 0, 0.17), box(0.05, 0.1, 0.05, D, sx * 0.06, 0, -0.17));
  }
  const tail = new THREE.Group(); tail.position.set(0, 0.24, -0.22); pet.add(tail);
  tail.add(box(0.05, 0.32, 0.05, D, 0, 0, 0)); tail.rotation.x = -0.5;
  const WAY = [[0, 0], [-1.2, -2.6], [-4.5, -3.6], [-1.2, -2.6], [0, 0], [-1, 2.6]];
  let i = 0, wait = 3, t = 0, hold = 0, used = false;
  pet.position.y = 0.16;
  g.userData.setUse = (v) => { used = v; };
  g.userData.touchKind = 'cat';
  g.userData.touch = () => { hold = 4; };
  g.userData.tick = (dt) => {
    t += dt; hold = Math.max(0, hold - dt);
    tail.rotation.z = Math.sin(t * (hold > 0 ? 8 : 2.4)) * 0.4;
    if (used || hold > 0) { const bob = Math.abs(Math.sin(t * 9)) * 0.02; pet.scale.y = 1 + bob; return; }
    pet.scale.y = 1;
    const [ax, az] = WAY[(i + 1) % WAY.length];
    if (wait > 0) { wait -= dt; return; }
    const dx = ax - pet.position.x, dz = az - pet.position.z, d = Math.hypot(dx, dz);
    if (d < 0.05) { i = (i + 1) % WAY.length; wait = 2 + Math.random() * 9; pet.position.y = i === 0 ? 0.16 : 0; return; }
    pet.position.x += (dx / d) * dt * 0.75; pet.position.z += (dz / d) * dt * 0.75;
    pet.position.y = 0;
    pet.rotation.y = Math.atan2(dx, dz);
  };
  return g;
}

// ---------------------------------------------------------------- 湖
function bird(kind) {
  const g = new THREE.Group();
  const ball = (r, c) => { const m = new THREE.Mesh(new THREE.SphereGeometry(r, 9, 7), mat(c, { flatShading: false })); m.castShadow = true; return m; };
  if (kind === 'swan') {
    const b = ball(0.42, '#fbfaf5'); b.scale.set(0.82, 0.68, 1.3); b.position.y = 0.22; g.add(b);
    g.add(bar([0, 0.3, 0.38], [0, 0.72, 0.56], 0.07, '#fbfaf5'), bar([0, 0.72, 0.56], [0, 1.02, 0.5], 0.06, '#fbfaf5'));
    const h = ball(0.12, '#fbfaf5'); h.position.set(0, 1.06, 0.56); g.add(h);
    const k = new THREE.Mesh(new THREE.ConeGeometry(0.05, 0.18, 6), mat('#e8863a')); k.rotation.x = Math.PI / 2; k.position.set(0, 1.04, 0.72); g.add(k);
    const tl = new THREE.Mesh(new THREE.ConeGeometry(0.14, 0.32, 6), mat('#fbfaf5')); tl.rotation.x = -1.0; tl.position.set(0, 0.36, -0.54); g.add(tl);
  } else {
    const baby = kind === 'duckling';
    const s = baby ? 0.52 : 1;
    const body = ball(0.24 * s, baby ? '#f3d25a' : '#8c6f4c'); body.scale.set(0.85, 0.72, 1.3); body.position.y = 0.13 * s; g.add(body);
    const head = ball(0.13 * s, baby ? '#f3d25a' : '#2e7a55'); head.position.set(0, 0.36 * s, 0.26 * s); g.add(head);
    const k = new THREE.Mesh(new THREE.ConeGeometry(0.05 * s, 0.14 * s, 6), mat('#efa03a')); k.rotation.x = Math.PI / 2; k.position.set(0, 0.34 * s, 0.42 * s); g.add(k);
    if (!baby) g.add(box(0.2, 0.03, 0.05, '#f2f0e8', 0, 0.26, 0.17));
  }
  return g;
}

function lake(s) {
  const g = new THREE.Group();
  const rx = (s.w || 22) / 2, rz = (s.d || 12) / 2;
  const disc = (ax, az, y, m) => { const d = new THREE.Mesh(new THREE.CircleGeometry(1, 56), m); d.rotation.x = -Math.PI / 2; d.scale.set(ax, az, 1); d.position.y = y; d.receiveShadow = true; g.add(d); return d; };
  disc(rx + 0.9, rz + 0.9, 0.012, mat('#cdbd8d'));
  disc(rx + 0.25, rz + 0.25, 0.024, mat('#3f7f94'));
  const wm = new THREE.MeshStandardMaterial({ color: '#58a9cc', roughness: 0.2, metalness: 0.1, emissive: '#16405a', emissiveIntensity: 0.28 });
  disc(rx, rz, 0.036, wm);
  const inside = (x, z, k) => (x / (rx * k)) ** 2 + (z / (rz * k)) ** 2 < 1;
  let seed = 41; const r = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < 16; i++) {
    const a = r() * Math.PI * 2, x = Math.cos(a) * rx * (0.5 + r() * 0.38), z = Math.sin(a) * rz * (0.5 + r() * 0.38);
    const pad = new THREE.Mesh(new THREE.CircleGeometry(0.28 + r() * 0.18, 9), mat('#4f9a58')); pad.rotation.x = -Math.PI / 2; pad.position.set(x, 0.05, z); g.add(pad);
    if (i % 4 === 0) { const f = new THREE.Mesh(new THREE.IcosahedronGeometry(0.09, 0), mat('#f2b8cf')); f.position.set(x, 0.12, z); g.add(f); }
  }
  for (let i = 0; i < 42; i++) {
    const a = r() * Math.PI * 2, x = Math.cos(a) * (rx + 0.45), z = Math.sin(a) * (rz + 0.45);
    if (z < -rz * 0.55 && Math.abs(x) < rx * 0.62) continue;          // 北岸留给人站
    const h = 0.7 + r() * 0.8;
    g.add(bar([x, 0, z], [x + (r() - 0.5) * 0.2, h, z], 0.022, '#5e8a44'));
    if (i % 2) { const t = new THREE.Mesh(new THREE.CapsuleGeometry(0.05, 0.16, 3, 6), mat('#6b4a2f')); t.position.set(x, h, z); g.add(t); }
  }
  const rings = [0, 1, 2, 3, 4].map(() => { const m = new THREE.Mesh(new THREE.RingGeometry(0.88, 1, 28), new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide })); m.rotation.x = -Math.PI / 2; m.position.y = 0.06; g.add(m); return { m, life: 0 }; });
  const ripple = (x, z) => { const o = rings.find((q) => q.life <= 0) || rings[0]; o.life = 1; o.m.position.x = x; o.m.position.z = z; };
  const birds = [];
  const add = (kind, x, z, lead) => { const o = bird(kind); g.add(o); const b = { kind, o, x, z, h: r() * 6.28, tx: x, tz: z, wait: r() * 3, lead }; birds.push(b); return b; };
  const mom = add('duck', -5, 1); add('duckling', -5.7, 1.4, mom); add('duckling', -6.3, 1.7, birds[1]); add('duckling', -6.9, 2.0, birds[2]);
  add('duck', 3, -2); add('duck', 6, 2.5);
  const sw = add('swan', 1, 2.5); add('swan', 2.3, 3.4, sw);
  let t = 0, food = null, foodT = 0, sparkle = 0;
  const callTo = (x, z, secs) => { food = [x, z]; foodT = secs; };
  g.userData.setUse = (v, u) => { if (v && u) callTo(u.x - g.position.x, u.z - g.position.z, 2); };
  g.userData.touchKind = 'lake';
  g.userData.touch = (pt) => {
    const x = pt ? pt.x - g.position.x : 0, z = pt ? pt.z - g.position.z : 0;
    ripple(x, z); ripple(x + 0.4, z - 0.2); callTo(x, z, 9);
  };
  g.userData.tick = (dt) => {
    t += dt; sparkle -= dt;
    foodT = Math.max(0, foodT - dt); if (foodT <= 0) food = null;
    wm.emissiveIntensity = 0.26 + Math.sin(t * 0.8) * 0.05;
    if (sparkle <= 0) { sparkle = 0.8 + r() * 1.6; const a = r() * 6.28, k = r() * 0.8; ripple(Math.cos(a) * rx * k, Math.sin(a) * rz * k); }
    for (const q of rings) if (q.life > 0) { q.life -= dt * 0.55; const e = 1 - q.life; q.m.scale.set(0.2 + e * 1.1, 0.2 + e * 1.1, 1); q.m.material.opacity = Math.max(0, q.life) * 0.4; }
    for (const b of birds) {
      if (b.lead) { const f = Math.sin(b.lead.h), c = Math.cos(b.lead.h); b.tx = b.lead.x - f * 0.65; b.tz = b.lead.z - c * 0.65; }
      else if (food) { const k = b.kind === 'swan' ? 1.8 : 1.2, a = birds.indexOf(b) * 2.1; b.tx = food[0] + Math.cos(a) * k; b.tz = food[1] + Math.sin(a) * k; }
      else if ((b.wait -= dt) <= 0) { b.wait = 5 + r() * 9; const a = r() * 6.28, k = 0.2 + r() * 0.55; b.tx = Math.cos(a) * rx * k; b.tz = Math.sin(a) * rz * k; }
      if (!inside(b.tx, b.tz, 0.88)) { const q = Math.hypot(b.tx / (rx * 0.86), b.tz / (rz * 0.86)); b.tx /= q; b.tz /= q; }
      const dx = b.tx - b.x, dz = b.tz - b.z, d = Math.hypot(dx, dz);
      if (d > 0.08) {
        let dh = Math.atan2(dx, dz) - b.h; dh = Math.atan2(Math.sin(dh), Math.cos(dh));
        b.h += dh * Math.min(1, dt * 2.4);
        const sp = (b.kind === 'swan' ? 0.55 : 0.7) * Math.min(1, d) * (food ? 1.6 : 1);
        b.x += Math.sin(b.h) * sp * dt; b.z += Math.cos(b.h) * sp * dt;
      }
      b.o.position.set(b.x, 0.05 + Math.sin(t * 2 + b.x) * 0.012, b.z);
      b.o.rotation.y = b.h;
    }
  };
  return g;
}

function dock(s) {
  const g = new THREE.Group();
  const len = s.len || 3;
  for (let i = 0; i < Math.round(len / 0.34); i++) g.add(box(1.3, 0.07, 0.3, i % 2 ? '#a57c52' : '#b58c60', 0, 0.22, -len / 2 + 0.17 + i * 0.34));
  for (const sx of [-1, 1]) for (const k of [-0.48, 0.48]) g.add(box(0.1, 0.4, 0.1, '#6e4a33', sx * 0.55, -0.05, k * len));
  return g;
}

// ---------------------------------------------------------------- 住户自己添的小东西
function book_pile() { const g = new THREE.Group(); ['#c0504a', '#3e6fb5', '#e3b23c', '#5d9b6a'].forEach((c, i) => { const b = box(0.46 - i * 0.04, 0.09, 0.34, c, 0, i * 0.09, 0); b.rotation.y = i * 0.25; g.add(b); }); return g; }
function recipe() { const g = new THREE.Group(); g.add(box(0.5, 0.42, 0.38, WOOD, 0, 0, 0), box(0.4, 0.05, 0.3, '#f3e6c8', 0, 0.42, 0)); return g; }
function flower() { const g = new THREE.Group(); const p = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.15, 0.3, 8), mat('#d98a6a')); p.position.y = 0.15; g.add(p); g.add(bar([0, 0.3, 0], [0, 0.85, 0], 0.025, '#5e8a44')); ['#ef8fb1', '#f6c84c', '#ef8fb1', '#f6c84c', '#ef8fb1'].forEach((c, i) => { const m = new THREE.Mesh(new THREE.IcosahedronGeometry(0.1, 0), mat(c)); const a = i * 1.26; m.position.set(Math.cos(a) * 0.14, 0.88, Math.sin(a) * 0.14); g.add(m); }); return g; }
function painting() { const g = new THREE.Group(); g.add(box(0.8, 0.8, 0.05, WOOD_D, 0, 0.04, 0), box(0.68, 0.68, 0.02, '#8fc2dc', 0, 0.1, 0.03), box(0.68, 0.24, 0.02, '#6f9a4f', 0, 0.1, 0.045)); return g; }
function sheet() { const g = new THREE.Group(); g.add(bar([0, 0, 0], [0, 0.9, 0], 0.025, METAL), box(0.45, 0.04, 0.3, METAL, 0, 0, 0), box(0.5, 0.42, 0.03, '#f6f1e6', 0, 0.75, 0.02)); return g; }
function plush_duck() { const g = new THREE.Group(); const b = bird('duckling'); b.scale.setScalar(2.3); g.add(b); return g; }
function fish_trophy() { const g = new THREE.Group(); g.add(box(0.75, 0.46, 0.05, WOOD, 0, 0.1, 0)); const f = new THREE.Mesh(new THREE.SphereGeometry(0.18, 8, 6), mat('#6fa8c9')); f.scale.set(1.6, 0.7, 0.3); f.position.set(0, 0.33, 0.04); g.add(f); return g; }
function dumbbell() { const g = new THREE.Group(); for (const z of [-0.16, 0.16]) { g.add(box(0.42, 0.05, 0.05, METAL, 0, 0.07, z), box(0.1, 0.16, 0.16, '#3a3c48', -0.2, 0, z), box(0.1, 0.16, 0.16, '#3a3c48', 0.2, 0, z)); } return g; }
function poster() { const g = new THREE.Group(); g.add(box(0.72, 1.0, 0.04, '#2f3f6e', 0, 0.03, 0), box(0.4, 0.4, 0.02, '#efc24a', 0, 0.45, 0.025)); return g; }
function photo() { const g = new THREE.Group(); g.add(box(0.36, 0.44, 0.04, WOOD_L, 0, 0, 0), box(0.28, 0.34, 0.02, '#e9d9bf', 0, 0.05, 0.02)); g.rotation.x = -0.12; return g; }
function cat_toy() { const g = new THREE.Group(); g.add(bar([0, 0, 0], [0.3, 0.7, 0], 0.015, WOOD)); const b = new THREE.Mesh(new THREE.IcosahedronGeometry(0.09, 0), mat('#d9574a')); b.position.set(0.3, 0.72, 0); g.add(b); g.add(box(0.26, 0.05, 0.26, WOOD_L, 0, 0, 0)); return g; }

function unknown(s) {
  return box(s.w || 0.8, s.h || 0.6, s.d || 0.8, s.color || '#9a97a6');
}

export const FURNITURE = {
  chair, desk, bed, shelf, bookshelf, sofa, armchair, table, coffee_table, rug, mat: mat_, lamp, plant, cabinet, fridge, counter, tv, beanbag, boxes,
  swing, seesaw, slide, carousel, sandbox, bench, lamp_post, fence,
  piano, easel, chess, cat, lake, dock, book_pile, recipe, flower, painting, sheet, plush_duck, fish_trophy, dumbbell, poster, photo, cat_toy,
};

export function buildFurniture(spec) {
  const fn = FURNITURE[spec.type] || unknown;
  const g = fn(spec);
  g.position.x = spec.x; g.position.z = spec.z;
  g.rotation.y = spec.rot != null ? (spec.rot * Math.PI) / 180 : faceAngle(spec.face);
  g.userData.type = spec.type;
  return g;
}
