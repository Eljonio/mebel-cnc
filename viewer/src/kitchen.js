// 3D-просмотр кухни из scene.json — та же модель, что в рендерах Blender и в деталировке.
// Оси помещения: X вдоль стены A, Y в комнату, Z вверх. В three.js: (X, Z, Y) — тогда вид не зеркальный.
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

const T = (x, y, z) => new THREE.Vector3(x, z, y);

function woodTexture() {
  const cv = document.createElement('canvas');
  cv.width = 1024; cv.height = 256;
  const g = cv.getContext('2d');
  g.fillStyle = '#b8895a';
  g.fillRect(0, 0, cv.width, cv.height);
  let seed = 7;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let i = 0; i < 140; i++) {
    const y = rnd() * cv.height, a = 1 + rnd() * 3, ph = rnd() * 6;
    g.strokeStyle = `rgba(${110 + rnd() * 40},${70 + rnd() * 25},${35 + rnd() * 15},${0.12 + rnd() * 0.18})`;
    g.lineWidth = 0.6 + rnd() * 2.2;
    g.beginPath();
    for (let x = 0; x <= cv.width; x += 16) g.lineTo(x, y + Math.sin(x / 140 + ph) * a);
    g.stroke();
  }
  const t = new THREE.CanvasTexture(cv);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

function tileTexture() {
  const cv = document.createElement('canvas');
  cv.width = cv.height = 256;
  const g = cv.getContext('2d');
  g.fillStyle = '#d6cec2'; g.fillRect(0, 0, 256, 256);
  g.strokeStyle = '#bdb4a8'; g.lineWidth = 3; g.strokeRect(0, 0, 256, 256);
  const t = new THREE.CanvasTexture(cv);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}

// коробка с UV в мировых мм (для дерева и плитки): 1 повтор текстуры = scale мм
function boxGeo(b, grainY, scale) {
  const [x0, y0, z0, x1, y1, z1] = b;
  const g = new THREE.BoxGeometry(x1 - x0, z1 - z0, y1 - y0);
  g.translate((x0 + x1) / 2, (z0 + z1) / 2, (y0 + y1) / 2);
  const p = g.attributes.position, n = g.attributes.normal, uv = g.attributes.uv;
  for (let i = 0; i < p.count; i++) {
    const X = p.getX(i), Z = p.getY(i), Y = p.getZ(i);
    const nx = Math.abs(n.getX(i)), ny = Math.abs(n.getY(i));
    let u, v;
    if (ny > 0.5) { u = grainY ? Y : X; v = grainY ? X : Y; }        // верх/низ
    else if (nx > 0.5) { u = grainY ? Y : Z; v = Z; }
    else { u = X; v = Z; }
    uv.setXY(i, u / scale, v / scale * 4);
  }
  return g;
}

function label(text, opts = {}) {
  const size = opts.size || 44;
  const cv = document.createElement('canvas');
  const g = cv.getContext('2d');
  g.font = `600 ${size}px Inter, system-ui, sans-serif`;
  const w = Math.ceil(g.measureText(text).width) + 28;
  cv.width = w; cv.height = size + 22;
  g.font = `600 ${size}px Inter, system-ui, sans-serif`;
  g.fillStyle = opts.bg || 'rgba(22,35,59,0.88)';
  g.beginPath(); g.roundRect(0, 0, cv.width, cv.height, 12); g.fill();
  g.fillStyle = opts.fg || '#fff';
  g.textBaseline = 'middle';
  g.fillText(text, 14, cv.height / 2 + 2);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  const k = opts.k || 1.6;
  sp.scale.set(cv.width * k, cv.height * k, 1);
  sp.renderOrder = 20;
  return sp;
}

