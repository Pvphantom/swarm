"""Auction-based task allocation.

Decentralised-style allocation: every idle drone that *can* handle a task
computes a bid equal to its estimated travel cost. The lowest bid wins.
Specialists get a discount on their own block type, so they naturally win the
work they're tuned for; generalists win when no specialist is free or cheaper.
"""

import math

from backend import config


def distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


class TaskAllocator:
    def __init__(self, environment):
        self.env = environment

    def calculate_bid(self, drone, task):
        """Bid = travel to the block source + source-to-placement distance."""
        if task.recover_block is not None:
            source_pos = task.recover_block.position
        else:
            source_pos = self.env.supply_zones[task.block_type].position
        dist_to_supply = distance(drone.position, source_pos)
        dist_to_placement = distance(source_pos, task.placement_pos)
        return dist_to_supply + dist_to_placement

    def run_auction(self, task, available_drones):
        """Return the winning drone for `task`, or None if nobody can bid."""
        bids = {}
        for drone in available_drones:
            if not drone.can_handle(task.block_type):
                continue
            bid = self.calculate_bid(drone, task)
            # Specialists are faster on their own block type -> discount.
            if drone.specialist_type == task.block_type_specialist:
                bid *= config.SPECIALIST_DISCOUNT
            bids[drone] = bid

        if not bids:
            return None
        return min(bids, key=bids.get)
