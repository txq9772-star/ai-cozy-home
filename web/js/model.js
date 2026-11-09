// 住户的 glb 模型（tools/avatars/ 生成）。对外接口跟 avatar.js 的 buildAvatar 返回的一样。
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { clone as cloneSkinned } from 'three/addons/utils/SkeletonUtils.js';

const FADE = 0.25;
const files = new Map();
const loader = new GLTFLoader();

function fetchGltf(url) {
  if (!files.has(url)) files.set(url, loader.loadAsync(url));
  return files.get(url);
}

export function modelUrl(model) { return '/skin/' + String(model).replace(/^\/+/, ''); }

export async function loadModelAvatar(url, spec = {}, fallbackColor = '#999') {
  const gltf = await fetchGltf(url);
  const scene = cloneSkinned(gltf.scene);
  const root = new THREE.Group();
  const inner = new THREE.Group();     // sit_low 比 sit 低一点，在这里补
  root.add(inner); inner.add(scene);

  const faces = [];
  const mats = [];
  scene.traverse((o) => {
    if (!o.isMesh) return;
    o.castShadow = true;
    o.frustumCulled = false;           // 躺下时骨骼把人移出了静止姿势的包围球
    o.material = o.material.clone();
    mats.push(o.material);
    const i = o.morphTargetDictionary?.eyes_closed;
    if (i !== undefined) faces.push({ mesh: o, index: i });
  });
  mats.forEach((m) => { m.userData.baseOpacity = m.opacity; m.userData.baseTransparent = m.transparent; });

  const color = new THREE.Color(spec.quilt || fallbackColor).lerp(new THREE.Color('#ffffff'), 0.35);
  const quilt = new THREE.Mesh(new THREE.BoxGeometry(0.86, 0.12, 1.0),
    new THREE.MeshStandardMaterial({ color, roughness: 0.75, flatShading: true, emissive: color, emissiveIntensity: 0.16 }));
  quilt.position.set(0, 0.98, 0.62);
  quilt.castShadow = true;
  quilt.visible = false;
  root.add(quilt);
  mats.push(quilt.material);
  quilt.material.userData.baseOpacity = 1; quilt.material.userData.baseTransparent = false;

  const mixer = new THREE.AnimationMixer(scene);
  const actions = {};
  for (const clip of gltf.animations) actions[clip.name] = mixer.clipAction(clip);
  if (!actions.idle) throw new Error('模型缺少 idle 动画：' + url);

  const st = { pose: 'stand', walking: false, closed: 0, closedTarget: 0, current: null, gesture: null };
  const bones = { r: [scene.getObjectByName('arm_R'), scene.getObjectByName('fore_R')], l: [scene.getObjectByName('arm_L'), scene.getObjectByName('fore_L')] };
  const hand = new THREE.Object3D();
  hand.position.set(0, 0.24, 0);
  bones.r[1]?.add(hand);
  const X = new THREE.Vector3(1, 0, 0), q = new THREE.Quaternion(), inv = new THREE.Quaternion(), axis = new THREE.Vector3();
  function bend(side, up, fore) {
    const [arm, low] = bones[side];
    if (!arm || !low) return;
    // 各骨骼自身的轴不一定朝前，这里把“人物的左右轴”换算到骨骼父节点的坐标里，手臂才是真的往前抬
    const turn = (bone, angle) => {
      inv.identity();
      for (let n = bone.parent; n && n !== scene; n = n.parent) inv.premultiply(n.quaternion);
      axis.copy(X).applyQuaternion(inv.invert());
      bone.quaternion.premultiply(q.setFromAxisAngle(axis, -angle));
    };
    turn(arm, up);
    turn(low, fore);
  }
  const clipFor = (p) => ({ stand: 'idle', sit_low: 'sit' }[p] || p);

  function play(name, fade) {
    const next = actions[name] || actions.idle;
    if (st.current === next) return;
    next.reset().setEffectiveWeight(1).play();
    next.time = Math.random() * next.getClip().duration;
    if (st.current && fade) { next.fadeIn(fade); st.current.fadeOut(fade); }
    else if (st.current) st.current.stop();
    st.current = next;
  }

  function apply(fade = FADE) {
    const pose = st.walking ? 'walk' : st.pose;
    play(clipFor(pose), fade);
    inner.position.y = pose === 'sit_low' ? -0.08 : 0;
    quilt.visible = false;                // 被子由床提供，会贴着身体
  }

  function setPose(pose) { if (pose !== st.pose) { st.pose = pose; apply(); } }
  function setWalking(w) { if (w !== st.walking) { st.walking = w; apply(); } }
  function setAsleep(a) { st.closedTarget = a ? 1 : 0; }
  function setDim(d) {
    mats.forEach((m) => {
      m.transparent = d ? true : m.userData.baseTransparent;
      m.opacity = d ? 0.4 * m.userData.baseOpacity : m.userData.baseOpacity;
      m.needsUpdate = true;
    });
  }
  function update(dt) {
    mixer.update(dt);
    if (st.gesture) { bend('r', st.gesture.r[0], st.gesture.r[1]); bend('l', st.gesture.l[0], st.gesture.l[1]); }
    if (st.closed !== st.closedTarget) {
      const step = dt * 6;
      st.closed = Math.abs(st.closedTarget - st.closed) <= step ? st.closedTarget : st.closed + Math.sign(st.closedTarget - st.closed) * step;
      faces.forEach((f) => { f.mesh.morphTargetInfluences[f.index] = st.closed; });
    }
  }

  apply(0);
  update(0);
  if (bones.r[0] && bones.r[1]) {                     // 手的位置按骨骼实际朝向算：从肩到肘的方向延长
    scene.updateWorldMatrix(true, true);
    const a = bones.r[0].getWorldPosition(new THREE.Vector3()), b = bones.r[1].getWorldPosition(new THREE.Vector3());
    const tip = b.clone().add(b.clone().sub(a).normalize().multiplyScalar(0.2));
    hand.position.copy(bones.r[1].worldToLocal(tip));
  }
  return { root, setPose, setWalking, setAsleep, setDim, update, height: 1.55, hand, setGesture(g) { st.gesture = g; } };
}
