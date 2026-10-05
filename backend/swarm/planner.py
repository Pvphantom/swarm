"""Adaptive construction planner.

Turns a voxel occupancy blueprint into a set of real structural *pieces* —
cubes, beams and slabs — chosen so each piece is self-supporting when it rests
on what's beneath it:

  * a cube (1x1) only goes where it has support directly below,
  * a beam (1xN) spans a gap as long as it's footed near both ends,
  * a slab (MxN) rests on its supports like a tabletop on legs.

Support comes from the blueprint cell directly beneath a piece (or the ground);
a piece may span unsupported cells between its footings, up to an overhang
limit. Cells that can't be reached by any stable piece get a support column
added beneath them, so the structure is always buildable for real.

The planner is pure geometry (no physics / PyBullet), so it's easy to test.
"""

from collections import deque

from backend import config

MAXP = config.PIECE_MAX_SPAN        # longest side of a piece, in cells
OVER = config.PIECE_MAX_OVERHANG    # how far a piece may overhang its footing


def _piece_type(w, d):
    if w == 1 and d == 1:
        return "cube"
    if min(w, d) == 1:
        return "beam"
    return "slab"


def _stable(rect_cells, footed):
    """Is a rectangle self-supporting given the set of footed (x,z) cells?"""
    fcells = [c for c in rect_cells if c in footed]
    if not fcells:
        return False
    xs = [c[0] for c in rect_cells]
    zs = [c[1] for c in rect_cells]
    cx = (min(xs) + max(xs)) / 2.0
    cz = (min(zs) + max(zs)) / 2.0
    fxs = [c[0] for c in fcells]
    fzs = [c[1] for c in fcells]
    # Centre of mass must sit over the footing's span (won't tip)…
    if not (min(fxs) <= cx <= max(fxs) and min(fzs) <= cz <= max(fzs)):
        return False
    # …and no cell may overhang its nearest footing by more than the limit.
    for c in rect_cells:
        if min(max(abs(c[0] - f[0]), abs(c[1] - f[1])) for f in fcells) > OVER:
            return False
    return True


def _rect_cells(x0, z0, w, d):
    return [(x0 + i, z0 + j) for i in range(w) for j in range(d)]


def _largest_stable_rect(remaining, footed):
    """Greedy: the biggest stable rectangle fully inside `remaining`."""
    best = None
    best_area = 0
    for (x0, z0) in remaining:
        for w in range(min(MAXP, 1 + max(x for x, _ in remaining) - x0), 0, -1):
            for d in range(min(MAXP, 1 + max(z for _, z in remaining) - z0), 0, -1):
                cells = _rect_cells(x0, z0, w, d)
                if any(c not in remaining for c in cells):
                    continue
                if w * d <= best_area:
                    continue
                if _stable(cells, footed):
                    best, best_area = cells, w * d
    return best


def _region_dist_to_footing(region, footed):
    """BFS distance (in-layer, 4-connected) from footed cells to each region cell."""
    dist = {c: 0 for c in region if c in footed}
    q = deque(dist)
    while q:
        x, z = q.popleft()
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, z + dz)
            if n in region and n not in dist:
                dist[n] = dist[(x, z)] + 1
                q.append(n)
    return dist


def plan(voxels, dims):
    """Return (pieces, scaffold_cells, stats).

    pieces: list of dicts {cells, x0, z0, y, w, d, type, center, mass}
    """
    occ = {(v["x"], v["y"], v["z"]) for v in voxels}
    layers = sorted({c[1] for c in occ})
    scaffold = set()

    # --- Support pre-pass: add columns under cells no piece could reach. ---
    for y in layers:
        if y == 0:
            continue
        region = {(x, z) for (x, yy, z) in occ if yy == y}
        footed = {(x, z) for (x, z) in region if (x, y - 1, z) in occ}
        dist = _region_dist_to_footing(region, footed)
        for (x, z) in region:
            if dist.get((x, z), 99) > OVER:
                for yy in range(y - 1, -1, -1):
                    if (x, yy, z) in occ:
                        break
                    occ.add((x, yy, z))
                    scaffold.add((x, yy, z))

    # --- Decompose every layer into the largest stable pieces. ---
    pieces = []
    for y in layers:
        region = {(x, z) for (x, yy, z) in occ if yy == y}
        footed = {(x, z) for (x, z) in region if y == 0 or (x, y - 1, z) in occ}
        remaining = set(region)
        guard = 0
        while remaining and guard < 10000:
            guard += 1
            rect = _largest_stable_rect(remaining, footed)
            if rect is None:
                # Shouldn't happen after the pre-pass; drop a supported column
                # under the first cell as a safety net.
                x, z = next(iter(remaining))
                for yy in range(y - 1, -1, -1):
                    if (x, yy, z) in occ:
                        break
                    occ.add((x, yy, z))
                    scaffold.add((x, yy, z))
                footed.add((x, z))
                rect = [(x, z)]
            xs = [c[0] for c in rect]
            zs = [c[1] for c in rect]
            x0, z0 = min(xs), min(zs)
            w, d = max(xs) - x0 + 1, max(zs) - z0 + 1
            cx = (x0 + (w - 1) / 2.0 - dims["x"] / 2.0 + 0.5) * config.VOXEL_SIZE
            cz = (z0 + (d - 1) / 2.0 - dims["z"] / 2.0 + 0.5) * config.VOXEL_SIZE
            cy = y * config.VOXEL_SIZE + config.VOXEL_SIZE / 2.0
            pieces.append({
                "cells": [(x, y, z) for (x, z) in rect],
                "x0": x0, "z0": z0, "y": y, "w": w, "d": d,
                "type": _piece_type(w, d),
                "center": [cx, cy, cz],
                "mass": round(0.1 * w * d, 3),
            })
            remaining -= set(rect)

    counts = {}
    for p in pieces:
        counts[p["type"]] = counts.get(p["type"], 0) + 1
    stats = {
        "pieces": len(pieces),
        "voxels": len(occ),
        "by_type": counts,
        "scaffold": len(scaffold),
        "biggest": max((p["w"] * p["d"] for p in pieces), default=0),
    }
    return pieces, scaffold, stats
