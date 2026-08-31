"""Swarm orchestration.

Owns the drones, the task queue, and the per-physics-step control loop that:
  * auctions ready tasks to idle drones,
  * ticks each drone's control/FSM,
  * detects collisions and handles placement failures,
  * reassigns idle generalists to help with stranded specialist work.

`control_step()` is called once per PyBullet step by the runner; `env.step()`
is called right after by the runner.
"""

import math
import time

from backend import config
from backend.swarm import failure, specialist
from backend.swarm.allocator import TaskAllocator


class Task:
    _next = 0

    def __init__(self, voxel, block_type, placement_pos):
        self.id = Task._next
        Task._next += 1
        self.voxel = tuple(voxel)                       # (x, y, z) grid coords
        self.block_type = block_type
        self.block_type_specialist = config.BLOCK_TYPES[block_type]["specialist_type"]
        self.placement_pos = list(placement_pos)        # world-space centre

        self.assigned_drone = None
        self.block = None            # Block being carried for this task
        self.recover_block = None    # set when this is a dropped-block recovery
        self.attempts = 0
        self.exclude_drone = None    # drone id barred from re-attempting


class SwarmManager:
    def __init__(self, blueprint, environment):
        self.blueprint = blueprint
        self.env = environment
        self.allocator = TaskAllocator(environment)

        self.drones = []
        self.task_queue = []
        self.completed_tasks = []
        self.dropped_blocks = []
        self.events = []

        self.required_voxels = set()
        self.placed_voxels = set()
        self.total_tasks = 0
        self.robot_reasoning = {}
        self.current_layer = 0          # Litematica-style: build one Y-layer at a time
        self.layers = []                # sorted list of occupied Y layers

        self.stats = {"placed": 0, "dropped": 0, "collisions": 0}
        self.started_at = None
        self.finished = False

    # -- deployment --------------------------------------------------------
    def deploy_swarm(self):
        self.generate_tasks()
        count = self.calculate_robot_count()
        self.spawn_drones(count)
        self._replenish_supply()
        self.started_at = time.time()
        self.log(f"Swarm deployed: {count} drones for {self.total_tasks} blocks")
        return count

    def calculate_robot_count(self):
        voxels = self.blueprint["voxels"]
        n = len(voxels) or 1

        # Factor 1 — spatial distribution across build-footprint quadrants.
        xs = [v["x"] for v in voxels]
        zs = [v["z"] for v in voxels]
        midx = (min(xs) + max(xs)) / 2.0
        midz = (min(zs) + max(zs)) / 2.0
        quadrants = {(v["x"] > midx, v["z"] > midz) for v in voxels}
        spatial = len(quadrants)                     # 1..4

        # Factor 2 — time: aim for a handful of placements per drone.
        tasks_per_robot = 6
        time_factor = math.ceil(n / tasks_per_robot)

        # Factor 3 — block-type diversity (>=1 specialist per type).
        distinct = len({v["block_type"] for v in voxels})

        count = max(spatial, time_factor, distinct, 1)
        count = min(count, config.MAX_DRONES)

        self.robot_reasoning = {
            "spatial_quadrants": spatial,
            "time_factor": time_factor,
            "distinct_block_types": distinct,
            "chosen": count,
        }
        return count

    def spawn_drones(self, count):
        from backend.sim.drone import Drone

        present = {v["block_type"] for v in self.blueprint["voxels"]}
        roles = []
        # One specialist per present specialist block type, if budget allows.
        if "small_cube" in present:
            roles.append("small")
        if "large_slab" in present:
            roles.append("large")
        roles = roles[:count]
        while len(roles) < count:
            roles.append("generalist")
        # Guarantee a generalist when medium_brick is needed.
        if "medium_brick" in present and "generalist" not in roles and roles:
            roles[-1] = "generalist"

        for i, role in enumerate(roles):
            row = i % 5
            col = i // 5
            start = [
                config.STAGING_ORIGIN[0] + col * config.STAGING_SPACING,
                config.CRUISE_HEIGHT,
                config.STAGING_ORIGIN[2] + row * config.STAGING_SPACING,
            ]
            self.drones.append(Drone(i, role, start))

    def generate_tasks(self):
        grid_dim = self.blueprint["dimensions"]
        # Build bottom layers first so blocks have something to rest on.
        voxels = sorted(self.blueprint["voxels"], key=lambda v: (v["y"], v["x"], v["z"]))
        for v in voxels:
            world = config.voxel_to_world(v["x"], v["y"], v["z"], grid_dim)
            task = Task((v["x"], v["y"], v["z"]), v["block_type"], world)
            self.task_queue.append(task)
            self.required_voxels.add((v["x"], v["y"], v["z"]))
        self.total_tasks = len(self.task_queue)
        self.layers = sorted({v["y"] for v in voxels})
        self.current_layer = self.layers[0] if self.layers else 0

    def _replenish_supply(self):
        counts = {}
        for task in self.task_queue:
            counts[task.block_type] = counts.get(task.block_type, 0) + 1
        for block_type, n in counts.items():
            self.env.supply_zones[block_type].replenish(n)

    # -- per-step control loop --------------------------------------------
    def control_step(self):
        if self.finished:
            return
        self._allocate()

        for drone in self.drones:
            result = drone.tick(self.events)
            if result is None:
                continue
            task = drone.finished_task
            drone.finished_task = None
            if result == "placed":
                self.stats["placed"] += 1
                self.placed_voxels.add(task.voxel)
                self.completed_tasks.append(task)
            elif result == "place_failed":
                failure.handle_placement_failure(self, drone, task)

        failure.detect_collisions(self)
        self._advance_layer()
        self._reassign_check()
        self._trim_events()

        if (not self.task_queue
                and all(d.task is None for d in self.drones)
                and len(self.completed_tasks) >= self.total_tasks):
            if not self.finished:
                self.finished = True
                self.log("Build complete")

    def _allocate(self):
        idle = [d for d in self.drones if d.is_idle]
        if not idle or not self.task_queue:
            return
        # Only run as many drones at once as the space can absorb; piling every
        # drone into one cramped layer causes collisions without speeding things
        # up. Recovery work always gets a drone regardless of the cap.
        active = sum(1 for d in self.drones if d.task is not None)
        slots = max(0, min(config.MAX_CONCURRENT_BUILDERS, len(self.drones)) - active)

        for task in list(self.task_queue):
            if not idle:
                break
            if not self._task_ready(task):
                continue
            is_recovery = task.recover_block is not None
            if not is_recovery and slots <= 0:
                continue
            avail = [d for d in idle if d.id != task.exclude_drone] or idle
            winner = self.allocator.run_auction(task, avail)
            if winner is None:
                continue
            self.task_queue.remove(task)
            winner.assign_task(task, self.env)
            idle.remove(winner)
            if not is_recovery:
                slots -= 1
            tag = " (recovery)" if is_recovery else ""
            self.log(f"Task {task.voxel} {task.block_type}{tag} -> Drone {winner.id}")

    def _task_ready(self, task):
        # Recovery of a dropped block is always allowed (its voxel belongs to a
        # layer at or below the current one anyway).
        if task.recover_block is not None:
            return True
        # Strict layer-by-layer: only the current layer's voxels are buildable.
        return task.voxel[1] == self.current_layer

    def _advance_layer(self):
        """Advance to the next Y-layer once the current one is fully built."""
        pending = any(t.voxel[1] == self.current_layer for t in self.task_queue)
        active = any(d.task is not None and d.task.voxel[1] == self.current_layer
                     for d in self.drones)
        if pending or active:
            return
        remaining = sorted({t.voxel[1] for t in self.task_queue})
        if remaining and remaining[0] != self.current_layer:
            self.current_layer = remaining[0]
            self.log(f"Layer {self.current_layer} unlocked")

    def _reassign_check(self):
        idle = [d for d in self.drones if d.is_idle]
        if idle and self.task_queue:
            specialist.mark_reassigned_helpers(self.task_queue, idle, self.events)

    # -- helpers -----------------------------------------------------------
    def log(self, msg):
        self.events.append(msg)
        self._trim_events()

    def _trim_events(self):
        if len(self.events) > 60:
            del self.events[:-60]

    @property
    def elapsed(self):
        return round(time.time() - self.started_at, 1) if self.started_at else 0.0

    def status(self):
        in_progress = sum(1 for d in self.drones if d.task is not None)
        return {
            "total_tasks": self.total_tasks,
            "completed": len(self.completed_tasks),
            "in_progress": in_progress,
            "queued": len(self.task_queue),
            "finished": self.finished,
            "robot_count": len(self.drones),
            "current_layer": self.current_layer,
            "total_layers": len(self.layers),
            "robot_reasoning": self.robot_reasoning,
            "stats": {**self.stats, "elapsed": self.elapsed},
        }
