"""PyBullet world setup.

Builds a headless (DIRECT) physics world with:
  * a ground plane whose normal is +Y (so gravity along -Y rests blocks on it),
  * a thin visual "lego board" at the origin,
  * three supply zones, one per block type.

Runs headless by default so it works over SSH / on a server; pass gui=True for
a local debug window.
"""

import pybullet as p
import pybullet_data

from backend import config
from backend.sim.supply import SupplyZone


class Environment:
    def __init__(self, gui: bool = False):
        self.gui = gui
        self.client = None
        self.ground = None
        self.board_visual = None
        self.supply_zones = {}

    def setup(self):
        self.client = p.connect(p.GUI if self.gui else p.DIRECT)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.resetSimulation()

        p.setGravity(0, -9.81, 0)
        p.setTimeStep(config.SIM_TIMESTEP)
        p.setPhysicsEngineParameter(numSolverIterations=20)

        # Ground plane with a +Y normal (Y-up world).
        ground_col = p.createCollisionShape(p.GEOM_PLANE, planeNormal=[0, 1, 0])
        self.ground = p.createMultiBody(0, ground_col)
        p.changeDynamics(self.ground, -1, lateralFriction=1.0)
        # Ground is collision group 1; dropped pieces collide only with it.
        p.setCollisionFilterGroupMask(self.ground, -1, 1, -1)

        self._build_board()
        self._build_supply_zones()
        return self

    def _build_board(self):
        half = config.BOARD_SIZE / 2.0
        board_col = p.createCollisionShape(
            p.GEOM_BOX, halfExtents=[half, 0.005, half]
        )
        board_vis = p.createVisualShape(
            p.GEOM_BOX,
            halfExtents=[half, 0.005, half],
            rgbaColor=[0.10, 0.10, 0.18, 1.0],
        )
        # Sits just under y=0 so block bottoms rest on the visible surface.
        self.board_visual = p.createMultiBody(
            baseMass=0,
            baseCollisionShapeIndex=board_col,
            baseVisualShapeIndex=board_vis,
            basePosition=[0, -0.005, 0],
        )
        p.changeDynamics(self.board_visual, -1, lateralFriction=1.0)

    def _build_supply_zones(self):
        for block_type, cfg in config.SUPPLY_ZONES.items():
            self.supply_zones[block_type] = SupplyZone(block_type, cfg["position"])

    def step(self):
        p.stepSimulation()

    def disconnect(self):
        if self.client is not None:
            try:
                p.disconnect(self.client)
            except Exception:
                pass
            self.client = None

    def to_state(self):
        return {
            "board_size": config.BOARD_SIZE,
            "supply_zones": {
                bt: zone.to_state() for bt, zone in self.supply_zones.items()
            },
        }
