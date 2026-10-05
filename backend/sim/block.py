"""Structural piece — a real rigid member (cube / beam / slab).

A piece spans w x d grid cells (1 cell tall) and is a single dynamic rigid
body, so it rests on its supports under real gravity: a slab on its legs, a beam
on its end columns. No welding, no zero-gravity. The class is still named
`Block` for import compatibility.

States:
    "supply"  -> just materialised at a feeder, about to be collected
    "carried" -> attached to a drone (collision-less while in transit)
    "placed"  -> set down on its supports, resting
    "dropped" -> fumbled in a collision, fell free, awaiting recovery
"""

import pybullet as p

from backend import config

VS = config.VOXEL_SIZE


class Block:
    _next_id = 0

    def __init__(self, piece_type, w, d, center, cells=None, state="supply"):
        self.id = Block._next_id
        Block._next_id += 1

        self.piece_type = piece_type       # "cube" | "beam" | "slab"
        self.w = int(w)                    # cells along x
        self.d = int(d)                    # cells along z
        self.cells = list(cells or [])     # [(x,y,z), ...] footprint in the grid
        self.state = state
        self.target_pos = list(center)
        self.mass = round(0.1 * self.w * self.d, 3)

        color = config.PIECE_TYPES[piece_type]["color"] + [1.0]
        half = [self.w * VS / 2.0, VS / 2.0, self.d * VS / 2.0]
        col = p.createCollisionShape(p.GEOM_BOX, halfExtents=half)
        vis = p.createVisualShape(p.GEOM_BOX, halfExtents=half, rgbaColor=color)
        self.body = p.createMultiBody(
            baseMass=self.mass,
            baseCollisionShapeIndex=col,
            baseVisualShapeIndex=vis,
            basePosition=list(center),
        )
        p.changeDynamics(self.body, -1, lateralFriction=1.2,
                         spinningFriction=0.1, rollingFriction=0.01)
        # Collision group 2 = structure (collides with ground group 1 + itself).
        p.setCollisionFilterGroupMask(self.body, -1, 2, -1)

    # -- back-compat alias (old code referred to block_type) ---------------
    @property
    def block_type(self):
        return self.piece_type

    # -- queries -----------------------------------------------------------
    @property
    def position(self):
        return list(p.getBasePositionAndOrientation(self.body)[0])

    def distance_to(self, pos):
        a = self.position
        return sum((a[i] - pos[i]) ** 2 for i in range(3)) ** 0.5

    # -- physics helpers ---------------------------------------------------
    def freeze(self):
        p.resetBaseVelocity(self.body, [0, 0, 0], [0, 0, 0])

    def teleport(self, position, orientation=(0, 0, 0, 1)):
        p.resetBasePositionAndOrientation(self.body, list(position), list(orientation))
        p.resetBaseVelocity(self.body, [0, 0, 0], [0, 0, 0])

    def set_ghost(self):
        """No collisions while carried, so a big slab doesn't jam the airspace."""
        p.setCollisionFilterGroupMask(self.body, -1, 0, 0)

    def set_solid(self):
        p.setCollisionFilterGroupMask(self.body, -1, 2, -1)

    def set_fall_clear(self):
        """Dropped piece: collide only with the ground (group 1) so it falls past
        the structure instead of smashing it, then gets recovered."""
        p.setCollisionFilterGroupMask(self.body, -1, 2, 1)

    def make_dynamic(self):
        p.changeDynamics(self.body, -1, mass=self.mass)

    def make_static(self):
        p.changeDynamics(self.body, -1, mass=0)

    def remove(self):
        try:
            p.removeBody(self.body)
        except Exception:
            pass
        self.body = None

    def to_state(self):
        return {
            "id": self.id,
            "position": self.position,
            "piece_type": self.piece_type,
            "w": self.w,
            "d": self.d,
            "state": self.state,
        }
