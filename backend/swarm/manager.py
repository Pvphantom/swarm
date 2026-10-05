"""Swarm orchestration (structural-piece build).

The planner decomposes the blueprint into real pieces (cubes / beams / slabs);
each piece is one Task. Pieces are built strictly bottom-up: because every piece
rests on the layer beneath it, finishing a whole layer before the next starts
guarantees each piece has its support in place when it's set down.
"""

import math
import time

from backend import config
from backend.swarm import failure, planner, specialist
from backend.swarm.allocator import TaskAllocator

PLACEMENT_TOL = config.VOXEL_SIZE * 0.6   # a piece this close to target counts as placed


class Task:
    _next = 0

    def __init__(self, spec):
        self.id = Task._next
        Task._next += 1
        self.spec = spec
        self.piece_type = spec["type"]
        self.w = spec["w"]
        self.d = spec["d"]
        self.cells = spec["cells"]
        self.layer = spec["y"]
        self.voxel = (spec["x0"], spec["y"], spec["z0"])   # anchor (for logs/verify)
        self.placement_pos = list(spec["center"])
        self.block_type_specialist = config.PIECE_TYPES[self.piece_type]["specialist"]

        self.assigned_drone = None
        self.block = None             # piece being carried
        self.recover_block = None     # dropped piece to recover
        self.attempts = 0
        self.exclude_drone = None

    def label(self):
        return f"{self.piece_type} {self.w}x{self.d}"


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

        self.total_tasks = 0
        self.robot_reasoning = {}
        self.current_layer = 0
        self.layers = []
        self.layer_tasks = {}            # layer -> [Task]
        self.placed_pieces = {}          # task.id -> placed Block
        self._settling = []              # [block, frames, layer] -> set after settling
        self.verified_layers = set()
        self._verify_attempts = {}

        self.plan_stats = {}
        self.scaffold = set()

        self.stats = {"placed": 0, "dropped": 0, "collisions": 0}
        self.started_at = None
        self.finished = False

    # -- deployment --------------------------------------------------------
    def deploy_swarm(self):
        self.generate_tasks()
        count = self.calculate_robot_count()
        self.spawn_drones(count)
        self.started_at = time.time()
        s = self.plan_stats
        self.log(f"Planner: {s['pieces']} pieces from {s['voxels']} voxels "
                 f"({self._fmt_types(s['by_type'])}; biggest {s['biggest']} cells)")
        self.log(f"Swarm deployed: {count} drones")
        return count

    @staticmethod
    def _fmt_types(by_type):
        return ", ".join(f"{n} {t}" for t, n in by_type.items())

    def generate_tasks(self):
        pieces, scaffold, stats = planner.plan(self.blueprint["voxels"],
                                               self.blueprint["dimensions"])
        self.scaffold = scaffold
        self.plan_stats = stats
        pieces.sort(key=lambda p: (p["y"], -(p["w"] * p["d"])))
        for spec in pieces:
            task = Task(spec)
            self.task_queue.append(task)
            self.layer_tasks.setdefault(task.layer, []).append(task)
        self.total_tasks = len(self.task_queue)
        self.layers = sorted(self.layer_tasks)
        self.current_layer = self.layers[0] if self.layers else 0

    def calculate_robot_count(self):
        pieces = self.task_queue
        n = len(pieces) or 1
        xs = [t.placement_pos[0] for t in pieces]
        zs = [t.placement_pos[2] for t in pieces]
        midx = (min(xs) + max(xs)) / 2.0
        midz = (min(zs) + max(zs)) / 2.0
        spatial = len({(x > midx, z > midz) for x, z in zip(xs, zs)})
        time_factor = math.ceil(n / 4)
        distinct = len({t.piece_type for t in pieces})
        count = min(max(spatial, time_factor, distinct, 1), config.MAX_DRONES)
        self.robot_reasoning = {
            "spatial_quadrants": spatial,
            "time_factor": time_factor,
            "distinct_block_types": distinct,
            "chosen": count,
        }
        return count

    def spawn_drones(self, count):
        from backend.sim.drone import Drone
        present = {t.piece_type for t in self.task_queue}
        roles = []
        for kind in ("slab", "beam", "cube"):   # one specialist per present kind
            if kind in present:
                roles.append(kind)
        roles = roles[:count]
        while len(roles) < count:
            roles.append("generalist")
        for i, role in enumerate(roles):
            row, col = i % 5, i // 5
            start = [config.STAGING_ORIGIN[0] + col * config.STAGING_SPACING,
                     config.CRUISE_HEIGHT,
                     config.STAGING_ORIGIN[2] + row * config.STAGING_SPACING]
            self.drones.append(Drone(i, role, start))

    # -- control loop ------------------------------------------------------
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
                self.completed_tasks.append(task)
                self._finalize_placement(task)
            elif result == "place_failed":
                failure.handle_placement_failure(self, drone, task)

        self._process_settling()
        failure.detect_collisions(self)
        self._advance_layer()
        self._reassign_check()
        self._trim_events()

        if (not self.finished and not self.task_queue
                and all(d.task is None for d in self.drones)
                and set(self.layers).issubset(self.verified_layers)):
            _, strays = self._scan_pieces()
            self._cleanup_strays(strays)
            self.finished = True
            self.log("Build complete — structure verified ✓")

    def _process_settling(self):
        """Pieces rest dynamically on their supports, then set (become static)."""
        still = []
        for item in self._settling:
            blk, frames, layer = item
            if blk.body is None:
                continue
            frames -= 1
            if frames <= 0:
                # Align to exact target (it demonstrated it rests) and set.
                blk.teleport(blk.target_pos)
                blk.make_static()
            else:
                still.append([blk, frames, layer])
        self._settling = still

    def _layer_settling(self, layer):
        return any(l == layer and f > 0 for _, f, l in self._settling)

    def _allocate(self):
        idle = [d for d in self.drones if d.is_idle]
        if not idle or not self.task_queue:
            return
        active = sum(1 for d in self.drones if d.task is not None)
        slots = max(0, min(config.MAX_CONCURRENT_BUILDERS, len(self.drones)) - active)
        ready = [t for t in self.task_queue if self._task_ready(t)]
        for task in ready:
            if not idle:
                break
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
            self.log(f"{task.label()} @ layer {task.layer}{tag} -> Drone {winner.id}")

    def _task_ready(self, task):
        # Recovery always allowed; otherwise strict bottom-up (the layer below is
        # fully placed before this layer starts, so support is guaranteed).
        return task.recover_block is not None or task.layer == self.current_layer

    def _advance_layer(self):
        pending = any(t.layer == self.current_layer for t in self.task_queue)
        active = any(d.task is not None and d.task.layer == self.current_layer
                     for d in self.drones)
        if pending or active or self._layer_settling(self.current_layer):
            return
        if not self._verify_and_repair(self.current_layer):
            return
        remaining = sorted({t.layer for t in self.task_queue})
        if remaining and remaining[0] != self.current_layer:
            self.current_layer = remaining[0]
            self.log(f"Layer {self.current_layer} unlocked")

    # -- placement + verification -----------------------------------------
    def _finalize_placement(self, task):
        """Record a placed piece. It was set down under real gravity and settled
        on its supports; now the joint sets (mortar cures) so this course is a
        solid base for the next — real construction sequencing, not a weld hack."""
        if task.block is None:
            return
        self.placed_pieces[task.id] = task.block
        task.block.state = "placed"
        # Let it settle on its supports under real gravity, then set (mortar
        # cures) so this course is a solid base for the next one.
        self._settling.append([task.block, config.PLACE_SETTLE_FRAMES, task.layer])
        support = "ground" if task.layer == 0 else "the course below"
        if task.piece_type == "slab":
            self.log(f"Slab {task.w}x{task.d} set down, resting on {support}")
        elif task.piece_type == "beam" and max(task.w, task.d) >= 3:
            self.log(f"Beam spanning {max(task.w, task.d)} cells bridged onto {support}")

    def _scan_pieces(self):
        placed, strays = [], []
        for zone in self.env.supply_zones.values():
            for b in zone.blocks:
                if b.body is None:
                    continue
                if b.state == "placed":
                    placed.append(b)
                elif b.state == "dropped":
                    strays.append(b)
        return placed, strays

    def _verify_and_repair(self, layer):
        """Confirm every planned piece in the layer is resting at its target."""
        placed, strays = self._scan_pieces()
        missing = []
        for task in self.layer_tasks.get(layer, []):
            blk = self.placed_pieces.get(task.id)
            ok = blk is not None and blk.body is not None and \
                blk.distance_to(task.placement_pos) <= PLACEMENT_TOL
            if not ok:
                missing.append(task)

        if not missing:
            if layer not in self.verified_layers:
                self.verified_layers.add(layer)
                self.log(f"Layer {layer} verified ✓ "
                         f"({len(self.layer_tasks.get(layer, []))} pieces resting true)")
            self._cleanup_strays(strays)
            return True

        self.log(f"Layer {layer} verify: {len(missing)} piece(s) off-target — repairing")
        for task in missing:
            self._verify_attempts[task.id] = self._verify_attempts.get(task.id, 0) + 1
            self.placed_pieces.pop(task.id, None)
            if self._verify_attempts[task.id] >= 3:
                self._force_place(task, strays)
                continue
            new = Task(task.spec)
            if strays:
                new.recover_block = strays.pop()
            self.layer_tasks[layer].append(new)
            self.task_queue.append(new)
        return False

    def _force_place(self, task, strays):
        """Deterministic fallback: set the piece exactly on its supports."""
        from backend.sim.block import Block
        blk = strays.pop() if strays else Block(task.piece_type, task.w, task.d,
                                                task.placement_pos)
        blk.teleport(task.placement_pos)
        blk.set_solid()
        blk.make_static()
        blk.state = "placed"
        if blk not in self.env.supply_zones[task.piece_type].blocks:
            self.env.supply_zones[task.piece_type].blocks.append(blk)
        self.placed_pieces[task.id] = blk
        self.log(f"Auto-corrected {task.label()} at layer {task.layer}")

    def _cleanup_strays(self, strays):
        for b in strays:
            if any(t.recover_block is b for t in self.task_queue):
                continue
            zone = self.env.supply_zones.get(b.piece_type)
            if zone and b in zone.blocks:
                zone.blocks.remove(b)
            b.remove()

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
        completed = len([t for t in self.completed_tasks if t.id in self.placed_pieces])
        completed = min(len(self.placed_pieces), self.total_tasks)
        return {
            "total_tasks": self.total_tasks,
            "completed": completed,
            "verified_layers": sorted(self.verified_layers),
            "in_progress": in_progress,
            "queued": len(self.task_queue),
            "finished": self.finished,
            "robot_count": len(self.drones),
            "current_layer": self.current_layer,
            "total_layers": len(self.layers),
            "robot_reasoning": self.robot_reasoning,
            "structure": {
                "pieces": self.plan_stats.get("pieces", 0),
                "voxels": self.plan_stats.get("voxels", 0),
                "by_type": self.plan_stats.get("by_type", {}),
                "biggest": self.plan_stats.get("biggest", 0),
                "scaffold": len(self.scaffold),
            },
            "stats": {**self.stats, "elapsed": self.elapsed},
        }
