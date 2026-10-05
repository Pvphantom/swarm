"""Failure handling: drone-drone collisions and placement failures.

These functions operate on the SwarmManager (passed in) and mutate its task
queue / counters. Kept dependency-light so there's no import cycle with the
manager.
"""

import math

from backend import config


def _distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def detect_collisions(manager):
    """Detect near-collisions between active drones and recover from them.

    A carrying drone drops its block (which becomes a high-priority recovery
    task); both drones flee to opposite avoidance points.
    """
    drones = manager.drones
    events = manager.events

    for i in range(len(drones)):
        for j in range(i + 1, len(drones)):
            d1, d2 = drones[i], drones[j]
            if d1._collision_cd or d2._collision_cd:
                continue
            # Parked/idle drones at the staging area don't count.
            if d1.state == "IDLE" and d2.state == "IDLE":
                continue

            p1, p2 = d1.position, d2.position
            # Drones cruise in separate altitude lanes; only treat them as
            # colliding when they're genuinely at the same height (e.g. two
            # drones whose paths cross in adjacent lanes over the same spot).
            if abs(p1[1] - p2[1]) > config.COLLISION_HEIGHT_GATE:
                continue
            if _distance(p1, p2) >= config.COLLISION_DISTANCE:
                continue

            # Vector to push them apart (fall back to x-axis if coincident).
            dx = [p1[k] - p2[k] for k in range(3)]
            norm = math.sqrt(sum(c * c for c in dx)) or 1.0
            unit = [c / norm for c in dx]
            step = config.AVOIDANCE_STEP
            avoid1 = [p1[0] + unit[0] * step, config.CRUISE_HEIGHT, p1[2] + unit[2] * step]
            avoid2 = [p2[0] - unit[0] * step, config.CRUISE_HEIGHT, p2[2] - unit[2] * step]

            manager.stats["collisions"] += 1
            events.append(f"Drone {d1.id} collided with Drone {d2.id}")

            for drone, avoid in ((d1, avoid1), (d2, avoid2)):
                task = drone.task
                dropped = drone.handle_collision(avoid)
                if dropped is not None:
                    manager.stats["dropped"] += 1
                    events.append(
                        f"Drone {drone.id} dropped {dropped.block_type}; "
                        f"recovery task queued"
                    )
                    if task is not None:
                        task.recover_block = dropped
                        _requeue_front(manager, task)
                    else:
                        manager.dropped_blocks.append(dropped)
                elif task is not None:
                    # Interrupted before pickup — just retry. Keep recover_block
                    # intact: if this was a recovery task, the dropped block it
                    # targets is still on the ground and must not be orphaned
                    # (clearing it here caused a fresh block to be dispensed and
                    # the old one to be abandoned as a stray).
                    _requeue_front(manager, task)


def _requeue_front(manager, task):
    task.assigned_drone = None
    task.block = None
    manager.task_queue.insert(0, task)


def handle_placement_failure(manager, drone, task):
    """A placed block missed tolerance. Retry once, then reassign to another drone."""
    events = manager.events
    task.attempts += 1
    task.assigned_drone = None
    # Re-use the block we just placed instead of drawing a fresh one from
    # supply (which would leave a stray block and drain the bin).
    if task.block is not None:
        task.recover_block = task.block
        task.block.state = "dropped"
    task.block = None

    if task.attempts >= config.MAX_PLACEMENT_RETRIES + 1:
        task.exclude_drone = drone.id           # force a different drone
        events.append(
            f"Task at voxel {task.voxel} reassigned away from Drone {drone.id} "
            f"after {task.attempts} attempts"
        )
    else:
        events.append(
            f"Drone {drone.id} retrying placement at voxel {task.voxel}"
        )

    if task.attempts >= 6:
        # Drop the task after repeated failures; the per-layer verifier will
        # detect the missing cell and repair it (ultimately force-placing it),
        # so we never falsely mark a voxel as done.
        events.append(f"Task at voxel {task.voxel} dropped — verifier will repair")
        return

    manager.task_queue.insert(0, task)
