// 农场的家具：路、田、牲口圈、农机、粮仓、筒仓、风车、农机棚、稻草人、草垛。
// 载入时登记进 FURNITURE。田和圈的样子跟着服务器发来的农场状态变（World.setFarm 调 setStage / setPen），
// 农机是可以坐的 ride：人坐上去、又有活（setWork）时，它沿主路和田间的缝开到地里来回跑，人下来它自己开回棚里。
import * as THREE from 'three';
import { FURNITURE, box, mat, bar, makeRide, anchor, SEAT_DROP, faceAngle } from './furniture.js';

const rnd = (seed) => { let n = seed; return () => ((n = (n * 16807) % 2147483647) / 2147483647); };
const lerp = (a, b, t) => a + (b - a) * t;
const clamp01 = (v) => Math.max(0, Math.min(1, v));
const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
const dummy = new THREE.Object3D();

// ---------------------------------------------------------------- 路
function road(s) {
  const g = new THREE.Group(), w = s.w || 3, pts = s.pts || [];
  const y = 0.006 + w * 0.002;              // 宽的路略高一点，交叉的地方不闪
  for (let i = 0; i + 1 < pts.length; i++) {
    const [a, b] = [pts[i], pts[i + 1]], len = Math.hypot(b[0] - a[0], b[1] - a[1]), ang = -Math.atan2(b[1] - a[1], b[0] - a[0]);
    const seg = new THREE.Mesh(new THREE.BoxGeometry(len + w, 0.02, w), mat('#b49a6c'));
    seg.position.set((a[0] + b[0]) / 2, y, (a[1] + b[1]) / 2); seg.rotation.y = ang; seg.receiveShadow = true;
    g.add(seg);
    if (w >= 2.8) {                          // 宽路上压出两道车辙
      for (const k of [-1, 1]) {
        const r = new THREE.Mesh(new THREE.BoxGeometry(len + w * 0.6, 0.02, 0.32), mat('#9d855c'));
        r.position.set((a[0] + b[0]) / 2 - Math.sin(ang) * k * w * 0.24, y + 0.004, (a[1] + b[1]) / 2 - Math.cos(ang) * k * w * 0.24);
        r.rotation.y = ang; r.receiveShadow = true; g.add(r);
      }
    }
  }
  return g;
}

// ---------------------------------------------------------------- 田
// 每种作物：株距、几部分（茎、叶、穗/棒子/花），每部分在各生长阶段的颜色
const CROP3D = {
  rice: { gap: 0.46, parts: [
    { geo: () => new THREE.ConeGeometry(0.09, 0.85, 5), y: 0.42, h: 0.85, col: ['#7fbf5a', '#6aa84f', '#c9b45a'] },
    { geo: () => new THREE.BoxGeometry(0.05, 0.22, 0.05), y: 0.78, h: 0.22, tilt: 0.7, from: 0.72, col: ['#9fca6a', '#9fca6a', '#e0bf55'] },
  ] },
  wheat: { gap: 0.4, parts: [
    { geo: () => new THREE.BoxGeometry(0.035, 0.9, 0.035), y: 0.45, h: 0.9, col: ['#86c25e', '#73b052', '#d6b45c'] },
    { geo: () => new THREE.BoxGeometry(0.07, 0.17, 0.07), y: 0.95, h: 0.17, from: 0.65, col: ['#9ccc6c', '#a5c464', '#e8c35e'] },
  ] },
  corn: { gap: 0.72, shadow: true, parts: [
    { geo: () => new THREE.BoxGeometry(0.08, 2.1, 0.08), y: 1.05, h: 2.1, col: ['#7bbb55', '#5f9f45', '#b9a457'] },
    { geo: () => new THREE.BoxGeometry(0.75, 0.02, 0.14), y: 1.0, h: 0.02, leaf: true, col: ['#86c45c', '#6aa84f', '#c2ad5c'] },
    { geo: () => new THREE.BoxGeometry(0.75, 0.02, 0.14), y: 1.55, h: 0.02, leaf: true, turn: 1.4, col: ['#86c45c', '#6aa84f', '#c2ad5c'] },
    { geo: () => new THREE.BoxGeometry(0.12, 0.3, 0.12), y: 1.25, h: 0.3, off: 0.1, from: 0.6, col: ['#8fc263', '#8fc263', '#efc24a'] },
  ] },
  potato: { gap: 0.62, rows: true, parts: [
    { geo: () => new THREE.IcosahedronGeometry(0.3, 0), y: 0.2, h: 0.4, bush: true, col: ['#76b958', '#5e9f48', '#a8a457'] },
    { geo: () => new THREE.IcosahedronGeometry(0.06, 0), y: 0.5, h: 0.06, from: 0.62, upto: 0.95, col: ['#f6f3ea', '#f6f3ea', '#f6f3ea'] },
  ] },
};
const SOIL = { stubble: '#9a8058', plowed: '#5d4330', sown: '#634734', sprout: '#5f4532', growing: '#5f4532', ripe: '#6a5038' };

