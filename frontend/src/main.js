// Entry point — wires scene, renderers, UI, and the websocket state stream.
import { initScene } from "./scene.js?v=3";
import { BlockManager } from "./blocks.js?v=3";
import { DroneManager } from "./drones.js?v=3";
import { initUI } from "./ui.js?v=3";
import { StateSocket } from "./websocket.js?v=3";

const holder = document.getElementById("canvas-holder");
const { scene, camera, renderer, controls, holograms } = initScene(holder);

const blockMgr = new BlockManager(scene);
const droneMgr = new DroneManager(scene);

let latest = null;
let running = false;

const ui = initUI({
  onStart: () => { blockMgr.clear(); droneMgr.clear(); latest = null; running = true; },
  onReset: () => { blockMgr.clear(); droneMgr.clear(); latest = null; running = false; },
});

const socket = new StateSocket(
  (state) => {
    // Ignore idle heartbeats before a build starts.
    if (!state || !state.drones) return;
    latest = state;
    ui.updateHUD(state);
  },
  () => {}
);
socket.connect();

// Render loop — managers interpolate toward the latest state every frame.
function animate() {
  requestAnimationFrame(animate);
  const time = performance.now() / 1000;
  controls.update();
  for (const h of holograms) {
    h.rotation.y = time * 0.8;
    h.position.y = h.userData.baseY + Math.sin(time * 1.5 + h.userData.phase) * 0.05;
  }
  if (latest) {
    droneMgr.update(latest.drones, time);
    blockMgr.update(latest.blocks, time);
  }
  renderer.render(scene, camera);
}
animate();
