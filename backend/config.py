"""Central configuration: block types, simulation parameters, world geometry.

Coordinate convention (consistent everywhere in this project):
    +Y is UP. Gravity acts along -Y. The lego board's top surface is at y = 0.
    x = left/right, z = front/back  (matches the CV prompt's x / z axes;
    the CV prompt's "y = up/down" maps to our world +Y).
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------------------
# API keys
# --------------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o")

# --------------------------------------------------------------------------
# Block catalogue
# --------------------------------------------------------------------------
# `dimensions` are FULL sizes in metres (half-extents are derived in the sim).
BLOCK_TYPES = {
    "small_cube": {
        "dimensions": [0.1, 0.1, 0.1],
        "color": [0.2, 0.6, 1.0],       # blue
        "mass": 0.1,
        "specialist_type": "small",
    },
    "large_slab": {
        "dimensions": [0.1, 0.1, 0.1],
        "color": [1.0, 0.4, 0.2],       # orange
        "mass": 0.3,
        "specialist_type": "large",
    },
    "medium_brick": {
        "dimensions": [0.1, 0.1, 0.1],
        "color": [0.4, 1.0, 0.4],       # green
        "mass": 0.2,
        "specialist_type": "generalist",
    },
}
# NOTE: all blocks are unit voxels (0.1^3) so the lattice tiles with no overlap;
# the type is purely colour / mass / specialist role.

# ----- Structural pieces (what the planner actually builds with) -----------
# The drones assemble the structure from these real members. The planner picks
# the shape per spot; colour encodes the member kind.
PIECE_TYPES = {
    "cube": {"color": [0.30, 0.65, 1.0],  "specialist": "cube"},   # 1x1 filler/detail
    "beam": {"color": [1.0, 0.55, 0.22],  "specialist": "beam"},   # 1xN spanning member
    "slab": {"color": [0.40, 1.0, 0.55],  "specialist": "slab"},   # MxN deck / plate
}

# Which piece kinds each drone role may carry.
SPECIALIST_RULES = {
    "cube": ["cube"],
    "beam": ["beam"],
    "slab": ["slab"],
    "generalist": ["cube", "beam", "slab"],
}

# Discount a specialist gets when bidding on its own piece kind (lower == wins).
SPECIALIST_DISCOUNT = 0.7

# --------------------------------------------------------------------------
# World geometry
# --------------------------------------------------------------------------
VOXEL_SIZE = 0.1            # metres per voxel cell (one small_cube edge)
BOARD_SIZE = 1.0           # 1m x 1m build board, centred on origin
MAX_GRID = 10              # CV blueprint clamped to 10 x 10 x 10

CRUISE_HEIGHT = 0.5        # drones cruise this high above the board
CARRY_OFFSET = 0.12        # block hangs this far below the drone centre (constraint)
GRAB_HEIGHT = 0.26         # drone centre height when grabbing from a supply zone
RELEASE_GAP = 0.03         # block is released this far above its target, then falls

# Supply zones — one holographic feeder per piece kind, off the -X side.
SUPPLY_ZONES = {
    "cube": {"position": [-1.4, 0.0,  0.35]},
    "beam": {"position": [-1.4, 0.0,  0.0]},
    "slab": {"position": [-1.4, 0.0, -0.35]},
}

# Drone staging positions are generated procedurally in the swarm manager.
STAGING_ORIGIN = [1.4, CRUISE_HEIGHT, -0.5]
STAGING_SPACING = 0.25

# --------------------------------------------------------------------------
# Simulation parameters
# --------------------------------------------------------------------------
SIM_HZ = 240               # PyBullet internal step rate
SIM_TIMESTEP = 1.0 / SIM_HZ
STREAM_FPS = 30            # websocket state broadcast rate
STEPS_PER_STREAM = SIM_HZ // STREAM_FPS   # sample every N physics steps (8)

MAX_DRONES = 10
TARGET_COMPLETION_STEPS = 3000   # tuning target for robot-count time factor

# Build strategy: how many drones may actively build at once. The rest park at
# the staging area — piling every drone into a cramped layer hurts more than it
# helps (collisions), so concurrency is capped to what the space can absorb.
MAX_CONCURRENT_BUILDERS = 3

# --------------------------------------------------------------------------
# Structural / architectural rules
# --------------------------------------------------------------------------
# How far a block may cantilever (in-layer steps) from a supported column
# before it's considered unsupported. A chair seat spanning corner legs is a
# cantilever of 1-2; beyond this we scaffold or flag instead of placing a block
# that couldn't physically stay up.
MAX_CANTILEVER = 3

# Adaptive piece planner: pieces are real structural members (cubes/beams/slabs)
# that rest on their supports under gravity.
PIECE_MAX_SPAN = 4        # longest side of a single piece, in cells
PIECE_MAX_OVERHANG = 2    # how far a piece may overhang its footing (verified stable in physics)

# Weld each placed block to its already-placed neighbours (the "adhesive").
WELD_JOINTS = True
WELD_MAX_FORCE = 2000.0

# Non-ground blocks stay dynamic and are held up purely by their welded joints
# (true structural simulation). PyBullet's fixed constraints are too compliant
# for this — a cantilevered plate droops several cm and breaks the lattice — so
# we anchor each placed block instead. The welds are still created and define
# the connectivity graph (the "adhesive"); anchoring keeps the build exact.
DYNAMIC_STRUCTURE = False
SCAFFOLD_UNSUPPORTED = True   # add support columns under floating voxels

# Drone flight / control
DRONE_MASS = 0.4
DRONE_HALF_EXTENTS = [0.06, 0.03, 0.06]
PD_KP = 16.0               # position gain
PD_KD = 7.0                # velocity (damping) gain
MAX_DRONE_FORCE = 40.0     # clamp on PD force magnitude
ARRIVAL_TOLERANCE = 0.05   # metres — "close enough" to a waypoint
DESCEND_TIMEOUT = 300      # steps before a descend phase gives up and proceeds

# Placement / failure handling
PLACEMENT_TOLERANCE = 0.02     # 2cm — spec's placement acceptance radius
PLACEMENT_SETTLE_STEPS = 60    # steps to let a placed block settle before checking
PLACE_SETTLE_FRAMES = 70       # steps a piece settles (dynamic) before it sets
MAX_PLACEMENT_RETRIES = 1      # retry once on same drone, then reassign
COLLISION_DISTANCE = 0.115     # centre-to-centre distance treated as a collision
COLLISION_HEIGHT_GATE = 0.07   # only collide when within this vertical distance
COLLISION_COOLDOWN = 90        # steps a drone is collision-immune after one
AVOIDANCE_STEP = 0.35          # how far drones jump apart after a collision


def block_half_extents(block_type: str):
    return [d / 2.0 for d in BLOCK_TYPES[block_type]["dimensions"]]


def voxel_to_world(vx: int, vy: int, vz: int, grid_dim: dict):
    """Map an integer voxel coordinate to a world-space block centre.

    The grid is centred on the board in X/Z; +Y stacks upward from the board.
    """
    dx = grid_dim.get("x", MAX_GRID)
    dz = grid_dim.get("z", MAX_GRID)
    world_x = (vx - dx / 2.0 + 0.5) * VOXEL_SIZE
    world_y = vy * VOXEL_SIZE + VOXEL_SIZE / 2.0
    world_z = (vz - dz / 2.0 + 0.5) * VOXEL_SIZE
    return [world_x, world_y, world_z]