function field(s) {
  const g = new THREE.Group(), w = s.w || 12, d = s.d || 10, crop = CROP3D[s.crop] || CROP3D.wheat;
  const rim = '#8b7a4e';
  g.add(box(w, 0.2, 0.35, rim, 0, 0, -d / 2 + 0.17), box(w, 0.2, 0.35, rim, 0, 0, d / 2 - 0.17),
    box(0.35, 0.2, d - 0.7, rim, -w / 2 + 0.17, 0, 0), box(0.35, 0.2, d - 0.7, rim, w / 2 - 0.17, 0, 0));
  const soilMat = new THREE.MeshStandardMaterial({ color: SOIL.growing, roughness: 1, flatShading: true });
  const soil = new THREE.Mesh(new THREE.BoxGeometry(w - 0.7, 0.1, d - 0.7), soilMat);
  soil.position.y = 0.05; soil.receiveShadow = true; g.add(soil);
  // 垄沟
  const iw = w - 1.0, id = d - 1.0, rows = Math.floor(id / 0.55);
  const furrowMat = new THREE.MeshStandardMaterial({ color: '#4a3424', roughness: 1, flatShading: true });
  const furrows = new THREE.InstancedMesh(new THREE.BoxGeometry(iw, 0.07, 0.2), furrowMat, rows);
  for (let i = 0; i < rows; i++) { dummy.position.set(0, 0.12, -id / 2 + 0.27 + i * 0.55); dummy.rotation.set(0, 0, 0); dummy.scale.set(1, 1, 1); dummy.updateMatrix(); furrows.setMatrixAt(i, dummy.matrix); }
  furrows.receiveShadow = true; g.add(furrows);
  // 稻田里的水
  let water = null;
  if (s.crop === 'rice') {
    water = new THREE.Mesh(new THREE.PlaneGeometry(w - 0.8, d - 0.8), new THREE.MeshStandardMaterial({ color: '#6fb3cf', transparent: true, opacity: 0.55, roughness: 0.15, metalness: 0.1 }));
    water.rotation.x = -Math.PI / 2; water.position.y = 0.17; g.add(water);
  }
  // 作物：每块地一套 InstancedMesh
  const r = rnd(Math.round(Math.abs(s.x * 37 + s.z * 11)) + 5);
  const spots = [];
  const gap = crop.gap;
  for (let z = -id / 2 + gap / 2; z < id / 2; z += crop.rows ? 0.55 * Math.round(gap / 0.55 + 0.4) : gap) {
    for (let x = -iw / 2 + gap / 2; x < iw / 2; x += gap) {
      spots.push({ x: x + (r() - 0.5) * gap * 0.35, z: z + (crop.rows ? 0 : (r() - 0.5) * gap * 0.35), k: 0.85 + r() * 0.3, a: r() * Math.PI * 2 });
    }
  }
  const parts = crop.parts.map((p) => {
    const m = new THREE.MeshStandardMaterial({ color: p.col[0], roughness: 0.9, flatShading: true });
    const mesh = new THREE.InstancedMesh(p.geo(), m, spots.length);
    mesh.castShadow = !!crop.shadow && !p.leaf; mesh.receiveShadow = false;
    g.add(mesh);
    return { p, mesh, m };
  });
  const colAt = (cols, ripe, f) => (ripe ? cols[2] : f < 0.75 ? cols[0] : cols[1]);
  const tmp = new THREE.Color(), dryCol = new THREE.Color('#b7a26a');
  let last = '';
  g.userData.setStage = (plot) => {
    const st = plot?.stage || 'growing', f = plot?.progress ?? 0.6, dry = !!plot?.dry;
    const key = `${st}|${f.toFixed(2)}|${dry}`;
    if (key === last) return;
    last = key;
    soilMat.color.set(dry ? '#8d7253' : SOIL[st] || SOIL.growing);
    furrows.visible = st !== 'stubble';
    if (water) water.visible = ['sown', 'sprout', 'growing'].includes(st);
    const ripe = st === 'ripe', stub = st === 'stubble';
    // 长到多高：出苗 0.15 → 长高 1
    const grow = stub ? 0.12 : st === 'sown' ? 0 : st === 'sprout' ? lerp(0.12, 0.38, clamp01((f - 0.12) / 0.28)) : ripe ? 1 : lerp(0.4, 1, clamp01((f - 0.4) / 0.6));
    for (const { p, mesh, m } of parts) {
      const show = grow > 0 && !(stub && (p !== crop.parts[0] || s.crop === 'potato')) && (p.from == null || f >= p.from || ripe) && (p.upto == null || (f < p.upto && !ripe));
      mesh.visible = show;
      if (!show) continue;
      tmp.set(stub ? '#c9b47a' : colAt(p.col, ripe, f));
      if (dry && !stub) tmp.lerp(dryCol, 0.45);
      m.color.copy(tmp);
      spots.forEach((q, i) => {
        const k = q.k * (p.bush ? Math.max(grow, 0.3) : grow);
        if (p.bush) {
          dummy.position.set(q.x, p.y * k + 0.1, q.z); dummy.rotation.set(0, q.a, 0); dummy.scale.set(k * 1.1, k * 0.8, k * 1.1);
        } else if (p.leaf) {
          dummy.position.set(q.x, 0.1 + p.y * k, q.z); dummy.rotation.set(0, q.a + (p.turn || 0), ripe ? -0.35 : -0.15); dummy.scale.set(k, 1, 1);
        } else if (p === crop.parts[0]) {
          dummy.position.set(q.x, 0.1 + p.y * k, q.z); dummy.rotation.set((q.k - 1) * 0.3, q.a, (q.k - 1) * 0.3); dummy.scale.set(Math.max(0.5, k), k, Math.max(0.5, k));
        } else {
          const lean = p.tilt && ripe ? p.tilt : 0;
          dummy.position.set(q.x + (p.off || 0) * Math.cos(q.a), 0.1 + p.y * k * crop.parts[0].h / crop.parts[0].h, q.z + (p.off || 0) * Math.sin(q.a));
          dummy.rotation.set(lean * Math.cos(q.a), q.a, lean * Math.sin(q.a)); dummy.scale.setScalar(Math.max(0.6, k));
        }
        dummy.updateMatrix(); mesh.setMatrixAt(i, dummy.matrix);
      });
      mesh.instanceMatrix.needsUpdate = true;
    }
  };
  g.userData.setStage(null);
  g.userData.plot = s.plot;
  g.userData.touchKind = 'farm'; g.userData.farmRef = s.plot; g.userData.touch = () => {};
  return g;
}

