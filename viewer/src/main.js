// 3D-просмотр изделия из model.json — та же модель, из которой режутся детали.
// Наши оси: X — ширина, Y — глубина (0 — лицо фасадов), Z — вверх. В three.js: (x, z, -y).
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

const V = (x, y, z) => new THREE.Vector3(x, z, -y);

function shade(hex, k) {
  const c = new THREE.Color(hex);
  c.multiplyScalar(k);
  return c;
}

function textSprite(text, k = 0.55, size = 46) {
  const cv = document.createElement('canvas');
  const ctx = cv.getContext('2d');
  ctx.font = `600 ${size}px Inter, system-ui, sans-serif`;
  const w = Math.ceil(ctx.measureText(text).width) + 24;
  cv.width = w; cv.height = size + 20;
  ctx.font = `600 ${size}px Inter, system-ui, sans-serif`;
  ctx.fillStyle = 'rgba(255,255,255,0.92)';
  ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = '#16233b';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 12, cv.height / 2 + 2);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  sp.scale.set(cv.width * k, cv.height * k, 1);
  sp.renderOrder = 10;
  return sp;
}

function dimLine(group, a, b, label, k) {
  const mat = new THREE.LineBasicMaterial({ color: 0x16233b });
  group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), mat));
  const s = textSprite(label, k);
  s.position.copy(a.clone().add(b).multiplyScalar(0.5));
  group.add(s);
}

