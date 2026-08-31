# SwarmBuild — Multi-Agent Construction Robot System

A drone swarm that autonomously builds a 3D voxel structure from an uploaded
image. A CV pipeline turns the photo into a pixelated voxel blueprint; a swarm
of up to 10 specialist/generalist drones coordinate via **auction-based task
allocation** to pick up blocks and place them — with collision handling,
dropped-block recovery, and dynamic generalist reassignment — simulated in
**PyBullet** and streamed live over a **WebSocket** to a **Three.js** frontend.

```
Browser (Three.js)  ──WS state stream──┐
   upload / start ───REST──────────────┤
                                        ▼
                                  FastAPI backend
                     CV pipeline · Swarm manager · Physics bridge
                                        │
                                  PyBullet simulation
                        board · supply zones · drones · blocks
```

## Quick start

PyBullet has no macOS-arm64 wheel and won't compile under Python 3.13 here, so
the project runs in a **Python 3.11 conda env** using the prebuilt conda-forge
PyBullet binary.

```bash
# 1. environment
conda create -y -n swarmbuild python=3.11
conda activate swarmbuild
conda install -y -c conda-forge pybullet
pip install fastapi "uvicorn[standard]" websockets openai Pillow numpy python-dotenv python-multipart

# 2. run (port 8000 was busy on the dev machine; 8010 is the default here)
./run.sh                # or:
PYTHONPATH=. uvicorn backend.main:app --host 127.0.0.1 --port 8010
```

Then open <http://127.0.0.1:8010>, click **Use demo blueprint (chair)** (or drop
an image), and hit **Start build**.

## OpenAI (optional)

The CV pipeline uses GPT-4o Vision. Without a key it falls back to a
deterministic demo blueprint (a chair), so the whole system runs offline.

```bash
cp .env.example .env      # then add your key
# OPENAI_API_KEY=sk-...
```

## API

| Method | Route              | Purpose                                  |
|--------|--------------------|------------------------------------------|
| POST   | `/api/upload`      | Upload image → CV pipeline → blueprint   |
| POST   | `/api/demo`        | Load the built-in demo blueprint         |
| GET    | `/api/blueprint`   | Current voxel blueprint                   |
| POST   | `/api/start`       | Deploy swarm, start the simulation        |
| POST   | `/api/reset`       | Stop and tear down the simulation         |
| GET    | `/api/status`      | Current swarm status                      |
| WS     | `/ws/simulation`   | 30 fps physics state stream               |

## Layout

```
backend/
  main.py            FastAPI app + threaded simulation runner
  config.py          block types, world geometry, sim/tuning params
  cv/                GPT-4o Vision pipeline + voxelizer/validator
  sim/               PyBullet world, drone agent, block, supply zones
  swarm/             manager, auction allocator, specialist roles, failures
  bridge/            PyBullet state → JSON snapshot for the stream
frontend/
  index.html, style.css
  src/               scene, drones, blocks, ui, websocket, main (Three.js)
```

## Design decisions (interview talking points)

- **Auction-based allocation** — decentralised, no central-planner bottleneck;
  each drone bids its own travel cost, so it scales with drone count.
- **No mid-task reassignment** — reassignment only happens when a drone goes
  idle, avoiding race conditions on partially built sections.
- **Specialist robots** — each specialist knows its supply zone and is tuned for
  one block type (bid discount); generalists cover gaps and are flagged as
  *helpers* when specialist work is stranded.
- **Spatial distribution for robot count** — combines build-footprint quadrant
  spread, a time-per-drone estimate, and block-type diversity (≥1 specialist per
  type), capped at 10.
- **PyBullet → WebSocket → Three.js** — physics truth is decoupled from the
  visual representation; the stream (30 fps, sampling PyBullet's 240 Hz every 8
  steps) is a clean interface between them.

### Implementation notes

- Drones fly with a **PD controller + gravity compensation** (pure force
  application, no ROS), each in its **own altitude lane** so cruising drones
  don't collide — collisions occur when two descend onto the same spot, which is
  what the failure-handling demo shows.
- Blocks are **layer-ordered** (bottom-up) so upper voxels rest on placed
  supports; placement **snaps to the exact target** for a clean lattice, while
  **dropped** blocks fall under real physics and are recovered via
  high-priority tasks.