// ---------------------------------------------------------------- 牲口
function cowMesh() {
  const g = new THREE.Group();
  const body = box(0.7, 0.6, 1.3, '#f4f1ea', 0, 0.55, 0); g.add(body);
  for (const [x, y, z, w, h, d] of [[0.2, 0.9, 0.2, 0.32, 0.22, 0.4], [-0.25, 0.75, -0.35, 0.22, 0.3, 0.3], [0.36, 0.7, -0.1, 0.02, 0.25, 0.3]]) g.add(box(w, h, d, '#2c2a30', x, y - h / 2 + 0.1, z));
  for (const [x, z] of [[-0.24, 0.45], [0.24, 0.45], [-0.24, -0.45], [0.24, -0.45]]) g.add(box(0.14, 0.55, 0.14, '#f4f1ea', x, 0, z));
  const head = new THREE.Group(); head.position.set(0, 0.95, 0.68); g.add(head);
  head.add(box(0.42, 0.38, 0.42, '#f4f1ea', 0, -0.2, 0.08), box(0.36, 0.18, 0.12, '#e8a9a0', 0, -0.25, 0.32), box(0.08, 0.12, 0.08, '#e9dfc9', -0.18, 0.15, 0), box(0.08, 0.12, 0.08, '#e9dfc9', 0.18, 0.15, 0));
  return { g, head, speed: 0.35, bob: 0.5 };
}
function sheepMesh() {
  const g = new THREE.Group();
  const wool = new THREE.Mesh(new THREE.IcosahedronGeometry(0.42, 0), mat('#f2efe6')); wool.scale.set(0.9, 0.75, 1.15); wool.position.y = 0.6; wool.castShadow = true; g.add(wool);
  for (const [x, z] of [[-0.18, 0.25], [0.18, 0.25], [-0.18, -0.25], [0.18, -0.25]]) g.add(box(0.08, 0.38, 0.08, '#3a3640', x, 0, z));
  const head = new THREE.Group(); head.position.set(0, 0.72, 0.42); g.add(head);
  head.add(box(0.22, 0.24, 0.3, '#3a3640', 0, -0.12, 0.08), box(0.1, 0.05, 0.14, '#3a3640', -0.15, 0.02, 0), box(0.1, 0.05, 0.14, '#3a3640', 0.15, 0.02, 0));
  return { g, head, speed: 0.45, bob: 0.4, wool };
}
function chickenMesh(i) {
  const g = new THREE.Group();
  const c = i % 5 === 0 ? '#c9804a' : '#faf8f2';
  const body = new THREE.Mesh(new THREE.SphereGeometry(0.16, 8, 6), mat(c)); body.scale.set(0.9, 0.85, 1.15); body.position.y = 0.2; body.castShadow = true; g.add(body);
  g.add(box(0.03, 0.12, 0.03, '#e8a13a', -0.05, 0, 0), box(0.03, 0.12, 0.03, '#e8a13a', 0.05, 0, 0));
  const head = new THREE.Group(); head.position.set(0, 0.34, 0.14); g.add(head);
  const hb = new THREE.Mesh(new THREE.SphereGeometry(0.08, 7, 5), mat(c)); head.add(hb);
  head.add(box(0.03, 0.06, 0.07, '#d9463a', 0, 0.05, 0), box(0.04, 0.03, 0.06, '#e8a13a', 0, -0.03, 0.08));
  return { g, head, speed: 0.6, bob: 1.2, peck: true };
}

