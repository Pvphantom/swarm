// Block mesh rendering — colour by type, appearance by state, smooth motion.
import * as THREE from "three";
import { S, WORLD_SCALE, BLOCK_COLORS } from "./scene.js";

const DIMS = {
  small_cube: [0.1, 0.1, 0.1],
  large_slab: [0.3, 0.1, 0.1],
  medium_brick: [0.2, 0.1, 0.1],
};

export class BlockManager {
  constructor(scene) {
    this.scene = scene;
    this.blocks = new Map(); // id -> { mesh, target, state, pop }
    this._geo = {};
    for (const [type, d] of Object.entries(DIMS)) {
      this._geo[type] = new THREE.BoxGeometry(d[0] * WORLD_SCALE, d[1] * WORLD_SCALE, d[2] * WORLD_SCALE);
    }
  }

  _make(type) {
    const mat = new THREE.MeshStandardMaterial({
      color: BLOCK_COLORS[type],
      metalness: 0.35,
      roughness: 0.45,
      emissive: BLOCK_COLORS[type],
      emissiveIntensity: 0.12,
    });
    const mesh = new THREE.Mesh(this._geo[type], mat);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    // subtle wire overlay for a "constructed" look
    const wire = new THREE.LineSegments(
      new THREE.EdgesGeometry(this._geo[type]),
      new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.15 })
    );
    mesh.add(wire);
    return mesh;
  }

  update(blockStates, time) {
    const seen = new Set();
    for (const b of blockStates) {
      seen.add(b.id);
      let entry = this.blocks.get(b.id);
      if (!entry) {
        const mesh = this._make(b.block_type);
        this.scene.add(mesh);
        const p = S(b.position);
        mesh.position.set(p[0], p[1], p[2]);
        entry = { mesh, target: new THREE.Vector3(p[0], p[1], p[2]), state: b.state, pop: 0 };
        this.blocks.set(b.id, entry);
      }
      const p = S(b.position);
      entry.target.set(p[0], p[1], p[2]);

      // State transition → placement pop.
      if (entry.state !== b.state) {
        if (b.state === "placed") entry.pop = 1.0;
        entry.state = b.state;
      }

      const mat = entry.mesh.material;
      if (b.state === "dropped") {
        // Red pulsing danger glow.
        mat.emissive.setHex(0xff4444);
        mat.emissiveIntensity = 0.4 + 0.35 * Math.sin(time * 8);
      } else if (b.state === "supply") {
        mat.emissive.setHex(BLOCK_COLORS[b.block_type]);
        mat.emissiveIntensity = 0.06;
        mat.opacity = 1;
      } else if (b.state === "carried") {
        mat.emissive.setHex(BLOCK_COLORS[b.block_type]);
        mat.emissiveIntensity = 0.3;
      } else {
        mat.emissive.setHex(BLOCK_COLORS[b.block_type]);
        mat.emissiveIntensity = 0.12;
      }
    }

    // Interpolate + pop animation.
    for (const [id, e] of this.blocks) {
      if (!seen.has(id)) { this.scene.remove(e.mesh); this.blocks.delete(id); continue; }
      // carried/placed snap faster; supply is static
      const speed = e.state === "carried" ? 0.35 : 0.25;
      e.mesh.position.lerp(e.target, speed);
      if (e.pop > 0) {
        e.pop = Math.max(0, e.pop - 0.06);
        const s = 1 + e.pop * 0.4;
        e.mesh.scale.set(s, s, s);
      } else {
        e.mesh.scale.set(1, 1, 1);
      }
    }
  }

  clear() {
    for (const [, e] of this.blocks) this.scene.remove(e.mesh);
    this.blocks.clear();
  }
}