export function mount(el, model, opts = {}) {
  const [W, D, H] = model.size;
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  el.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(opts.background || '#eef0f3');
  const camera = new THREE.PerspectiveCamera(32, 1, 10, 50000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  const center = V(W / 2, D / 2, H / 2);
  controls.target.copy(center);

  scene.add(new THREE.HemisphereLight(0xffffff, 0x9aa1ab, 1.15));
  const sun = new THREE.DirectionalLight(0xffffff, 1.7);
  const R = Math.hypot(W, D, H);
  sun.position.copy(V(-W * 0.45, -D * 1.6, H * 3.2 + R));
  sun.target.position.copy(center);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -2 * R, right: 2 * R, top: 2 * R, bottom: -2 * R, near: 10, far: R * 10 });
  sun.shadow.bias = -0.0005;
  scene.add(sun, sun.target);
  const fill = new THREE.DirectionalLight(0xffffff, 0.45);
  fill.position.copy(V(W * 2, -D, H));
  scene.add(fill);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(R * 8, R * 8), new THREE.ShadowMaterial({ opacity: 0.16 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);

  const pickables = [];
  const doors = [];
  const facades = [];
  const holeGroup = new THREE.Group();
  holeGroup.visible = !!opts.holes;
  const byPanel = {};

  for (const p of model.panels) {
    const [x0, y0, z0] = p.lo, [x1, y1, z1] = p.hi;
    const geo = new THREE.BoxGeometry(x1 - x0, z1 - z0, y1 - y0);
    const color = p.group === 'facade' ? shade(p.color, 0.93) : new THREE.Color(p.color);
    const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.78, metalness: 0.0, transparent: true });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: 0x2b2f36, transparent: true, opacity: 0.45 }));
    mesh.add(edges);
    mesh.userData = p;
    const c = V((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
    let holder = scene;
    if (p.door) {
      const pivot = new THREE.Group();
      pivot.position.copy(V(p.door.pivot_x, y1, 0));   // ось петли: край двери у внутренней пласти
      scene.add(pivot);
      mesh.position.copy(c.clone().sub(pivot.position));
      pivot.add(mesh);
      holder = pivot;
      const sign = p.door.hinge_side === 'left' ? -1 : 1;
      doors.push({ pivot, sign, angle: 0, target: 0 });
      if (p.door.handle) {
        const hd = p.door.handle;
        const bar = new THREE.Mesh(new THREE.BoxGeometry(10, hd.pitch + 20, 10),
          new THREE.MeshStandardMaterial({ color: 0x6b7280, metalness: 0.6, roughness: 0.35 }));
        bar.position.copy(V(hd.x, y0 - 28, hd.z).sub(pivot.position));
        bar.castShadow = true;
        pivot.add(bar);
        for (const dz of [-hd.pitch / 2, hd.pitch / 2]) {
          const leg = new THREE.Mesh(new THREE.BoxGeometry(8, 8, 28), bar.material);
          leg.position.copy(V(hd.x, y0 - 14, hd.z + dz).sub(pivot.position));
          pivot.add(leg);
        }
      }
      facades.push(mesh);
    } else {
      mesh.position.copy(c);
      scene.add(mesh);
    }
    byPanel[p.id] = { mesh, holder };
    pickables.push(mesh);
  }

  // отверстия — тёмные цилиндры точно по модели (видны при открытых дверях)
  const holeMat = new THREE.MeshBasicMaterial({ color: 0x111827 });
  for (const h of model.holes) {
    const geo = new THREE.CylinderGeometry(h.d / 2, h.d / 2, h.depth + 0.6, 20);
    const m = new THREE.Mesh(geo, holeMat);
    const dir = V(h.dir[0], h.dir[1], h.dir[2]).normalize();
    const start = V(h.p[0], h.p[1], h.p[2]).sub(dir.clone().multiplyScalar(0.3));
    const mid = start.clone().add(dir.clone().multiplyScalar(h.depth / 2));
    m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
    const host = byPanel[h.panel];
    if (host && host.holder !== scene) {
      m.position.copy(mid.sub(host.holder.position));
      host.holder.add(m);
    } else {
      m.position.copy(mid);
      holeGroup.add(m);
    }
    m.userData.isHole = true;
    m.visible = !!opts.holes;
  }
  scene.add(holeGroup);

  // габаритные размеры
  const dims = new THREE.Group();
  const off = 70;
  const k = Math.max(0.45, R * 0.0006);
  dimLine(dims, V(0, -off, 0), V(W, -off, 0), `${W}`, k);
  dimLine(dims, V(W + off, D, 0), V(W + off, D, H), `${H}`, k);
  dimLine(dims, V(W + off, 0, 0), V(W + off, D, 0), `${D}`, k);
  scene.add(dims);

  function frame(view = 'front3q') {
    const fov = THREE.MathUtils.degToRad(camera.fov);
    const dist = (R * 0.62) / Math.sin(fov / 2);
    const dirs = {
      front3q: V(0.62, -1.0, 0.55),
      front: V(0, -1, 0.12),
      top: V(0.2, -0.45, 1.0),
    };
    const d = (dirs[view] || dirs.front3q).normalize();
    camera.position.copy(center.clone().add(d.multiplyScalar(dist)));
    controls.target.copy(center);
    controls.update();
  }

  function resize() {
    const w = el.clientWidth || 800, h = el.clientHeight || 600;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  const api = {
    setDoors(open) { for (const d of doors) d.target = open ? d.sign * THREE.MathUtils.degToRad(100) : 0; },
    setDoorsInstant(open) { api.setDoors(open); for (const d of doors) { d.angle = d.target; d.pivot.rotation.y = d.angle; } },
    setFacades(show) { for (const m of facades) m.parent.visible = show; },
    setHoles(show) {
      scene.traverse(o => { if (o.userData && o.userData.isHole) o.visible = show; });
      holeGroup.visible = show;
    },
    setDims(show) { dims.visible = show; },
    view: frame,
    render() { renderer.render(scene, camera); },
    get doorsOpen() { return doors.some(d => d.target !== 0); },
  };

  const ray = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  let down = null;
  renderer.domElement.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
  renderer.domElement.addEventListener('pointerup', e => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    const r = renderer.domElement.getBoundingClientRect();
    mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(pickables, false).find(h => h.object.parent.visible !== false);
    for (const m of pickables) m.material.emissive && m.material.emissive.setHex(0x000000);
    if (hit) {
      hit.object.material.emissive.setHex(0x1d4ed8);
      hit.object.material.emissiveIntensity = 0.25;
      opts.onPick && opts.onPick(hit.object.userData);
    } else {
      opts.onPick && opts.onPick(null);
    }
  });

  window.addEventListener('resize', resize);
  resize();
  frame(opts.view || 'front3q');
  if (opts.open) api.setDoorsInstant(true);
  if (opts.facades === false) api.setFacades(false);

  let frames = 0;
  function loop() {
    for (const d of doors) {
      d.angle += (d.target - d.angle) * 0.12;
      if (Math.abs(d.target - d.angle) < 1e-3) d.angle = d.target;
      d.pivot.rotation.y = d.angle;
    }
    controls.update();
    renderer.render(scene, camera);
    if (++frames === 3) window.__mebelReady = true;
    requestAnimationFrame(loop);
  }
  loop();
  return api;
}