function pen(s) {
  const g = new THREE.Group(), w = s.w || 10, d = s.d || 8, kind = s.kind || 'cow';
  const gate = s.gate || 'n', at = s.gate_at || 0, GAP = 2.4;
  // 栅栏：四面，门那面留个口
  const side = (wall) => {
    const along = wall === 'n' || wall === 's', len = along ? w : d;
    const fx = wall === 'e' ? w / 2 : wall === 'w' ? -w / 2 : 0, fz = wall === 's' ? d / 2 : wall === 'n' ? -d / 2 : 0;
    const segs = wall === gate ? [[-len / 2, at - GAP / 2], [at + GAP / 2, len / 2]] : [[-len / 2, len / 2]];
    for (const [a, b] of segs) {
      if (b - a < 0.2) continue;
      const n = Math.max(1, Math.round((b - a) / 1.6));
      for (let i = 0; i <= n; i++) { const t = a + ((b - a) * i) / n; g.add(box(0.12, 0.95, 0.12, '#8a6440', along ? t : fx, 0, along ? fz : t)); }
      for (const y of [0.38, 0.75]) g.add(along ? box(b - a, 0.07, 0.06, '#a77c52', (a + b) / 2, y, fz) : box(0.06, 0.07, b - a, '#a77c52', fx, y, (a + b) / 2));
    }
  };
  ['n', 's', 'e', 'w'].forEach(side);
  // 棚子，放在东北角
  const sw = kind === 'cow' ? 6 : 4.2, sd = kind === 'cow' ? 4 : 3, sx = w / 2 - sw / 2 - 0.4, sz = -d / 2 + sd / 2 + 0.4;
  if (kind === 'chicken') {
    g.add(box(sw, 1.5, sd, '#d9b48a', sx, 0.3, sz));
    for (let i = 0; i < 6; i++) g.add(box(0.12, 0.3, 0.12, '#6e4a33', sx + (i % 3 - 1) * (sw / 2 - 0.2), 0, sz + (i < 3 ? -1 : 1) * (sd / 2 - 0.2)));
    const roof = box(sw + 0.5, 0.1, sd + 0.6, '#b5473a', sx, 1.95, sz); roof.rotation.x = 0.18; g.add(roof);
    g.add(box(0.5, 0.6, 0.06, '#5a3a28', sx - 1, 0.6, sz + sd / 2 + 0.01));
    const ramp = box(0.5, 0.05, 1.1, '#a77c52', sx - 1, 0.25, sz + sd / 2 + 0.5); ramp.rotation.x = 0.45; g.add(ramp);
  } else {
    for (const [px, pz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) g.add(box(0.14, 2.2, 0.14, '#6e4a33', sx + px * (sw / 2 - 0.1), 0, sz + pz * (sd / 2 - 0.1)));
    g.add(box(sw, 1.4, 0.1, '#a3623f', sx, 0, sz - sd / 2 + 0.05));
    const roof = box(sw + 0.6, 0.12, sd + 0.8, kind === 'cow' ? '#8e4a36' : '#6f7b88', sx, 2.2, sz); roof.rotation.x = -0.12; g.add(roof);
    g.add(box(sw - 0.4, 0.25, sd - 0.4, '#e3c27a', sx, 0, sz));       // 地上铺的草
  }
  // 食槽，靠门
  const gx = gate === 'n' || gate === 's' ? at : gate === 'e' ? w / 2 - 1.3 : -w / 2 + 1.3;
  const gz = gate === 'n' ? -d / 2 + 1.3 : gate === 's' ? d / 2 - 1.3 : at;
  const tx = gate === 'n' || gate === 's' ? gx + 1.6 : gx, tz = gate === 'n' || gate === 's' ? gz : gz + 1.6;
  const turned = gate === 'e' || gate === 'w';
  g.add(box(turned ? 0.6 : 1.8, 0.45, turned ? 1.8 : 0.6, '#7a5238', tx, 0, tz));
  const fodder = box(turned ? 0.45 : 1.6, 0.06, turned ? 1.6 : 0.45, '#d8c06a', tx, 0.42, tz); g.add(fodder);
  // 牲口
  const n = s.count || 6, r = rnd(Math.round(w * 13 + d * 7 + n) + 3), herd = [];
  const lim = [-w / 2 + 0.8, -d / 2 + 0.8, w / 2 - 0.8, d / 2 - 0.8];
  for (let i = 0; i < n; i++) {
    const a = kind === 'cow' ? cowMesh() : kind === 'sheep' ? sheepMesh() : chickenMesh(i);
    a.x = lerp(lim[0], lim[2], r()); a.z = lerp(lim[1], lim[3], r()); a.h = r() * 6.28; a.tx = a.x; a.tz = a.z; a.wait = r() * 4; a.t = r() * 10;
    a.g.position.set(a.x, 0, a.z); g.add(a.g); herd.push(a);
  }
  let crowdUntil = 0, lastFed = 0, hungry = false;
  g.userData.touchKind = 'farm'; g.userData.farmRef = s.pen; g.userData.touch = () => {};
  g.userData.setPen = (st) => {
    if (!st) return;
    hungry = !!st.hungry;
    fodder.visible = !hungry;
    if (lastFed && st.fed_ts > lastFed + 1) crowdUntil = performance.now() + 45000;     // 刚喂过：都挤到食槽边
    lastFed = st.fed_ts || lastFed;
  };
  g.userData.tick = (dt) => {
    const crowd = performance.now() < crowdUntil;
    for (const [i, a] of herd.entries()) {
      a.t += dt;
      if (crowd) { const ang = i * 2.4; a.tx = tx + Math.cos(ang) * (0.7 + (i % 3) * 0.35) * (turned ? 1 : 1.6); a.tz = tz + Math.sin(ang) * (0.7 + (i % 3) * 0.35) * (turned ? 1.6 : 1); }
      else if ((a.wait -= dt) <= 0) { a.wait = 4 + r() * 10; a.tx = lerp(lim[0], lim[2], r()); a.tz = lerp(lim[1], lim[3], r()); }
      a.tx = Math.max(lim[0], Math.min(lim[2], a.tx)); a.tz = Math.max(lim[1], Math.min(lim[3], a.tz));
      const dx = a.tx - a.x, dz = a.tz - a.z, dist = Math.hypot(dx, dz);
      let moving = false;
      if (dist > 0.15) {
        const dh = wrap(Math.atan2(dx, dz) - a.h); a.h += dh * Math.min(1, dt * 2);
        const sp = a.speed * Math.min(1, dist) * (Math.abs(dh) < 1 ? 1 : 0.3);
        a.x += Math.sin(a.h) * sp * dt; a.z += Math.cos(a.h) * sp * dt; moving = sp > 0.05;
      }
      a.g.position.set(a.x, moving ? Math.abs(Math.sin(a.t * 8)) * 0.03 : 0, a.z);
      a.g.rotation.y = a.h;
      a.head.rotation.x = moving ? 0 : a.peck ? Math.max(0, Math.sin(a.t * 3 + i)) * 0.9 : 0.25 + Math.sin(a.t * a.bob + i) * 0.25;
    }
  };
  return g;
}

// ---------------------------------------------------------------- 农机
const PAINT = { tractor: '#3f8a4c', seeder: '#3f6fb5', sprayer: '#d9762f', combine: '#d9b23a', digger: '#b5473a', truck: '#4f7fb0' };

function wheel(r, wdt, x, y, z) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, wdt, 14), mat('#2b2a30'));
  m.rotation.z = Math.PI / 2; m.position.set(x, y, z); m.castShadow = true;
  const hub = new THREE.Mesh(new THREE.CylinderGeometry(r * 0.45, r * 0.45, wdt + 0.02, 8), mat('#d9c25a'));
  hub.rotation.z = Math.PI / 2; hub.position.copy(m.position);
  const spin = new THREE.Group(); spin.position.set(x, y, z); m.position.set(0, 0, 0); hub.position.set(0, 0, 0);
  spin.add(m, hub); spin.userData.r = r;
  return spin;
}

