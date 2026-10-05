// Three.js scene setup — dark "construction site in the void" aesthetic.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

// PyBullet works in metres; scale up so the 1m board fills the viewport.
export const WORLD_SCALE = 3.5;
export const S = (v) => [v[0] * WORLD_SCALE, v[1] * WORLD_SCALE, v[2] * WORLD_SCALE];

export const BLOCK_COLORS = {
  cube: 0x4ca6ff,
  beam: 0xff8c38,
  slab: 0x66ff8c,
};

// Supply-zone world positions + representative hologram shape (w x d cells),
// must match backend config.SUPPLY_ZONES.
const SUPPLY = {
  cube: { pos: [-1.4, 0, 0.35], w: 1, d: 1 },
  beam: { pos: [-1.4, 0, 0.0], w: 4, d: 1 },
  slab: { pos: [-1.4, 0, -0.35], w: 2, d: 2 },
};

export function initScene(container) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0a0f);
  scene.fog = new THREE.Fog(0x0a0a0f, 12, 34);

  const w = container.clientWidth;
  const h = container.clientHeight;
  const camera = new THREE.PerspectiveCamera(58, w / h, 0.1, 200);
  camera.position.set(6.5, 5.5, 7.5);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(w, h);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.target.set(0, 0.6, 0);
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.minDistance = 3;
  controls.maxDistance = 22;

  // ---- lighting ----
  scene.add(new THREE.AmbientLight(0x334466, 0.7));
  const dir = new THREE.DirectionalLight(0x8899ff, 1.1);
  dir.position.set(4, 9, 5);
  dir.castShadow = true;
  dir.shadow.mapSize.set(1024, 1024);
  dir.shadow.camera.near = 1;
  dir.shadow.camera.far = 30;
  dir.shadow.camera.left = -8;
  dir.shadow.camera.right = 8;
  dir.shadow.camera.top = 8;
  dir.shadow.camera.bottom = -8;
  scene.add(dir);
  const rim = new THREE.PointLight(0x6a3aff, 0.6, 30);
  rim.position.set(-6, 4, -4);
  scene.add(rim);

  // ---- lego board ----
  const boardSize = 1.0 * WORLD_SCALE;
  const board = new THREE.Mesh(
    new THREE.BoxGeometry(boardSize, 0.06, boardSize),
    new THREE.MeshStandardMaterial({ color: 0x1a1a2e, metalness: 0.3, roughness: 0.8 })
  );
  board.position.y = -0.03;
  board.receiveShadow = true;
  scene.add(board);

  const grid = new THREE.GridHelper(boardSize, 20, 0x2a2a4e, 0x1f1f3a);
  grid.position.y = 0.001;
  scene.add(grid);

  // subtle glowing edge around the board
  const edge = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(boardSize, 0.06, boardSize)),
    new THREE.LineBasicMaterial({ color: 0x4488ff, transparent: true, opacity: 0.35 })
  );
  edge.position.y = -0.03;
  scene.add(edge);

  // ---- supply zones (holographic, infinite feeders) ----
  const holograms = [];
  const unit = 0.1 * WORLD_SCALE;
  for (const [type, cfg] of Object.entries(SUPPLY)) {
    const pos = cfg.pos;
    const p = S(pos);
    const pad = new THREE.Mesh(
      new THREE.CylinderGeometry(0.4, 0.4, 0.03, 32),
      new THREE.MeshStandardMaterial({
        color: BLOCK_COLORS[type],
        emissive: BLOCK_COLORS[type],
        emissiveIntensity: 0.35,
        transparent: true,
        opacity: 0.5,
      })
    );
    pad.position.set(p[0], 0.015, p[2]);
    pad.receiveShadow = true;
    scene.add(pad);

    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(0.4, 0.015, 8, 40),
      new THREE.MeshBasicMaterial({ color: BLOCK_COLORS[type] })
    );
    ring.rotation.x = Math.PI / 2;
    ring.position.set(p[0], 0.04, p[2]);
    scene.add(ring);

    // Holographic piece — shaped like the member kind, translucent + bobbing.
    const holo = new THREE.Group();
    const bw = cfg.w * unit, bd = cfg.d * unit;
    const fill = new THREE.Mesh(
      new THREE.BoxGeometry(bw, unit, bd),
      new THREE.MeshBasicMaterial({ color: BLOCK_COLORS[type], transparent: true, opacity: 0.22 })
    );
    const wire = new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.BoxGeometry(bw, unit, bd)),
      new THREE.LineBasicMaterial({ color: BLOCK_COLORS[type], transparent: true, opacity: 0.9 })
    );
    holo.add(fill, wire);
    holo.position.set(p[0], 0.5, p[2]);
    holo.userData = { baseY: 0.5, phase: Math.random() * Math.PI * 2 };
    scene.add(holo);
    holograms.push(holo);
  }

  // ---- starfield ----
  const starGeo = new THREE.BufferGeometry();
  const starCount = 700;
  const pts = new Float32Array(starCount * 3);
  for (let i = 0; i < starCount; i++) {
    const r = 40 + Math.random() * 40;
    const th = Math.random() * Math.PI * 2;
    const ph = Math.acos(2 * Math.random() - 1);
    pts[i * 3] = r * Math.sin(ph) * Math.cos(th);
    pts[i * 3 + 1] = Math.abs(r * Math.cos(ph)) * 0.6;
    pts[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th);
  }
  starGeo.setAttribute("position", new THREE.BufferAttribute(pts, 3));
  scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0x8899ff, size: 0.15, transparent: true, opacity: 0.6 })));

  window.addEventListener("resize", () => {
    const nw = container.clientWidth, nh = container.clientHeight;
    camera.aspect = nw / nh;
    camera.updateProjectionMatrix();
    renderer.setSize(nw, nh);
  });

  return { scene, camera, renderer, controls, holograms };
}