export function mount(el, S, opts = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  el.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#e7ecf1');
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.55;

  const { a, b, height: H } = S.room;
  const center = T(a / 2, b / 2, 900);
  scene.add(new THREE.HemisphereLight(0xffffff, 0xb9b1a6, 0.9));
  const sun = new THREE.DirectionalLight(0xfff4e6, 1.6);
  sun.position.copy(T(a * 0.75, -b * 0.9, H * 2.6));
  sun.target.position.copy(center);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  const R = Math.hypot(a, b);
  Object.assign(sun.shadow.camera, { left: -R, right: R, top: R, bottom: -R, near: 100, far: R * 6 });
  sun.shadow.bias = -0.0004;
  scene.add(sun, sun.target);
  const fill = new THREE.DirectionalLight(0xffffff, 0.5);
  fill.position.copy(T(a * 1.2, b * 1.6, H * 1.2));
  scene.add(fill);

  const wood = woodTexture(), tiles = tileTexture();
  const mats = {};
  for (const [key, m] of Object.entries(S.mats)) {
    const p = { color: new THREE.Color(m.color), roughness: m.rough ?? 0.5, metalness: m.metal ?? 0 };
    if (m.wood) { p.map = wood; p.color = new THREE.Color('#ffffff'); }
    if (m.tiles) { p.map = tiles; p.color = new THREE.Color('#ffffff'); }
    if (m.opacity !== undefined) { p.transparent = true; p.opacity = m.opacity; p.depthWrite = false; }
    if (m.emissive) { p.emissive = new THREE.Color(m.color); p.emissiveIntensity = 1.2; }
    mats[key] = new THREE.MeshStandardMaterial(p);
  }

  const groups = { wallC: [], wallD: [], facades: [], points: [], labels: [], full: [], cut: [] };
  const clipCam = Object.values(S.cameras).find(c => c.clip);
  const clipZ = clipCam ? clipCam.clip : 0;
  const clipDrop = clipCam ? (clipCam.clip_drop || []) : [];
  let cutMode = false, hiddenWalls = [];
  function refreshRoom() {
    for (const m of groups.full) m.visible = !cutMode && !hiddenWalls.includes(m.userData.wall);
    for (const m of groups.cut) m.visible = cutMode && !hiddenWalls.includes(m.userData.wall);
  }
  const pickables = [];
  for (const s of S.solids) {
    let geo;
    if (s.shape === 'cyl_z') {
      const [x0, y0, z0, x1, y1, z1] = s.boxes[0];
      geo = new THREE.CylinderGeometry((x1 - x0) / 2, (x1 - x0) / 2, z1 - z0, 28);
      geo.translate((x0 + x1) / 2, (z0 + z1) / 2, (y0 + y1) / 2);
    } else {
      const scale = s.mat === 'floor' ? 600 : 2400;
      const parts = s.boxes.map(bx => boxGeo(bx, s.grain === 'y', scale));
      geo = parts.length === 1 ? parts[0] : mergeGeometries(parts);
    }
    let mat = mats[s.mat];
    if (s.kind === 'point') {
      mat = new THREE.MeshBasicMaterial({ color: S.mats[s.mat].color, depthTest: false, transparent: true, opacity: 0.9 });
    }
    const mesh = new THREE.Mesh(geo, mat);
    mesh.castShadow = !['glass', 'floor'].includes(s.mat) && s.kind !== 'point';
    mesh.receiveShadow = s.kind !== 'point';
    mesh.userData = s;
    if (s.kind === 'point') { mesh.renderOrder = 15; groups.points.push(mesh); mesh.visible = false; }
    if (s.wall === 'C') groups.wallC.push(mesh);
    if (s.wall === 'D') groups.wallD.push(mesh);
    if (s.kind === 'facade' || s.kind === 'filler') groups.facades.push(mesh);
    if (!['room', 'wall', 'window', 'door', 'point'].includes(s.kind)) pickables.push(mesh);
    scene.add(mesh);
    if (['wall', 'window', 'door'].includes(s.kind)) {
      mesh.userData.full = true;
      groups.full.push(mesh);
      if (s.shape === 'box' && clipZ && !clipDrop.includes(s.id)) {
        const cb = s.boxes.filter(b => b[2] < clipZ - 0.5).map(b => [b[0], b[1], b[2], b[3], b[4], Math.min(b[5], clipZ)]);
        if (cb.length) {
          const cg = cb.length === 1 ? boxGeo(cb[0], false, 2400) : mergeGeometries(cb.map(bx => boxGeo(bx, false, 2400)));
          const cm = new THREE.Mesh(cg, mat);
          cm.castShadow = cm.receiveShadow = true;
          cm.userData = { ...s, cut: true };
          cm.visible = false;
          groups.cut.push(cm);
          if (s.wall === 'C') groups.wallC.push(cm);
          if (s.wall === 'D') groups.wallD.push(cm);
          scene.add(cm);
        }
      }
    }
  }
  for (const l of S.labels) {
    const sp = label(l.text);
    sp.position.copy(T(...l.pos));
    sp.visible = false;
    groups.labels.push(sp);
    scene.add(sp);
  }
  for (const p of S.points) {
    const sp = label(p.name, { bg: p.color, size: 34, k: 1.5 });
    sp.position.copy(T(p.pos[0] + (p.pos[0] < 5 ? 260 : 0), p.pos[1] + (p.pos[1] < 5 ? 260 : 0), p.pos[2] + 120));
    sp.visible = false;
    groups.points.push(sp);
    scene.add(sp);
  }

  const camera = new THREE.PerspectiveCamera(40, 1, 20, 60000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  function setGroup(name, show) { for (const o of groups[name]) o.visible = show; }
  function view(name) {
    const c = S.cameras[name];
    if (!c) return;
    const hide = c.hide || [];
    cutMode = !!c.clip;
    hiddenWalls = [...hide];
    refreshRoom();
    if (c.ortho) {
      camera.fov = 12;
      const dist = (c.ortho / 2) / Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.05;
      camera.position.copy(T(c.target[0], c.target[1] + dist * 0.02, dist));
    } else if (c.fov_h) {
      // камера «как на фото»: горизонтальный угол обзора и сдвиг оптического центра (как в Blender shift_x)
      const asp = camera.aspect || 1.6;
      camera.fov = 2 * THREE.MathUtils.radToDeg(Math.atan(Math.tan(THREE.MathUtils.degToRad(c.fov_h / 2)) / asp));
      camera.filmGauge = 36;
      camera.filmOffset = (c.shift_x || 0) * 36;
      camera.position.copy(T(...c.pos));
    } else {
      camera.fov = 2 * THREE.MathUtils.radToDeg(Math.atan(12 / c.lens)) * 1.15;
      camera.filmOffset = 0;
      camera.position.copy(T(...c.pos));
    }
    camera.updateProjectionMatrix();
    currentView = name;
    controls.target.copy(T(...c.target));
    controls.update();
    opts.onView && opts.onView(name, hide);
  }

  let currentView = null;
  function resize() {
    const w = el.clientWidth || 1200, h = el.clientHeight || 800;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (currentView && S.cameras[currentView] && S.cameras[currentView].fov_h) view(currentView);
  }

  const ray = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  let down = null, picked = null;
  renderer.domElement.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointerup', e => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    const r = renderer.domElement.getBoundingClientRect();
    mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(pickables.filter(m => m.visible), false)[0];
    if (picked) { picked.material = picked.userData._mat; picked = null; }
    if (hit) {
      picked = hit.object;
      picked.userData._mat = picked.material;
      picked.material = picked.material.clone();
      picked.material.emissive = new THREE.Color('#1d4ed8');
      picked.material.emissiveIntensity = 0.35;
    }
    opts.onPick && opts.onPick(hit ? hit.object.userData : null);
  });

  window.addEventListener('resize', resize);
  resize();
  view(opts.view || 'angle');
  let frames = 0;
  (function loop() {
    controls.update();
    renderer.render(scene, camera);
    if (++frames === 4) window.__kitchenReady = true;
    requestAnimationFrame(loop);
  })();
  return {
    view,
    orbit(deg) {   // повернуть камеру вокруг вертикали через цель (для проверки вращения без мыши)
      const off = camera.position.clone().sub(controls.target);
      off.applyAxisAngle(new THREE.Vector3(0, 1, 0), THREE.MathUtils.degToRad(deg));
      camera.position.copy(controls.target).add(off);
      controls.update();
    },
    walls(show) { hiddenWalls = show ? [] : ['C', 'D']; refreshRoom(); },
    facades(show) { setGroup('facades', show); },
    points(show) { setGroup('points', show); },
    labels(show) { setGroup('labels', show); },
  };
}