// 拖拉机车头，seeder / sprayer / digger 都用它拉东西
function tractorBody(g, color, wheels) {
  g.add(box(1.1, 0.45, 2.3, color, 0, 0.45, 0.05));
  g.add(box(0.85, 0.55, 1.1, color, 0, 0.9, 0.6));
  g.add(box(0.9, 0.06, 1.12, '#2b2a30', 0, 1.45, 0.6));
  g.add(box(0.7, 0.12, 0.1, '#f0e6b0', 0, 1.05, 1.16));
  for (const [x, z] of [[-0.55, -0.15], [0.55, -0.15], [-0.55, -1.0], [0.55, -1.0]]) g.add(box(0.06, 1.45, 0.06, '#2b2a30', x, 0.9, z));
  g.add(box(1.3, 0.08, 1.15, color, 0, 2.35, -0.58));
  g.add(box(0.55, 0.12, 0.5, '#2b2a30', 0, 1.0, -0.55), box(0.55, 0.45, 0.08, '#2b2a30', 0, 1.1, -0.82));
  g.add(bar([0.3, 1.4, 0.95], [0.3, 2.3, 0.95], 0.05, '#55535e'));
  wheels.push(wheel(0.68, 0.42, -0.78, 0.68, -0.55), wheel(0.68, 0.42, 0.78, 0.68, -0.55), wheel(0.42, 0.28, -0.68, 0.42, 0.95), wheel(0.42, 0.28, 0.68, 0.42, 0.95));
  return { seatY: 1.12, seatZ: -0.55, pipe: [0.3, 2.35, 0.95] };
}

