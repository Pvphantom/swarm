"""FastAPI backend: REST routes, websocket stream, and the simulation runner.

All PyBullet work (world setup, body creation, stepping) happens on ONE
dedicated runner thread — PyBullet's client is not safe to touch from multiple
threads. REST handlers just hand the blueprint to the runner and read back the
latest snapshot it publishes.
"""

import base64
import os
import threading
import time

from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import config
from backend.bridge.state_stream import get_world_state
from backend.cv import pipeline, voxelizer
from backend.sim.environment import Environment
from backend.swarm.manager import SwarmManager

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")


# ==========================================================================
# Simulation runner (owns the PyBullet thread)
# ==========================================================================
class SimulationRunner:
    def __init__(self):
        self.env = None
        self.manager = None
        self.thread = None
        self.running = False
        self._latest = {"status": "idle"}
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._start_error = None

    def start(self, blueprint):
        self.stop()
        self.blueprint = blueprint
        self.running = True
        self._ready.clear()
        self._start_error = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        # Wait for the world to build (or fail) before returning.
        self._ready.wait(timeout=30)
        if self._start_error:
            raise RuntimeError(self._start_error)
        return self.manager.status() if self.manager else {"status": "error"}

    def _run(self):
        try:
            self.env = Environment(gui=False).setup()
            self.manager = SwarmManager(self.blueprint, self.env)
            self.manager.deploy_swarm()
            with self._lock:
                self._latest = get_world_state(self.manager, self.env)
        except Exception as exc:  # surface setup failures to the API caller
            self._start_error = f"{type(exc).__name__}: {exc}"
            self.running = False
            self._ready.set()
            return
        self._ready.set()

        frame_dt = 1.0 / config.STREAM_FPS
        next_t = time.perf_counter()
        while self.running:
            for _ in range(config.STEPS_PER_STREAM):
                self.manager.control_step()
                self.env.step()
            snapshot = get_world_state(self.manager, self.env)
            with self._lock:
                self._latest = snapshot

            next_t += frame_dt
            sleep = next_t - time.perf_counter()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_t = time.perf_counter()

        if self.env is not None:
            self.env.disconnect()

    def stop(self):
        self.running = False
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=5)
        self.thread = None
        self.env = None
        self.manager = None
        with self._lock:
            self._latest = {"status": "idle"}

    def latest(self):
        with self._lock:
            return dict(self._latest)

    def status(self):
        if self.manager is None:
            return {"status": "idle", "running": self.running}
        s = self.manager.status()
        s["status"] = "running" if self.running else "stopped"
        return s


runner = SimulationRunner()
current_blueprint = None

app = FastAPI(title="SwarmBuild")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache(request, call_next):
    """Dev convenience: never cache static assets, so edits always load fresh."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


# ==========================================================================
# REST routes
# ==========================================================================
@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    """Upload an image, run the CV pipeline, return a validated blueprint."""
    global current_blueprint
    data = await file.read()
    image_b64 = base64.b64encode(data).decode("ascii")
    mime = file.content_type or "image/png"

    raw = pipeline.analyze_image(image_b64, mime=mime)
    if raw is None:
        # No GPT-4o key (or the call failed) → local CV voxelizes the actual image.
        blueprint = voxelizer.voxelize_image(data)
        blueprint["source"] = "local_cv"
    else:
        blueprint = voxelizer.process(raw)
        blueprint["source"] = "gpt-4o"

    current_blueprint = blueprint
    return blueprint


@app.post("/api/demo")
async def demo():
    """Load the built-in demo blueprint without uploading an image."""
    global current_blueprint
    blueprint = voxelizer.build_demo_blueprint()
    blueprint["source"] = "demo"
    current_blueprint = blueprint
    return blueprint


@app.get("/api/blueprint")
async def get_blueprint():
    if current_blueprint is None:
        return JSONResponse({"error": "no blueprint yet"}, status_code=404)
    return current_blueprint


@app.post("/api/start")
async def start():
    if current_blueprint is None:
        return JSONResponse({"error": "upload an image or load the demo first"},
                            status_code=400)
    try:
        status = runner.start(current_blueprint)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return {"started": True, "status": status}


@app.post("/api/reset")
async def reset():
    runner.stop()
    return {"reset": True}


@app.get("/api/status")
async def status():
    return runner.status()


# ==========================================================================
# WebSocket state stream
# ==========================================================================
@app.websocket("/ws/simulation")
async def ws_simulation(ws: WebSocket):
    import asyncio

    await ws.accept()
    try:
        while True:
            await ws.send_json(runner.latest())
            await asyncio.sleep(1.0 / config.STREAM_FPS)
    except WebSocketDisconnect:
        return
    except Exception:
        return


# ==========================================================================
# Static frontend (mounted last so /api and /ws win)
# ==========================================================================
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
