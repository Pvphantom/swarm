"""Block physics wrapper.

A Block owns one PyBullet rigid body. Blocks move through these states:
    "supply"  -> sitting in a supply zone, waiting to be collected
    "carried" -> attached to a drone via a constraint
    "placed"  -> released onto the board, settled at its target voxel
    "dropped" -> released unexpectedly (collision) and awaiting recovery
"""

import pybullet as p

from backend import config


class Block:
    _next_id = 0

    def __init__(self, block_type: str, position, state: str = "supply"):
        self.id = Block._next_id
        Block._next_id += 1

        self.block_type = block_type
        self.state = state
        self.target_pos = None          # filled in when assigned to a task
        self.spec = config.BLOCK_TYPES[block_type]

        half = config.block_half_extents(block_type)
        color = self.spec["color"] + [1.0]

        col = p.createCollisionShape(p.GEOM_BOX, halfExtents=half)
        vis = p.createVisualShape(p.GEOM_BOX, halfExtents=half, rgbaColor=color)
        self.body = p.createMultiBody(
            baseMass=self.spec["mass"],
            baseCollisionShapeIndex=col,
            baseVisualShapeIndex=vis,
            basePosition=list(position),
        )
        # A little friction so placed blocks don't slide off the stack.
        p.changeDynamics(self.body, -1, lateralFriction=0.9, spinningFriction=0.05)

    # -- queries -----------------------------------------------------------
    @property
    def position(self):
        return list(p.getBasePositionAndOrientation(self.body)[0])

    def distance_to(self, pos):
        a = self.position
        return sum((a[i] - pos[i]) ** 2 for i in range(3)) ** 0.5

    # -- physics helpers ---------------------------------------------------
    def freeze(self):
        """Pin the block in place (used while sitting in supply)."""
        p.resetBaseVelocity(self.body, [0, 0, 0], [0, 0, 0])

    def teleport(self, position, orientation=(0, 0, 0, 1)):
        p.resetBasePositionAndOrientation(self.body, list(position), list(orientation))
        p.resetBaseVelocity(self.body, [0, 0, 0], [0, 0, 0])

    def make_static(self):
        """Lock a placed block in place (mass 0) so nothing can knock it loose."""
        p.changeDynamics(self.body, -1, mass=0)

    def set_ghost(self):
        """Disable collisions while carried, so wide slabs don't jam the airspace."""
        p.setCollisionFilterGroupMask(self.body, -1, 0, 0)

    def set_solid(self):
        """Re-enable collisions (placed support or a block that was dropped)."""
        p.setCollisionFilterGroupMask(self.body, -1, 1, -1)

    def make_dynamic(self):
        """Restore physics mass (e.g. if a placed block must be re-handled)."""
        p.changeDynamics(self.body, -1, mass=self.spec["mass"])

    def to_state(self):
        return {
            "id": self.id,
            "position": self.position,
            "block_type": self.block_type,
            "state": self.state,
        }