function machine(s) {
  const g = new THREE.Group(), kind = s.kind || 'tractor', color = PAINT[kind] || '#3f8a4c';
  const body = new THREE.Group(); g.add(body);
  const wheels = [];
  let seat, spinner = null, mist = null, cargo = null, len = 3;
  if (kind === 'combine') {
    body.add(box(2.6, 1.6, 4.2, color, 0, 0.7, -0.3));
    body.add(box(2.2, 0.9, 1.6, '#c9a12f', 0, 2.3, -1.2));                     // 粮箱
    body.add(box(1.6, 1.2, 1.4, '#cfe3ea', 0, 2.3, 0.95, { transparent: true, opacity: 0.35, depthWrite: false }), box(1.7, 0.1, 1.5, color, 0, 3.5, 0.95));
    body.add(box(1.6, 0.12, 1.4, '#55535e', 0, 2.2, 0.95));
    body.add(bar([1.1, 2.9, -1.6], [2.3, 3.0, 0.2], 0.12, '#8a8fa3'));          // 卸粮管
    body.add(box(3.8, 0.35, 1.1, '#b8952c', 0, 0.35, 2.4));                     // 割台
    const reel = new THREE.Group(); reel.position.set(0, 1.15, 2.55); body.add(reel);
    for (let i = 0; i < 6; i++) { const a = (i / 6) * Math.PI * 2; reel.add(box(3.6, 0.05, 0.05, '#d94f3a', 0, Math.sin(a) * 0.45 - 0.025, Math.cos(a) * 0.45)); }
    reel.add(bar([-1.8, 0, 0], [1.8, 0, 0], 0.05, '#8a8fa3'));
    spinner = reel;
    wheels.push(wheel(0.85, 0.5, -1.35, 0.85, 0.9), wheel(0.85, 0.5, 1.35, 0.85, 0.9), wheel(0.55, 0.36, -1.25, 0.55, -1.8), wheel(0.55, 0.36, 1.25, 0.55, -1.8));
    seat = { seatY: 2.25, seatZ: 0.9, pipe: [-0.9, 3.4, -0.4] };
    len = 5.4;
  } else if (kind === 'truck') {
    body.add(box(2.0, 1.4, 1.6, color, 0, 0.7, 1.5), box(1.9, 0.6, 0.05, '#cfe3ea', 0, 1.45, 2.31));
    body.add(box(2.1, 0.2, 3.6, '#55535e', 0, 0.7, -1.1));
    for (const x of [-1, 1]) body.add(box(0.06, 0.55, 3.6, '#7d8090', x * 1.02, 0.9, -1.1));
    body.add(box(2.1, 0.55, 0.06, '#7d8090', 0, 0.9, -2.88));
    cargo = new THREE.Group(); body.add(cargo);
    for (let i = 0; i < 12; i++) cargo.add(box(0.5, 0.32, 0.75, '#d9c08a', -0.6 + (i % 3) * 0.6, 0.9 + Math.floor(i / 6) * 0.32, -2.3 + (Math.floor(i / 3) % 2) * 0.85 + (i >= 6 ? 0.4 : 0)));
    cargo.visible = false;
    wheels.push(wheel(0.48, 0.32, -0.95, 0.48, 1.4), wheel(0.48, 0.32, 0.95, 0.48, 1.4), wheel(0.48, 0.32, -0.95, 0.48, -1.9), wheel(0.48, 0.32, 0.95, 0.48, -1.9));
    seat = { seatY: 1.15, seatZ: 1.4, pipe: [0.85, 1.9, 0.6] };
    len = 4.8;
  } else {
    seat = tractorBody(body, color, wheels);
    if (kind === 'tractor') {                 // 后面挂犁
      body.add(box(1.8, 0.12, 0.2, '#55535e', 0, 0.5, -1.65), bar([0, 0.55, -1.0], [0, 0.55, -1.6], 0.05, '#55535e'));
      for (let i = 0; i < 4; i++) { const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.04, 12), mat('#9a9db0')); disc.rotation.set(0.3, 0, Math.PI / 2 - 0.4); disc.position.set(-0.75 + i * 0.5, 0.28, -1.85 - (i % 2) * 0.15); body.add(disc); }
    } else if (kind === 'seeder') {           // 播种机：宽的种子箱
      body.add(box(2.8, 0.7, 0.8, '#e8c34a', 0, 0.55, -1.95), box(2.9, 0.08, 0.9, '#3f6fb5', 0, 1.25, -1.95));
      for (let i = 0; i < 6; i++) body.add(bar([-1.25 + i * 0.5, 0.55, -1.95], [-1.25 + i * 0.5, 0.08, -2.15], 0.025, '#55535e'));
    } else if (kind === 'sprayer') {          // 洒水车：水箱和喷杆
      const tank = new THREE.Mesh(new THREE.CylinderGeometry(0.75, 0.75, 1.8, 14), mat('#e8e6ee')); tank.rotation.x = Math.PI / 2; tank.position.set(0, 1.15, -2.0); tank.castShadow = true; body.add(tank);
      body.add(box(1.6, 0.12, 2.0, '#55535e', 0, 0.35, -2.0));
      wheels.push(wheel(0.45, 0.3, -0.85, 0.45, -2.2), wheel(0.45, 0.3, 0.85, 0.45, -2.2));
      body.add(box(6.5, 0.06, 0.06, '#7d8090', 0, 0.95, -2.95));
      mist = new THREE.Group(); body.add(mist);
      for (let i = 0; i < 9; i++) { const c = new THREE.Mesh(new THREE.ConeGeometry(0.32, 0.85, 8, 1, true), new THREE.MeshBasicMaterial({ color: '#d8eef8', transparent: true, opacity: 0.35, depthWrite: false })); c.position.set(-3 + i * 0.75, 0.52, -2.95); mist.add(c); }
      mist.visible = false;
    } else if (kind === 'digger') {           // 土豆收获机：带传送带的拖车
      body.add(box(1.7, 0.5, 2.4, '#c96a4a', 0, 0.45, -2.3));
      const belt = box(1.4, 0.06, 2.6, '#3a3640', 0, 0.95, -2.3); belt.rotation.x = -0.25; body.add(belt);
      body.add(box(1.8, 0.1, 0.4, '#8a8fa3', 0, 0.12, -3.5));
      wheels.push(wheel(0.42, 0.3, -0.95, 0.42, -2.0), wheel(0.42, 0.3, 0.95, 0.42, -2.0));
    }
  }
  wheels.forEach((w) => body.add(w));
  // 排气冒烟
  const puffs = [0, 1, 2, 3, 4, 5].map(() => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.16, 6, 5), new THREE.MeshBasicMaterial({ color: '#d6d4dc', transparent: true, opacity: 0, depthWrite: false })); body.add(m); return { m, life: 0 }; });
  let puffT = 0;

  // ---------- 开车
  const park = { x: s.x, z: s.z, yaw: faceAngle(s.face) };
  const st = { x: s.x, z: s.z, yaw: park.yaw, plan: [], mode: 'park', work: null, key: '', exit: [], loop: [], t: 0 };
  let room = { cx: 0, cz: 0 };
  const roadZ = () => room.cz + (s.road_z ?? 0);
  const gaps = () => (s.gaps || []).map((x) => room.cx + x);
  const gateAt = () => (s.gate ? [room.cx + s.gate[0], room.cz + s.gate[1]] : [park.x, roadZ()]);
  const P = (x, z, o = {}) => ({ x, z, ...o });

  function routeOut() {
    const rz = roadZ(), out = [P(park.x, rz)];
    if (st.work.job === 'sell') {
      const [gx, gz] = gateAt();
      out.push(P(gx, rz), P(gx, gz));
      st.exit = [P(gx, rz), P(park.x, rz), P(park.x, park.z, { rev: true })];
      st.loop = [];
      return out;
    }
    const [x0, z0, x1, z1] = st.work.rect, north = (z0 + z1) / 2 < rz, edge = north ? z1 : z0;
    const inX = x1 - 1.4;
    let path;
    if (Math.abs(edge - rz) < 4.5) path = [P(inX, rz)];
    else {
      const gx = gaps().reduce((b, x) => (Math.abs(x - x1) < Math.abs(b - x1) ? x : b), x1 + 1);
      const lane = edge + (north ? 1 : -1);
      path = [P(gx, rz), P(gx, lane), P(inX, lane)];
    }
    out.push(...path);
    // 一行一行来回开，间距 2.2 米，从靠路的那边开始
    const rows = [];
    for (let k = 0; ; k++) { const z = north ? edge - 1.1 - 2.2 * k : edge + 1.1 + 2.2 * k; if (z < z0 + 0.7 || z > z1 - 0.7) break; rows.push(z); }
    st.loop = [];
    rows.forEach((z, i) => { const a = i % 2 ? x0 + 1.4 : x1 - 1.4, b = i % 2 ? x1 - 1.4 : x0 + 1.4; st.loop.push(P(a, z), P(b, z)); });
    st.exit = [...path].reverse().concat([P(park.x, rz), P(park.x, park.z, { rev: true })]);
    return out.concat(st.loop);
  }

  function step(dt, speed) {
    const p = st.plan[0];
    if (!p) return 0;
    const dx = p.x - st.x, dz = p.z - st.z, dist = Math.hypot(dx, dz);
    if (dist < 0.25) { st.plan.shift(); return 0; }
    const h = p.rev ? Math.atan2(-dx, -dz) : Math.atan2(dx, dz), dh = wrap(h - st.yaw);
    st.yaw += Math.sign(dh) * Math.min(Math.abs(dh), dt * 1.6);
    const k = Math.max(0, Math.cos(dh)) ** 3;
    const mv = Math.min(dist, speed * k * dt);
    st.x += (dx / dist) * mv; st.z += (dz / dist) * mv;
    return p.rev ? -mv : mv;
  }

  const ride = makeRide(1, {
    update(dt) {
      const on = this.occ[0];
      st.t += dt;
      if (st.work && on && (st.mode === 'park' || st.mode === 'home' || st.replan)) { st.plan = routeOut(); st.mode = 'out'; st.replan = false; }
      else if (!on && (st.mode === 'out' || st.mode === 'work' || st.mode === 'wait')) { st.plan = st.exit.slice(); st.mode = 'home'; }
      else if (on && !st.work && st.mode !== 'park' && st.mode !== 'home') { st.plan = st.exit.slice(); st.mode = 'home'; }
      if (!st.plan.length) {
        if (st.mode === 'out' || st.mode === 'work') {
          if (st.loop.length) { st.loop.reverse(); st.plan = st.loop.slice(); st.mode = 'work'; } else st.mode = 'wait';
        } else if (st.mode === 'home') st.mode = 'park';
      }
      const fieldWork = st.mode === 'work' || (st.mode === 'out' && st.plan.length <= st.loop.length);
      const moved = st.mode === 'park' ? 0 : step(dt, fieldWork ? 1.7 : 3.4);
      if (st.mode === 'park') st.yaw += wrap(park.yaw - st.yaw) * Math.min(1, dt * 1.5);
      g.position.x = st.x; g.position.z = st.z; g.rotation.y = st.yaw;
      for (const w of wheels) w.rotation.x += moved / w.userData.r;
      if (spinner && fieldWork) spinner.rotation.x += dt * 2.6;
      if (mist) { mist.visible = fieldWork; mist.children.forEach((c, i) => { c.material.opacity = 0.22 + Math.sin(st.t * 9 + i) * 0.08; }); }
      if (cargo) cargo.visible = !!st.work && st.work.job === 'sell' && (st.mode === 'out' || (st.mode === 'wait' && st.t % 30 < 12));
      // 开着的时候冒烟
      puffT -= dt;
      if (Math.abs(moved) > 0 && puffT <= 0) { puffT = 0.35; const q = puffs.find((x) => x.life <= 0) || puffs[0]; q.life = 1; q.m.position.set(...seat.pipe); }
      for (const q of puffs) if (q.life > 0) { q.life -= dt * 0.8; q.m.position.y += dt * 0.8; q.m.scale.setScalar(1 + (1 - q.life) * 1.6); q.m.material.opacity = Math.max(0, q.life) * 0.5; }
      this.occ.fill(false);
    },
    yaw() { return st.yaw; },
    pose() { return 'sit'; },
  });
  ride.seats = [anchor(body, 0, seat.seatY - SEAT_DROP + 0.12, seat.seatZ)];
  g.userData.ride = ride;
  g.userData.setRoom = (r) => { room = { cx: (r.rect[0] + r.rect[2]) / 2, cz: (r.rect[1] + r.rect[3]) / 2 }; };
  // 服务器说这台车现在干什么：{ job, rect, key }，没活是 null
  g.userData.setWork = (w) => {
    const key = w ? w.key : '';
    if (key === st.key) return;
    st.key = key;
    st.work = w && (w.rect || w.job === 'sell') ? w : null;
    if (st.work && st.mode !== 'park' && st.mode !== 'home') st.replan = true;
  };
  g.userData.len = len;
  return g;
}

