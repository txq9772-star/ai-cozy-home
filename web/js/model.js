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

  const st = { pose: 'stand', walking: false, closed: 0, closedTarget: 0, current: null };
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
    quilt.visible = pose === 'lie';
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
    if (st.closed !== st.closedTarget) {
      const step = dt * 6;
      st.closed = Math.abs(st.closedTarget - st.closed) <= step ? st.closedTarget : st.closed + Math.sign(st.closedTarget - st.closed) * step;
      faces.forEach((f) => { f.mesh.morphTargetInfluences[f.index] = st.closed; });
    }
  }

  apply(0);
  update(0);
  return { root, setPose, setWalking, setAsleep, setDim, update, height: 1.55 };
}
