"""Blueprint processing.

Takes raw GPT-4o JSON (or the fallback) and returns a clean, validated
blueprint the swarm manager can consume:
  * clamps voxels to the grid, drops invalid / duplicate voxels,
  * counts blocks by type,
  * computes spatial-distribution metrics used for the robot-count decision.
"""

from backend import config

VALID_TYPES = set(config.BLOCK_TYPES.keys())


def process(raw: dict) -> dict:
    """Validate and enrich a raw blueprint dict."""
    voxels_in = raw.get("voxels", []) if isinstance(raw, dict) else []
    seen = set()
    voxels = []
    for v in voxels_in:
        try:
            x, y, z = int(v["x"]), int(v["y"]), int(v["z"])
        except (KeyError, TypeError, ValueError):
            continue
        bt = v.get("block_type", "small_cube")
        if bt not in VALID_TYPES:
            bt = "small_cube"
        if not (0 <= x < config.MAX_GRID and 0 <= y < config.MAX_GRID
                and 0 <= z < config.MAX_GRID):
            continue
        key = (x, y, z)
        if key in seen:
            continue
        seen.add(key)
        voxels.append({"x": x, "y": y, "z": z, "block_type": bt})

    if not voxels:
        # Nothing usable — hand back the demo so the pipeline still works.
        return build_demo_blueprint()

    xs = [v["x"] for v in voxels]
    ys = [v["y"] for v in voxels]
    zs = [v["z"] for v in voxels]
    dimensions = {
        "x": max(xs) + 1,
        "y": max(ys) + 1,
        "z": max(zs) + 1,
    }

    counts = {}
    for v in voxels:
        counts[v["block_type"]] = counts.get(v["block_type"], 0) + 1

    metrics = _spatial_metrics(voxels, xs, zs)

    return {
        "object_name": raw.get("object_name", "object") if isinstance(raw, dict) else "object",
        "dimensions": dimensions,
        "complexity_score": _complexity(raw, voxels, metrics),
        "voxels": voxels,
        "counts": counts,
        "metrics": metrics,
    }


def _spatial_metrics(voxels, xs, zs):
    midx = (min(xs) + max(xs)) / 2.0
    midz = (min(zs) + max(zs)) / 2.0
    quads = {}
    for v in voxels:
        q = (v["x"] > midx, v["z"] > midz)
        quads[q] = quads.get(q, 0) + 1
    footprint = (max(xs) - min(xs) + 1) * (max(zs) - min(zs) + 1)
    return {
        "occupied_quadrants": len(quads),
        "footprint_cells": footprint,
        "spread": round(len(quads) / 4.0, 2),
        "total_voxels": len(voxels),
    }


def _complexity(raw, voxels, metrics):
    if isinstance(raw, dict) and isinstance(raw.get("complexity_score"), (int, float)):
        return max(0.0, min(1.0, float(raw["complexity_score"])))
    # Derive from voxel count + spatial spread.
    vol = min(1.0, len(voxels) / 200.0)
    return round(0.6 * vol + 0.4 * metrics["spread"], 2)


def build_demo_blueprint() -> dict:
    """Deterministic Minecraft-style chair — used when no vision model is available."""
    voxels = []

    # Four legs (small_cube), two levels tall, at the footprint corners.
    for (x, z) in [(0, 0), (3, 0), (0, 3), (3, 3)]:
        for y in (0, 1):
            voxels.append({"x": x, "y": y, "z": z, "block_type": "small_cube"})

    # Seat (large_slab), full 4x4 footprint at y=2.
    for x in range(4):
        for z in range(4):
            voxels.append({"x": x, "y": 2, "z": z, "block_type": "large_slab"})

    # Backrest (medium_brick), at the back (z=0), two rows tall.
    for x in range(4):
        for y in (3, 4):
            voxels.append({"x": x, "y": y, "z": 0, "block_type": "medium_brick"})

    return process({"object_name": "chair", "voxels": voxels, "complexity_score": 0.6})