// ---------------------------------------------------------------- 房子和景
function barn(s) {
  const g = new THREE.Group(), w = s.w || 10, d = s.d || 8, H = 4.2;
  g.add(box(w, H, d, '#b5473a', 0, 0, 0));
  // 屋脊前后走向，山墙在南北两头，大门开在南边山墙上
  const RISE = 2.2, slope = Math.atan2(RISE, w / 2), half = Math.hypot(w / 2, RISE) + 0.35;
  for (const k of [-1, 1]) {
    const roof = box(half, 0.18, d + 0.7, '#5b4a48', 0, 0, 0);
    roof.geometry.translate(0, -0.09, 0);
    roof.position.set(k * (w / 4 + 0.08), H + RISE / 2 + 0.12, 0); roof.rotation.z = -k * slope; g.add(roof);
  }
  const gable = new THREE.Shape(); gable.moveTo(-w / 2, 0); gable.lineTo(w / 2, 0); gable.lineTo(0, 2.2); gable.lineTo(-w / 2, 0);
  for (const z of [-d / 2, d / 2 - 0.02]) { const m = new THREE.Mesh(new THREE.ExtrudeGeometry(gable, { depth: 0.02, bevelEnabled: false }), mat('#b5473a')); m.position.set(0, H, z); g.add(m); }
  g.add(box(3.4, 3.2, 0.08, '#8e3328', 0, 0, d / 2 + 0.01));
  g.add(bar([-1.6, 0.1, d / 2 + 0.07], [1.6, 3.1, d / 2 + 0.07], 0.06, '#f2efe6'), bar([1.6, 0.1, d / 2 + 0.07], [-1.6, 3.1, d / 2 + 0.07], 0.06, '#f2efe6'));
  g.add(box(3.5, 0.12, 0.12, '#f2efe6', 0, 3.2, d / 2 + 0.06), box(1.2, 1.0, 0.08, '#f2efe6', 0, H + 0.4, d / 2 + 0.03), box(1.0, 0.8, 0.09, '#3a3640', 0, H + 0.5, d / 2 + 0.04));
  return g;
}

