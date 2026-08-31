"""Specialist / generalist role logic.

Roles:
    small       -> small_cube only
    large       -> large_slab only
    generalist  -> medium_brick (its specialty) + can cover any type

Reassignment (no mid-task reassignment — only when a drone goes idle):
    1. A drone finishes all work it can win normally.
    2. If specialist-only tasks remain and no matching specialist is free,
       an idle generalist is flagged to help — it bids at normal cost
       (no specialist discount) so it only wins when genuinely the best option.
"""

from backend import config

SPECIALIST_RULES = config.SPECIALIST_RULES


def role_can_handle(specialist_type: str, block_type: str) -> bool:
    return block_type in SPECIALIST_RULES[specialist_type]


def block_specialist(block_type: str) -> str:
    """The role that specialises in this block type."""
    return config.BLOCK_TYPES[block_type]["specialist_type"]


def needs_generalist_help(pending_tasks, idle_drones) -> bool:
    """True if specialist work is stranded because no matching specialist is free.

    A generalist that is idle can then step in as a helper.
    """
    idle_roles = {d.specialist_type for d in idle_drones}
    for task in pending_tasks:
        spec = task.block_type_specialist
        if spec == "generalist":
            continue  # generalists already handle these
        if spec not in idle_roles:
            # No free specialist for this block type -> a generalist should help.
            return True
    return False


def mark_reassigned_helpers(pending_tasks, idle_drones, events):
    """Flag idle generalists as helpers when specialist work is stranded."""
    if not needs_generalist_help(pending_tasks, idle_drones):
        return
    for drone in idle_drones:
        if drone.specialist_type == "generalist" and not drone.reassigned:
            drone.reassigned = True
            events.append(
                f"Drone {drone.id} reassigned as generalist helper "
                f"(specialist backlog)"
            )
