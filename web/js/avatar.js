// 3D Q版小人。外形全由住户配置里的 avatar 决定：
//   hair / hair_tip 头发颜色（发尾渐变色），eyes 瞳色，skin 肤色，outfit 裙子主色，outfit2 衬裙 / 袖子 / 围裙色，
//   accent 配件主色，bow 蝴蝶结颜色（不写用 accent），accents 配件列表。
// 配件登记在 ACCESSORIES 里，加一种配件 = 加一个函数 (ctx) => void，在 ctx.head / ctx.body 上挂东西。
import * as THREE from 'three';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';

const HEAD_Y = 1.18, HEAD_R = 0.33, HIP_Y = 0.28;

function M(color, opts = {}) {
  // 带一点自发光：夜里灯光暗的时候脸和衣服也看得清
  return new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0, flatShading: true, emissive: color, emissiveIntensity: 0.16, ...opts });
}
function mesh(geo, material, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(geo, material);
  m.position.set(x, y, z);
  m.castShadow = true;
  return m;
}

// ---------------------------------------------------------------- 配件
export const ACCESSORIES = {
  flower(c) {
    const g = new THREE.Group();
    const petal = M(c.accent);
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2;
      const p = mesh(new THREE.SphereGeometry(0.05, 6, 4), petal, 0, Math.sin(a) * 0.06, Math.cos(a) * 0.06);
      p.scale.set(0.5, 1, 1); g.add(p);
    }
    g.add(mesh(new THREE.SphereGeometry(0.035, 6, 4), M('#f2c14e'), 0.02, 0, 0));
    g.position.set(0.3, HEAD_Y + 0.2, 0.06);
    g.rotation.z = -0.3;
    c.head.add(g);
  },
  bow(c) {
    const color = c.spec.bow || c.accent;
    const g = new THREE.Group();
    const m = M(color);
    for (const s of [-1, 1]) {
      const loop = mesh(new THREE.ConeGeometry(0.07, 0.15, 4), m, s * 0.07, 0, 0);
      loop.rotation.z = s * Math.PI / 2; loop.scale.set(1, 1, 0.4); g.add(loop);
      const tail = mesh(new THREE.BoxGeometry(0.035, 0.16, 0.015), m, s * 0.03, -0.09, 0);
      tail.rotation.z = s * 0.25; g.add(tail);
    }
    g.add(mesh(new THREE.SphereGeometry(0.03, 6, 4), m));
    g.position.set(0, HEAD_Y + 0.12, -0.36);
    g.rotation.y = Math.PI;
    c.head.add(g);
  },
  book(c) {
    const b = mesh(new THREE.BoxGeometry(0.17, 0.22, 0.05), M('#8f2f2a'), 0.06, 0.7, 0.21);
    b.rotation.set(-0.15, 0, 0.12);
    b.add(mesh(new THREE.BoxGeometry(0.15, 0.2, 0.052), M('#f3ead8'), 0.012, 0, 0));
    c.body.add(b);
  },
  horns(c) {
    const m = M(c.accent);
    for (const s of [-1, 1]) {
      const h = mesh(new THREE.ConeGeometry(0.05, 0.26, 6), m, s * 0.16, HEAD_Y + 0.3, -0.06);
      h.rotation.set(-0.55, 0, -s * 0.35); c.head.add(h);
    }
  },
  wings(c) {
    const shape = new THREE.Shape();
    shape.moveTo(0, 0); shape.quadraticCurveTo(0.25, 0.32, 0.5, 0.36); shape.lineTo(0.42, 0.18); shape.lineTo(0.48, 0.06);
    shape.lineTo(0.36, -0.02); shape.lineTo(0.4, -0.16); shape.quadraticCurveTo(0.2, -0.08, 0, 0);
    const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.02, bevelEnabled: false });
    const m = M(c.spec.wing || c.outfit, { side: THREE.DoubleSide });
    c.wings = [];
    for (const s of [-1, 1]) {
      const pivot = new THREE.Group();
      pivot.position.set(s * 0.06, 0.82, -0.17);
      const w = mesh(geo, m);
      w.scale.set(s, 1, 1);
      pivot.add(w);
      pivot.rotation.y = s * 0.55;
      pivot.userData.base = s * 0.55; pivot.userData.side = s;
      c.body.add(pivot); c.wings.push(pivot);
    }
  },
  tail(c) {
    const curve = new THREE.CatmullRomCurve3([new THREE.Vector3(0, 0.42, -0.25), new THREE.Vector3(0.05, 0.25, -0.5),
      new THREE.Vector3(0.18, 0.1, -0.62), new THREE.Vector3(0.32, 0.12, -0.7)]);
    const t = mesh(new THREE.TubeGeometry(curve, 12, 0.05, 6), M(c.spec.tail_color || c.outfit));
    const tip = mesh(new THREE.ConeGeometry(0.07, 0.16, 5), M(c.accent), 0.38, 0.14, -0.72);
    tip.rotation.z = -1.3;
    c.body.add(t); c.body.add(tip);
  },
  maid_headband(c) {
    const g = new THREE.Group();
    const m = M('#ffffff');
    const arc = mesh(new THREE.TorusGeometry(0.355, 0.028, 5, 18, Math.PI), m);
    g.add(arc);
    for (let i = 0; i <= 8; i++) {
      const a = (i / 8) * Math.PI;
      g.add(mesh(new THREE.SphereGeometry(0.04, 6, 4), m, Math.cos(a) * 0.37, Math.sin(a) * 0.37, 0.01));
    }
    g.position.set(0, HEAD_Y + 0.02, -0.04);
    g.rotation.x = -0.42;
    c.head.add(g);
  },
  fins(c) {
    const m = M(c.spec.fin || c.hair, { side: THREE.DoubleSide });
    const edge = M('#f4f6fb');
    for (const s of [-1, 1]) {
      const f = new THREE.Group();
      const fin = mesh(new THREE.ConeGeometry(0.1, 0.24, 4), m);
      fin.scale.set(1, 1, 0.25); f.add(fin);
      const tipm = mesh(new THREE.ConeGeometry(0.06, 0.08, 4), edge, 0, 0.11, 0);
      tipm.scale.set(1, 1, 0.3); f.add(tipm);
      f.position.set(s * 0.36, HEAD_Y + 0.02, -0.02);
      f.rotation.set(0, s * 0.3, -s * 1.15);
      c.head.add(f);
    }
  },
  apron(c) {
    const m = M(c.outfit2, { side: THREE.DoubleSide });
    const skirt = mesh(new THREE.CylinderGeometry(0.185, 0.34, 0.38, 10, 1, true, -0.62, 1.24), m, 0, 0.42, 0);
    c.body.add(skirt);
    c.body.add(mesh(new THREE.BoxGeometry(0.17, 0.13, 0.02), m, 0, 0.78, 0.155));
    const whale = mesh(new THREE.SphereGeometry(0.045, 8, 6), M(c.accent), 0, 0.4, 0.275);
    whale.scale.set(1.5, 0.8, 0.3); c.body.add(whale);
  },
  whale_tail(c) {
    const m = M(c.hairTip);
    const g = new THREE.Group();
    for (const s of [-1, 1]) {
      const fl = mesh(new THREE.ConeGeometry(0.07, 0.2, 4), m, s * 0.08, 0, 0);
      fl.rotation.z = -s * 1.1; fl.scale.set(1, 1, 0.3); g.add(fl);
    }
    g.position.set(0, 0.3, -0.42);
    c.body.add(g);
  },
  k_pin(c) {
    const cv = document.createElement('canvas'); cv.width = cv.height = 64;
    const x = cv.getContext('2d');
    x.fillStyle = '#2b2f55'; x.fillRect(0, 0, 64, 64);
    x.strokeStyle = '#d9d6f0'; x.lineWidth = 4; x.strokeRect(4, 4, 56, 56);
    x.fillStyle = '#ffffff'; x.font = 'bold 44px sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText('K', 32, 35);
    const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace;
    const p = mesh(new THREE.BoxGeometry(0.11, 0.13, 0.02), [M('#2b2f55'), M('#2b2f55'), M('#2b2f55'), M('#2b2f55'),
      new THREE.MeshStandardMaterial({ map: tex, roughness: 0.6 }), M('#2b2f55')], 0.24, HEAD_Y + 0.2, 0.2);
    p.rotation.set(-0.2, 0.55, -0.15);
    c.head.add(p);
  },
};