function silo(s) {
  const g = new THREE.Group(), r = s.r || 2, h = s.h || 8;
  const c = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, 20), mat('#c9c6cf', { flatShading: false })); c.position.y = h / 2; c.castShadow = true; g.add(c);
  for (let y = 1.2; y < h; y += 1.6) { const ring = new THREE.Mesh(new THREE.CylinderGeometry(r + 0.04, r + 0.04, 0.12, 20), mat('#a3a0ab')); ring.position.y = y; g.add(ring); }
  const dome = new THREE.Mesh(new THREE.SphereGeometry(r, 20, 8, 0, Math.PI * 2, 0, Math.PI / 2), mat('#9a97a6', { flatShading: false })); dome.position.y = h; dome.castShadow = true; g.add(dome);
  for (let y = 0.3; y < h; y += 0.4) g.add(box(0.5, 0.04, 0.04, '#55535e', 0, y, r + 0.12));
  g.add(box(0.04, h, 0.04, '#55535e', -0.25, 0, r + 0.12), box(0.04, h, 0.04, '#55535e', 0.25, 0, r + 0.12));
  return g;
}

function windmill(s) {
  const g = new THREE.Group(), H = 9;
  for (const [x, z] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) g.add(bar([x * 1.1, 0, z * 1.1], [x * 0.25, H, z * 0.25], 0.07, '#8a8fa3'));
  for (let y = 2; y < H; y += 2.2) { const k = 1.1 - (y / H) * 0.85; for (const [a, b] of [[[-k, -k], [k, -k]], [[k, -k], [k, k]], [[k, k], [-k, k]], [[-k, k], [-k, -k]]]) g.add(bar([a[0], y, a[1]], [b[0], y, b[1]], 0.035, '#8a8fa3')); }
  const hub = new THREE.Group(); hub.position.set(0, H + 0.2, 0.45); g.add(hub);
  hub.add(box(0.3, 0.3, 0.5, '#d9574a', 0, -0.15, -0.2));
  for (let i = 0; i < 12; i++) { const b = box(0.32, 2.2, 0.03, '#f2efe6', 0, 0, 0.05); b.geometry.translate(0, 1.1, 0); b.position.y = 0; b.rotation.z = (i / 12) * Math.PI * 2; hub.add(b); }
  const tail = box(0.04, 1.0, 1.6, '#d9574a', 0, H - 0.3, -1.2); g.add(tail);
  let t = 0;
  g.userData.tick = (dt) => { t += dt; hub.rotation.z -= dt * (0.9 + Math.sin(t * 0.2) * 0.4); };
  return g;
}

function shed(s) {
  const g = new THREE.Group(), w = s.w || 20, d = s.d || 7, H = 3.6;
  g.add(box(w, 0.08, d, '#a9a6b2', 0, 0, 0));
  g.add(box(w, H, 0.15, '#8e9aa8', 0, 0, -d / 2 + 0.07));
  for (const x of [-w / 2 + 0.07, w / 2 - 0.07]) g.add(box(0.15, H, d, '#8e9aa8', x, 0, 0));
  for (let x = -w / 2 + 0.1; x <= w / 2; x += w / 6) g.add(box(0.16, H + 0.4, 0.16, '#55535e', x, 0, d / 2 - 0.1));
  const roof = box(w + 0.6, 0.12, d + 1.2, '#6f7b88', 0, H + 0.2, 0.1); roof.rotation.x = 0.1; g.add(roof);
  return g;
}

function scarecrow() {
  const g = new THREE.Group();
  g.add(box(0.08, 1.9, 0.08, '#6e4a33', 0, 0, 0), box(1.3, 0.07, 0.07, '#6e4a33', 0, 1.35, 0));
  g.add(box(0.55, 0.6, 0.25, '#4f86d9', 0, 1.0, 0), box(0.5, 0.25, 0.22, '#d9c08a', 0, 0.75, 0));
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.2, 8, 6), mat('#e8d4a8')); head.position.y = 1.85; g.add(head);
  const hat = new THREE.Mesh(new THREE.ConeGeometry(0.38, 0.32, 10), mat('#d9b45c')); hat.position.y = 2.1; g.add(hat);
  return g;
}

function hay() {
  const g = new THREE.Group();
  const m = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.6, 1.2, 14), mat('#e0c46a')); m.rotation.z = Math.PI / 2; m.position.y = 0.6; m.castShadow = true; g.add(m);
  for (const x of [-0.3, 0.3]) { const r = new THREE.Mesh(new THREE.CylinderGeometry(0.61, 0.61, 0.05, 14), mat('#c9a84f')); r.rotation.z = Math.PI / 2; r.position.set(x, 0.6, 0); g.add(r); }
  return g;
}

Object.assign(FURNITURE, { road, field, pen, machine, barn, silo, windmill, shed, scarecrow, hay });
