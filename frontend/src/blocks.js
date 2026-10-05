// Piece rendering — parametric boxes (cube / beam / slab) sized by w x d.
import * as THREE from "three";
import { S, WORLD_SCALE, BLOCK_COLORS } from "./scene.js?v=3";

const CELL = 0.1 * WORLD_SCALE;

export class BlockManager {
  constructor(scene) {
    this.scene = scene;
    this.blocks = new Map(); // id -> { mesh, target, state, pop, key }
    this._geo = {};          // "wxd" -> BoxGeometry
  }

  _geoFor(w, d) {
    const key = `${w}x${d}`;
    if (!this._geo[key]) {
      this._geo[key] = new THREE.BoxGeometry(w * CELL, CELL, d * CELL);
    }
    return this._geo[key];
  }

  _make(b) {
    const color = BLOCK_COLORS[b.piece_type] ?? 0x8888ff;
    const mat = new THREE.MeshStandardMaterial({
      color, metalness: 0.35, roughness: 0.5,
      emissive: color, emissiveIntensity: 0.12,
    });
    const geo = this._geoFor(b.w, b.d);
    const mesh = new THREE.Mesh(geo, mat);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    const wire = new THREE.LineSegments(
      new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.18 })
    );
    mesh.add(wire);
    return mesh;
  }

  update(blockStates, time) {
    const seen = new Set();
    for (const b of blockStates) {
      seen.add(b.id);
      let e = this.blocks.get(b.id);
      const key = `${b.piece_type}:${b.w}x${b.d}`;
      if (!e || e.key !== key) {
        if (e) this.scene.remove(e.mesh);
        const mesh = this._make(b);
        const p = S(b.position);
        mesh.position.set(p[0], p[1], p[2]);
        this.scene.add(mesh);
        e = { mesh, target: new THREE.Vector3(p[0], p[1], p[2]), state: b.state, pop: 0, key };
        this.blocks.set(b.id, e);
      }
      const p = S(b.position);
      e.target.set(p[0], p[1], p[2]);
      if (e.state !== b.state) {
        if (b.state === "placed") e.pop = 1.0;
        e.state = b.state;
      }

      const mat = e.mesh.material;
      const base = BLOCK_COLORS[b.piece_type] ?? 0x8888ff;
      if (b.state === "dropped") {
        mat.emissive.setHex(0xff4444);
        mat.emissiveIntensity = 0.4 + 0.35 * Math.sin(time * 8);
      } else if (b.state === "carried") {
        mat.emissive.setHex(base); mat.emissiveIntensity = 0.3;
      } else if (b.state === "supply") {
        mat.emissive.setHex(base); mat.emissiveIntensity = 0.06;
      } else {
        mat.emissive.setHex(base); mat.emissiveIntensity = 0.14;
      }
    }

    for (const [id, e] of this.blocks) {
      if (!seen.has(id)) { this.scene.remove(e.mesh); this.blocks.delete(id); continue; }
      const speed = e.state === "carried" ? 0.4 : 0.3;
      e.mesh.position.lerp(e.target, speed);
      if (e.pop > 0) {
        e.pop = Math.max(0, e.pop - 0.07);
        const s = 1 + e.pop * 0.25;
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
