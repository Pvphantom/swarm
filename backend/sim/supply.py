"""Supply zones — one staging area per block type.

Each zone pre-spawns the exact number of blocks the blueprint needs, arranged
in a neat stack so the frontend can render a visible "parts bin". Drones grab
the top-most available block when they arrive.
"""

import pybullet as p

from backend import config
from backend.sim.block import Block


class SupplyZone:
    def __init__(self, block_type: str, position):
        self.block_type = block_type
        self.position = list(position)
        self.blocks = []          # all blocks ever spawned here
        self._available = []      # blocks still waiting to be collected
        self.occupants = set()    # drone ids currently picking (small capacity)
        self.capacity = 2

    def replenish(self, count: int):
        """Spawn `count` blocks stacked above the zone origin."""
        cell = config.VOXEL_SIZE
        for i in range(count):
            # Stack in a short 3-wide grid so tall blueprints don't tower.
            row = i // 3
            col = i % 3
            pos = [
                self.position[0] + (col - 1) * cell * 1.2,
                self.position[1] + cell / 2.0 + row * cell,
                self.position[2] + 0.0,
            ]
            block = Block(self.block_type, pos, state="supply")
            block.freeze()
            self.blocks.append(block)
            self._available.append(block)

    def take(self):
        """Hand out the next available block, spawning one if the bin ran dry."""
        while self._available:
            block = self._available.pop()
            if block.state == "supply":
                return block
        # Parts feeder: never let an empty bin stall the build.
        block = Block(self.block_type, [self.position[0], config.VOXEL_SIZE, self.position[2]],
                      state="supply")
        block.freeze()
        self.blocks.append(block)
        return block

    # -- occupancy (serialises pickups so drones don't pile into one bin) ---
    def try_acquire(self, drone_id):
        if drone_id in self.occupants or len(self.occupants) < self.capacity:
            self.occupants.add(drone_id)
            return True
        return False

    def release(self, drone_id):
        self.occupants.discard(drone_id)

    @property
    def available_count(self):
        return sum(1 for b in self._available if b.state == "supply")

    def to_state(self):
        return {
            "block_type": self.block_type,
            "position": self.position,
            "available": self.available_count,
        }
