"""Drone agent.

A drone is a small dynamic box driven by a PD controller with gravity
compensation, so it hovers and flies smoothly without a full flight-dynamics
model (the spec's "pure PyBullet force application"). It carries blocks with a
fixed constraint and runs a self-contained task state machine that the swarm
manager feeds one task at a time.

State machine (one task):
    IDLE -> MOVING_TO_SUPPLY -> PICKING_UP -> CARRYING ->
    MOVING_TO_PLACEMENT -> PLACING -> RETURNING -> IDLE
"""

import pybullet as p

from backend import config

GRAV = 9.81

# High-level FSM states (also streamed to the frontend).
IDLE = "IDLE"
MOVING_TO_SUPPLY = "MOVING_TO_SUPPLY"
PICKING_UP = "PICKING_UP"
CARRYING = "CARRYING"
MOVING_TO_PLACEMENT = "MOVING_TO_PLACEMENT"
PLACING = "PLACING"
RETURNING = "RETURNING"
AVOIDING = "AVOIDING"


class Drone:
    def __init__(self, drone_id: int, specialist_type: str, start_pos):
        self.id = drone_id
        self.specialist_type = specialist_type          # small / large / generalist
        # Each drone cruises in its own altitude lane so airborne drones don't
        # collide just by sharing a corridor; collisions then only happen when
        # two drones descend onto the same spot (which is what we want to show).
        self.lane = config.CRUISE_HEIGHT + drone_id * 0.08
        # Small per-drone XZ offset so two drones hovering over the same target
        # don't stack at the exact same point.
        self.hover_off = ((drone_id % 3 - 1) * 0.06, (drone_id // 3 % 3 - 1) * 0.06)
        self.home = [start_pos[0], self.lane, start_pos[2]]
        self._avoid_target = list(self.home)

        self.state = IDLE
        self.task = None                 # current Task (duck-typed)
        self.carrying_block = None       # Block instance while carrying
        self.carrying_block_type = None  # streamed to frontend
        self._constraint = None

        self._phase = 0                  # sub-phase within pick/place
        self._settle = 0                 # settle countdown for placement check
        self._pt = 0                     # ticks spent in current (state, phase)
        self._last_key = None
        self.finished_task = None        # task that just terminated (for manager)
        self._waypoint = list(start_pos)
        self.collision_flash = 0         # frames of "flash" for the frontend
        self._collision_cd = 0           # cooldown so collisions don't cascade
        self._held_zone = None           # supply zone currently reserved
        self.reassigned = False          # generalist covering a specialist gap

        half = config.DRONE_HALF_EXTENTS
        # Colour tint by role so the frontend can distinguish them.
        tint = {
            "cube": [0.55, 0.75, 1.0, 1.0],
            "beam": [1.0, 0.72, 0.5, 1.0],
            "slab": [0.6, 1.0, 0.72, 1.0],
            "generalist": [0.85, 0.85, 1.0, 1.0],
        }.get(specialist_type, [0.85, 0.85, 1.0, 1.0])
        col = p.createCollisionShape(p.GEOM_BOX, halfExtents=half)
        vis = p.createVisualShape(p.GEOM_BOX, halfExtents=half, rgbaColor=tint)
        self.body = p.createMultiBody(
            baseMass=config.DRONE_MASS,
            baseCollisionShapeIndex=col,
            baseVisualShapeIndex=vis,
            basePosition=list(start_pos),
        )
        p.changeDynamics(self.body, -1, linearDamping=0.6, angularDamping=0.9)
        # Drones are physical ghosts: their collisions are detected by the
        # manager's distance check, so they never physically knock the structure.
        p.setCollisionFilterGroupMask(self.body, -1, 0, 0)

    # -- queries -----------------------------------------------------------
    @property
    def position(self):
        return list(p.getBasePositionAndOrientation(self.body)[0])

    @property
    def is_idle(self):
        return self.state == IDLE and self.task is None

    def can_handle(self, block_type: str) -> bool:
        return block_type in config.SPECIALIST_RULES[self.specialist_type]

    # -- low-level control -------------------------------------------------
    def _apply_pd(self, target):
        """One PD control step toward `target`, with gravity compensation."""
        pos, _ = p.getBasePositionAndOrientation(self.body)
        lin, _ = p.getBaseVelocity(self.body)

        carried_mass = self.carrying_block.mass if self.carrying_block else 0.0
        total_mass = config.DRONE_MASS + carried_mass

        force = [0.0, total_mass * GRAV, 0.0]           # hover / anti-gravity
        for i in range(3):
            err = target[i] - pos[i]
            force[i] += config.PD_KP * err - config.PD_KD * lin[i]

        # Clamp force magnitude so the drone can't teleport.
        mag = sum(f * f for f in force) ** 0.5
        if mag > config.MAX_DRONE_FORCE:
            scale = config.MAX_DRONE_FORCE / mag
            force = [f * scale for f in force]

        p.applyExternalForce(self.body, -1, force, pos, p.WORLD_FRAME)

        # Keep the drone level and non-spinning (kinematic rotation lock).
        p.resetBasePositionAndOrientation(self.body, list(pos), [0, 0, 0, 1])
        p.resetBaseVelocity(self.body, list(lin), [0, 0, 0])

    def _reached(self, target, tol=None):
        tol = config.ARRIVAL_TOLERANCE if tol is None else tol
        pos = self.position
        d2 = sum((pos[i] - target[i]) ** 2 for i in range(3))
        return d2 <= tol * tol

    def move_to(self, target_pos):
        """Set a cruise waypoint (state left to the manager/FSM)."""
        self._waypoint = list(target_pos)

    # -- pick / place primitives ------------------------------------------
    def pick_up(self, block):
        """Attach `block` to the drone with a fixed constraint."""
        self.carrying_block = block
        self.carrying_block_type = block.block_type
        block.state = "carried"
        block.set_ghost()   # no collisions while carried -> no airspace jams
        # Snap the block to the carry point for a clean grab regardless of where
        # it was sitting in the supply stack.
        pos = self.position
        block.teleport([pos[0], pos[1] - config.CARRY_OFFSET, pos[2]])
        self._constraint = p.createConstraint(
            parentBodyUniqueId=self.body,
            parentLinkIndex=-1,
            childBodyUniqueId=block.body,
            childLinkIndex=-1,
            jointType=p.JOINT_FIXED,
            jointAxis=[0, 0, 0],
            parentFramePosition=[0, -config.CARRY_OFFSET, 0],
            childFramePosition=[0, 0, 0],
        )
        p.changeConstraint(self._constraint, maxForce=300)

    def place_block(self, target_pos):
        """Release the carried piece aligned over its target; it settles onto its
        supports under real gravity (no snap-lock, no welding)."""
        block = self.carrying_block
        if self._constraint is not None:
            p.removeConstraint(self._constraint)
            self._constraint = None
        if block is not None:
            # Align over the target and release just above the supports.
            block.teleport([target_pos[0], target_pos[1] + config.RELEASE_GAP, target_pos[2]])
            block.set_solid()
            block.make_dynamic()   # real rigid body held up by its supports
            block.state = "placed"
            block.target_pos = list(target_pos)
        self.carrying_block = None
        self.carrying_block_type = None
        return block

    def drop_block(self):
        """Emergency release (collision). Block keeps its momentum and falls."""
        block = self.carrying_block
        if self._constraint is not None:
            p.removeConstraint(self._constraint)
            self._constraint = None
        if block is not None:
            block.set_fall_clear()   # falls past the structure to the floor
            block.state = "dropped"
        self.carrying_block = None
        self.carrying_block_type = None
        return block

    def handle_collision(self, avoidance_pos):
        """React to a collision: drop any block, flee to an avoidance point."""
        self.collision_flash = 12
        self._collision_cd = config.COLLISION_COOLDOWN
        self._release_zone()
        dropped = None
        if self.carrying_block is not None:
            dropped = self.drop_block()
        # Interrupt whatever we were doing; drift to a nearby safe spot in our
        # own lane, then go idle to re-bid — no need to trek all the way home.
        self._avoid_target = [avoidance_pos[0], self.lane, avoidance_pos[2]]
        self.state = AVOIDING
        self.task = None
        self._phase = 0
        return dropped

    # -- task lifecycle ----------------------------------------------------
    def assign_task(self, task, env):
        self.task = task
        self._env = env
        self._phase = 0
        self.state = MOVING_TO_SUPPLY
        task.assigned_drone = self.id

    def _above(self, pos, height=None):
        h = self.lane if height is None else height
        return [pos[0] + self.hover_off[0], h, pos[2] + self.hover_off[1]]

    def tick(self, events):
        """Advance one control step. `events` is a list to append log strings to.

        Returns a status string when a task terminal event occurs:
        "placed", "place_failed", or None otherwise.
        """
        if self.collision_flash > 0:
            self.collision_flash -= 1
        if self._collision_cd > 0:
            self._collision_cd -= 1

        # Track how long we've been in the current (state, phase) so descend
        # phases can time out instead of fighting neighbouring blocks forever.
        key = (self.state, self._phase)
        self._pt = 0 if key != self._last_key else self._pt + 1
        self._last_key = key

        if self.state == IDLE:
            # Park at the staging area, out of the active build zone. Allocation
            # runs every step, so a drone that's needed is reassigned before it
            # drifts far.
            self._apply_pd(self.home)
            return None

        if self.state == RETURNING:
            self._apply_pd(self.home)
            if self._reached(self.home, tol=0.12):
                self.state = IDLE
            return None

        if self.state == AVOIDING:
            self._apply_pd(self._avoid_target)
            if self._reached(self._avoid_target, tol=0.12):
                self.state = IDLE
            return None

        task = self.task
        if task is None:
            self.state = IDLE
            return None

        # ---- fly to the pickup point ------------------------------------
        if self.state == MOVING_TO_SUPPLY:
            if task.recover_block is not None:
                pickup_xz = task.recover_block.position
            else:
                pickup_xz = self._env.supply_zones[task.piece_type].position
            self._pickup_xz = pickup_xz
            self._apply_pd(self._above(pickup_xz))
            if self._reached(self._above(pickup_xz), tol=0.08):
                self.state = PICKING_UP
                self._phase = 0
            return None

        # ---- descend, grab, ascend --------------------------------------
        if self.state == PICKING_UP:
            return self._tick_pick(task, events)

        # ---- carry to placement -----------------------------------------
        if self.state in (CARRYING, MOVING_TO_PLACEMENT):
            self.state = MOVING_TO_PLACEMENT
            over_target = self._above(task.placement_pos)
            self._apply_pd(over_target)
            if self._reached(over_target, tol=0.06):
                self.state = PLACING
                self._phase = 0
            return None

        # ---- descend, release, verify -----------------------------------
        if self.state == PLACING:
            return self._tick_place(task, events)

        return None

    def _tick_pick(self, task, events):
        block_pos = self._pickup_xz
        from_supply = task.recover_block is None
        zone = self._env.supply_zones[task.piece_type] if from_supply else None

        if self._phase == 0:
            # Serialise supply pickups: wait in-lane above the bin until it's
            # free, so drones don't pile into the same zone at once.
            if from_supply and not zone.try_acquire(self.id):
                self._apply_pd(self._above(block_pos))
                return None
            if from_supply:
                self._held_zone = zone
            # Shallow dip toward the block (drones stay high, keeping their
            # altitude lanes separated so they rarely collide).
            grab_y = max(config.GRAB_HEIGHT, self.lane - 0.14, block_pos[1] + config.CARRY_OFFSET)
            descend = [block_pos[0], grab_y, block_pos[2]]
            self._apply_pd(descend)
            if self._reached(descend, tol=0.06) or self._pt > config.DESCEND_TIMEOUT:
                self._phase = 1
            return None
        if self._phase == 1:
            block = task.recover_block if not from_supply else zone.take(task.w, task.d)
            self.pick_up(block)
            task.block = block
            self._phase = 2
            return None
        # phase 2: ascend back to lane, then release the supply zone
        self._apply_pd(self._above(block_pos))
        if self._reached(self._above(block_pos), tol=0.08):
            self._release_zone()
            self.state = CARRYING
        return None

    def _release_zone(self):
        if self._held_zone is not None:
            self._held_zone.release(self.id)
            self._held_zone = None

    def _tick_place(self, task, events):
        target = task.placement_pos
        if self._phase == 0:
            # Dip toward the target, staying high enough to keep lane separation.
            drop_y = max(self.lane - 0.14, target[1] + config.CARRY_OFFSET + config.RELEASE_GAP)
            drop_pt = [target[0], drop_y, target[2]]
            self._apply_pd(drop_pt)
            if self._reached(drop_pt, tol=0.05) or self._pt > config.DESCEND_TIMEOUT:
                self._phase = 1
            return None
        # phase 1: release the piece onto its supports (real gravity) and COMMIT
        # immediately — once it's down, the placement is done, so a later
        # collision can't orphan it or cause a double-placement. The manager
        # lets it settle and then sets it.
        self.place_block(target)
        self.state = IDLE
        done_task = self.task
        self.finished_task = done_task
        self.task = None
        events.append(f"Drone {self.id} set {done_task.label()} on layer {done_task.layer}")
        return "placed"

    # -- streaming ---------------------------------------------------------
    def to_state(self):
        return {
            "id": self.id,
            "position": self.position,
            "state": self.state,
            "carrying": self.carrying_block_type,
            "specialist_type": self.specialist_type,
            "reassigned": self.reassigned,
            "collision_flash": self.collision_flash > 0,
        }
