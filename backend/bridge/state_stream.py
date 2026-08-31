"""PyBullet state -> JSON snapshot for the websocket stream.

Called by the simulation runner every STEPS_PER_STREAM physics steps (30fps).
Produces the full world snapshot the Three.js frontend consumes.
"""

import time


def get_world_state(manager, env) -> dict:
    blocks = []
    for zone in env.supply_zones.values():
        for block in zone.blocks:
            blocks.append(block.to_state())

    status = manager.status()
    dropped_recoveries = (
        sum(1 for t in manager.task_queue if t.recover_block is not None)
        + len(manager.dropped_blocks)
    )

    return {
        "timestamp": time.time(),
        "drones": [d.to_state() for d in manager.drones],
        "blocks": blocks,
        "build_progress": {
            "total_tasks": status["total_tasks"],
            "completed": status["completed"],
            "in_progress": status["in_progress"],
            "queued": status["queued"],
            "dropped_recoveries": dropped_recoveries,
            "current_layer": status["current_layer"],
            "total_layers": status["total_layers"],
        },
        "stats": status["stats"],
        "robot_reasoning": status["robot_reasoning"],
        "supply": {bt: z.to_state() for bt, z in env.supply_zones.items()},
        "events": manager.events[-14:],
        "finished": manager.finished,
    }
