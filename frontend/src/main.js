// Entry point — wires scene, renderers, UI, and the websocket state stream.
import { initScene } from "./scene.js";
import { BlockManager } from "./blocks.js";
import { DroneManager } from "./drones.js";
import { initUI } from "./ui.js";
import { StateSocket } from "./websocket.js";

const holder = document.getElementById("canvas-holder");
const { scene, camera, renderer, controls } = initScene(holder);

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
  if (latest) {
    droneMgr.update(latest.drones, time);
    blockMgr.update(latest.blocks, time);
  }
  renderer.render(scene, camera);
}
animate();
