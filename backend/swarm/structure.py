"""Structural analysis — architectural soundness of a voxel blueprint.

Classifies every voxel by how it carries load, so the swarm can build in a
support-respecting order and connect (weld) each block to its neighbours:

    grounded     — sits on the board (y == 0); the foundation.
    stacked      — has a block directly beneath it; load goes straight down.
    cantilever   — no block beneath, but reaches a supported column through
                   in-layer neighbours within MAX_CANTILEVER steps; it is held
                   by adhesive joints to those neighbours (like a chair seat
                   spanning its legs).
    unsupported  — cannot reach support within the cantilever limit, or is a
                   floating island disconnected from the ground. Flagged so the
                   builder can scaffold or warn instead of placing a block that
                   could not physically stay up.
"""

from collections import deque

from backend import config

FACE_6 = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
PLANE_4 = [(1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1)]


def analyze(voxels):
    """Return per-voxel support classification + summary stats."""
    vset = {(v["x"], v["y"], v["z"]) for v in voxels}

    # --- connectivity to the ground (6-connected flood from y==0) ---
    connected = set()
    q = deque(v for v in vset if v[1] == 0)
    connected.update(q)
    while q:
        x, y, z = q.popleft()
        for dx, dy, dz in FACE_6:
            n = (x + dx, y + dy, z + dz)
            if n in vset and n not in connected:
                connected.add(n)
                q.append(n)

    # --- cantilever distance: per-layer BFS from columns with below-support ---
    # A voxel is a "support seed" in its layer if it is grounded or stacked.
    support_dist = {}
    layers = {}
    for v in vset:
        layers.setdefault(v[1], set()).add(v)
    for y, cells in layers.items():
        seeds = [c for c in cells if c[1] == 0 or (c[0], c[1] - 1, c[2]) in vset]
        dq = deque()
        for s in seeds:
            support_dist[s] = 0
            dq.append(s)
        while dq:
            x, yy, z = dq.popleft()
            for dx, _, dz in PLANE_4:
                n = (x + dx, yy, z + dz)
                if n in cells and n not in support_dist:
                    support_dist[n] = support_dist[(x, yy, z)] + 1
                    dq.append(n)

    classify = {}
    counts = {"grounded": 0, "stacked": 0, "cantilever": 0, "unsupported": 0}
    for v in vset:
        x, y, z = v
        if y == 0:
            t = "grounded"
        elif (x, y - 1, z) in vset:
            t = "stacked"
        else:
            d = support_dist.get(v)
            if v in connected and d is not None and d <= config.MAX_CANTILEVER:
                t = "cantilever"
            else:
                t = "unsupported"
        classify[v] = t
        counts[t] += 1

    unsupported = [v for v, t in classify.items() if t == "unsupported"]
    max_cantilever = max((support_dist.get(v, 0) for v, t in classify.items()
                          if t == "cantilever"), default=0)

    return {
        "classify": classify,
        "support_dist": support_dist,
        "counts": counts,
        "unsupported": unsupported,
        "max_cantilever": max_cantilever,
        "sound": len(unsupported) == 0,
    }


def orthogonal_neighbors(voxel):
    x, y, z = voxel
    return [(x + dx, y + dy, z + dz) for dx, dy, dz in FACE_6]
