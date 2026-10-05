"""Supply feeders — one holographic, infinite feeder per piece kind.

No physical piece exists until a drone collects one. `take()` materialises a
piece of the exact shape the task needs at the feeder; the frontend shows a
hologram in the meantime. Nothing can pile up or explode on spawn.
"""

from backend import config
from backend.sim.block import Block


class SupplyZone:
    def __init__(self, piece_type, position):
        self.block_type = piece_type       # "cube" | "beam" | "slab"
        self.piece_type = piece_type
        self.position = list(position)
        self.blocks = []                   # pieces that have been collected
        self.occupants = set()
        self.capacity = 2
        self.dispensed = 0

    def replenish(self, count):
        return  # holographic + infinite

    def take(self, w=1, d=1):
        """Materialise a piece of shape (w x d) of this kind at the feeder."""
        center = [self.position[0], config.VOXEL_SIZE / 2.0 + 0.2, self.position[2]]
        piece = Block(self.piece_type, w, d, center, state="supply")
        self.blocks.append(piece)
        self.dispensed += 1
        return piece

    # -- occupancy ---------------------------------------------------------
    def try_acquire(self, drone_id):
        if drone_id in self.occupants or len(self.occupants) < self.capacity:
            self.occupants.add(drone_id)
            return True
        return False

    def release(self, drone_id):
        self.occupants.discard(drone_id)

    def to_state(self):
        return {
            "piece_type": self.piece_type,
            "position": self.position,
            "available": "inf",
            "dispensed": self.dispensed,
            "hologram": True,
        }