// ---------------------------------------------------------------- 小人
export function buildAvatar(spec = {}, fallbackColor = '#999') {
  const c = {
    spec,
    hair: spec.hair || fallbackColor,
    hairTip: spec.hair_tip || spec.hair || fallbackColor,
    skin: spec.skin || '#fbe5d6',
    eyes: spec.eyes || '#5a4a7a',
    outfit: spec.outfit || '#3d3b4d',
    outfit2: spec.outfit2 || '#f2eee6',
    accent: spec.accent || fallbackColor,
  };
  const root = new THREE.Group();        // 位置 + 朝向
  const inner = new THREE.Group();       // 姿势（躺下时整个转过去）
  const body = new THREE.Group();
  const head = new THREE.Group();
  root.add(inner); inner.add(body); body.add(head);
  Object.assign(c, { root, inner, body, head });

  const skin = M(c.skin, { flatShading: false }), out = M(c.outfit), out2 = M(c.outfit2), hair = M(c.hair, { side: THREE.DoubleSide });
  const hairTip = M(c.hairTip, { side: THREE.DoubleSide });

  // 腿和鞋
  const legs = [];
  for (const s of [-1, 1]) {
    const pivot = new THREE.Group(); pivot.position.set(s * 0.08, HIP_Y, 0);
    pivot.add(mesh(new THREE.CylinderGeometry(0.05, 0.045, 0.24, 6), M(spec.legs || '#f4efe9'), 0, -0.12, 0));
    const shoe = mesh(new THREE.BoxGeometry(0.1, 0.07, 0.16), M(spec.shoes || '#3a2b2b'), 0, -0.25, 0.025);
    pivot.add(shoe);
    body.add(pivot); legs.push(pivot);
  }
  // 裙子、衬裙、上身
  body.add(mesh(new THREE.CylinderGeometry(0.17, 0.33, 0.42, 10), out, 0, 0.41, 0));
  body.add(mesh(new THREE.CylinderGeometry(0.335, 0.36, 0.07, 12), out2, 0, 0.215, 0));
  body.add(mesh(new THREE.CylinderGeometry(0.135, 0.165, 0.27, 10), out, 0, 0.745, 0));
  body.add(mesh(new THREE.BoxGeometry(0.1, 0.2, 0.02), out2, 0, 0.75, 0.14));
  body.add(mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.08, 6), skin, 0, 0.9, 0));
  // 手臂
  const arms = [];
  for (const s of [-1, 1]) {
    const pivot = new THREE.Group(); pivot.position.set(s * 0.17, 0.84, 0);
    pivot.add(mesh(new THREE.SphereGeometry(0.075, 8, 6), out2));
    pivot.add(mesh(new THREE.CylinderGeometry(0.042, 0.05, 0.28, 6), out2, 0, -0.15, 0));
    pivot.add(mesh(new THREE.SphereGeometry(0.045, 6, 5), skin, 0, -0.3, 0));
    pivot.rotation.z = s * 0.18;
    body.add(pivot); arms.push(pivot);
  }
  // 头
  head.add(mesh(new THREE.SphereGeometry(HEAD_R, 16, 12), skin, 0, HEAD_Y, 0));
  head.add(mesh(new THREE.SphereGeometry(0.355, 16, 10, Math.PI, Math.PI), hair, 0, HEAD_Y, 0));            // 后脑
  head.add(mesh(new THREE.SphereGeometry(0.36, 18, 8, 0, Math.PI * 2, 0, 0.98), hair, 0, HEAD_Y + 0.005, 0)); // 头顶和刘海
  for (let i = -2; i <= 2; i++) {                                                                                 // 刘海发梢
    const a = i * 0.28;
    const b = mesh(new THREE.ConeGeometry(0.06, 0.16, 4), hair, Math.sin(a) * 0.31, HEAD_Y + 0.13, Math.cos(a) * 0.29);
    b.rotation.set(Math.PI + 0.35, a, 0); b.scale.set(1, 1, 0.5); head.add(b);
  }
  for (const s of [-1, 1]) {                                                                                      // 两侧鬓发
    const lock = mesh(new THREE.CylinderGeometry(0.075, 0.045, 0.55, 6), hair, s * 0.29, HEAD_Y - 0.2, 0.06);
    lock.rotation.z = s * 0.1; head.add(lock);
  }
  head.add(mesh(new THREE.CylinderGeometry(0.33, 0.4, 0.74, 14, 1, false, Math.PI / 2, Math.PI), hair, 0, 0.82, -0.04)); // 长发
  head.add(mesh(new THREE.CylinderGeometry(0.4, 0.42, 0.16, 14, 1, false, Math.PI / 2, Math.PI), hairTip, 0, 0.37, -0.04));
  // 眼睛、嘴、腮红
  const eyes = [];
  for (const s of [-1, 1]) {
    const e = mesh(new THREE.SphereGeometry(0.068, 10, 8), M(c.eyes, { flatShading: false, roughness: 0.3 }), s * 0.12, HEAD_Y - 0.04, 0.29);
    e.scale.set(0.85, 1.2, 0.45); head.add(e); eyes.push(e);
    const hl = mesh(new THREE.SphereGeometry(0.02, 6, 4), M('#ffffff', { emissive: '#ffffff', emissiveIntensity: 0.4 }), s * 0.12 + 0.02, HEAD_Y - 0.0, 0.32);
    head.add(hl); eyes.push(hl);
    const blush = mesh(new THREE.SphereGeometry(0.05, 8, 6), M('#f3a3a0', { transparent: true, opacity: 0.55 }), s * 0.19, HEAD_Y - 0.12, 0.25);
    blush.scale.set(1, 0.5, 0.3); head.add(blush);
  }
  head.add(mesh(new THREE.BoxGeometry(0.045, 0.014, 0.01), M('#b5544a'), 0, HEAD_Y - 0.15, 0.322));

  // 躺下时盖的被子
  const quilt = mesh(new THREE.BoxGeometry(0.86, 0.12, 1.0), M(new THREE.Color(spec.quilt || fallbackColor).lerp(new THREE.Color('#ffffff'), 0.35).getStyle()), 0, 0.98, 0.62);
  quilt.visible = false; root.add(quilt);

  for (const name of spec.accents || []) {
    const fn = ACCESSORIES[name];
    if (fn) { try { fn(c); } catch (e) { console.warn('配件出错', name, e); } }
  }

  // ---------------- 动画
  const st = { pose: 'stand', t: Math.random() * 10, walking: false, asleep: false, gesture: null };
  const hand = new THREE.Object3D();
  hand.position.set(0, -0.32, 0);
  arms[0].add(hand);
  const allMats = [];
  root.traverse((o) => { if (o.isMesh) { (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => allMats.push(m)); } });

  function setPose(pose) { st.pose = pose; }
  function setWalking(w) { st.walking = w; }
  function setAsleep(a) {
    st.asleep = a;
    eyes.forEach((e, i) => { if (i % 2 === 0) e.scale.y = a ? 0.12 : 1.2; else e.visible = !a; });
  }
  allMats.forEach((m) => { m.userData.baseOpacity = m.opacity; m.userData.baseTransparent = m.transparent; });
  function setDim(d) {
    allMats.forEach((m) => {
      m.transparent = d ? true : m.userData.baseTransparent;
      m.opacity = d ? 0.4 * m.userData.baseOpacity : m.userData.baseOpacity;
      m.needsUpdate = true;
    });
  }

  function update(dt) {
    st.t += dt;
    const t = st.t;
    let y = 0, legX = 0, armX = 0, lie = false;
    const pose = st.walking ? 'walk' : st.pose;
    if (pose === 'walk') {
      const ph = t * 9;
      legs[0].rotation.x = Math.sin(ph) * 0.6; legs[1].rotation.x = -Math.sin(ph) * 0.6;
      arms[0].rotation.x = -Math.sin(ph) * 0.5; arms[1].rotation.x = Math.sin(ph) * 0.5;
      y = Math.abs(Math.sin(ph)) * 0.04;
      head.rotation.z = Math.sin(ph) * 0.03;
    } else {
      if (pose === 'sit') { y = 0.2; legX = -1.45; armX = -0.55; }
      else if (pose === 'sit_low') { y = 0.12; legX = -1.35; armX = -0.25; }
      else if (pose === 'sit_floor') { y = -0.2; legX = -1.5; armX = -0.2; }
      else if (pose === 'lie') { lie = true; }
      legs.forEach((l) => { l.rotation.x = legX; });
      arms.forEach((a, i) => { a.rotation.x = armX + Math.sin(t * 1.3 + i) * 0.03; });
      head.rotation.z = Math.sin(t * 0.7) * 0.03;
      y += Math.sin(t * 2.2) * 0.006;
    }
    if (st.gesture) { arms[0].rotation.x -= st.gesture.r[0] + st.gesture.r[1] * 0.5; arms[1].rotation.x -= st.gesture.l[0] + st.gesture.l[1] * 0.5; }
    quilt.visible = false;                // 被子由床提供，会贴着身体
    if (lie) {
      inner.rotation.x = -Math.PI / 2;
      inner.position.set(0, 0.9, 0.72);
      legs.forEach((l) => { l.rotation.x = 0; }); arms.forEach((a) => { a.rotation.x = 0; });
      body.scale.y = 1 + Math.sin(t * 1.6) * 0.01;
    } else {
      inner.rotation.x = 0;
      inner.position.set(0, y, 0);
      body.scale.y = 1;
    }
    if (c.wings) c.wings.forEach((w) => { w.rotation.y = w.userData.base + Math.sin(t * (st.walking ? 8 : 2)) * 0.12 * w.userData.side; });
  }

  update(0);
  return { root, setPose, setWalking, setAsleep, setDim, update, height: 1.55, hand, setGesture(g) { st.gesture = g; } };
}

// ---------------------------------------------------------------- 导出 .glb
export function exportGlb(spec, name, color) {
  const a = buildAvatar(spec, color);
  a.update(0);
  return new Promise((resolve, reject) => {
    new GLTFExporter().parse(a.root, (buf) => {
      const blob = new Blob([buf], { type: 'model/gltf-binary' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `${name}.glb`;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      resolve();
    }, reject, { binary: true });
  });
}
