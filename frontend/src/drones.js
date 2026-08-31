// Drone mesh rendering — chassis, spinning propellers, carry indicator, trails.
import * as THREE from "three";
import { S, WORLD_SCALE, BLOCK_COLORS } from "./scene.js";

const ROLE_TINT = {
  small: 0x8cbcff,
  large: 0xffa680,
  generalist: 0xd8d8ff,
};
const TRAIL_LEN = 22;

export class DroneManager {
  constructor(scene) {
    this.scene = scene;
    this.drones = new Map();
  }

  _make(role) {
    const group = new THREE.Group();
    const tint = ROLE_TINT[role] || 0xe0e0ff;

    // Chassis
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(0.12 * WORLD_SCALE, 0.05 * WORLD_SCALE, 0.12 * WORLD_SCALE),
      new THREE.MeshStandardMaterial({ color: tint, metalness: 0.6, roughness: 0.3, emissive: tint, emissiveIntensity: 0.15 })
    );
    body.castShadow = true;
    group.add(body);

    // Arms + propellers at 4 corners
    const props = [];
    const arm = 0.075 * WORLD_SCALE;
    const propMat = new THREE.MeshStandardMaterial({ color: 0x7070ff, emissive: 0x7070ff, emissiveIntensity: 0.6, transparent: true, opacity: 0.85 });
    for (const [dx, dz] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
      const hub = new THREE.Mesh(
        new THREE.CylinderGeometry(0.008 * WORLD_SCALE, 0.008 * WORLD_SCALE, 0.03 * WORLD_SCALE, 6),
        new THREE.MeshStandardMaterial({ color: 0x222244 })
      );
      hub.position.set(dx * arm, 0.03 * WORLD_SCALE, dz * arm);
      group.add(hub);
      const prop = new THREE.Mesh(
        new THREE.BoxGeometry(0.09 * WORLD_SCALE, 0.004 * WORLD_SCALE, 0.014 * WORLD_SCALE),
        propMat
      );
      prop.position.set(dx * arm, 0.05 * WORLD_SCALE, dz * arm);
      group.add(prop);
      props.push(prop);
    }

    // Carry indicator (below chassis, hidden until carrying)
    const carry = new THREE.Mesh(
      new THREE.BoxGeometry(0.09 * WORLD_SCALE, 0.09 * WORLD_SCALE, 0.09 * WORLD_SCALE),
      new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.4 })
    );
    carry.position.y = -0.12 * WORLD_SCALE;
    carry.visible = false;
    group.add(carry);

    // Under-glow
    const glow = new THREE.PointLight(tint, 0.5, 2.2);
    glow.position.y = -0.05 * WORLD_SCALE;
    group.add(glow);

    this.scene.add(group);

    // Trail
    const trailGeo = new THREE.BufferGeometry();
    trailGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(TRAIL_LEN * 3), 3));
    const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: tint, transparent: true, opacity: 0.4 }));
    trail.frustumCulled = false;
    this.scene.add(trail);

    return { group, body, props, carry, glow, tint, trail, trailPts: [], target: new THREE.Vector3() };
  }

  update(droneStates, time) {
    const seen = new Set();
    for (const d of droneStates) {
      seen.add(d.id);
      let e = this.drones.get(d.id);
      if (!e) {
        e = this._make(d.specialist_type);
        const p = S(d.position);
        e.group.position.set(p[0], p[1], p[2]);
        this.drones.set(d.id, e);
      }
      const p = S(d.position);
      e.target.set(p[0], p[1], p[2]);
      e.group.position.lerp(e.target, 0.3);

      // Propeller spin (faster when active).
      const active = d.state !== "IDLE";
      const spin = active ? 0.9 : 0.3;
      for (const pr of e.props) pr.rotation.y += spin;

      // Carry indicator.
      if (d.carrying) {
        e.carry.visible = true;
        e.carry.material.color.setHex(BLOCK_COLORS[d.carrying]);
        e.carry.material.emissive.setHex(BLOCK_COLORS[d.carrying]);
      } else {
        e.carry.visible = false;
      }

      // Collision flash.
      if (d.collision_flash) {
        e.body.material.emissive.setHex(0xff4444);
        e.body.material.emissiveIntensity = 0.9;
        e.glow.color.setHex(0xff4444);
      } else {
        e.body.material.emissive.setHex(e.tint);
        e.body.material.emissiveIntensity = d.reassigned ? 0.5 : 0.15;
        e.glow.color.setHex(d.reassigned ? 0xffaa44 : e.tint);
      }

      // Trail update.
      e.trailPts.push(e.group.position.clone());
      if (e.trailPts.length > TRAIL_LEN) e.trailPts.shift();
      const arr = e.trail.geometry.attributes.position.array;
      for (let i = 0; i < TRAIL_LEN; i++) {
        const pt = e.trailPts[i] || e.trailPts[0] || e.group.position;
        arr[i * 3] = pt.x; arr[i * 3 + 1] = pt.y; arr[i * 3 + 2] = pt.z;
      }
      e.trail.geometry.attributes.position.needsUpdate = true;
    }

    for (const [id, e] of this.drones) {
      if (!seen.has(id)) {
        this.scene.remove(e.group);
        this.scene.remove(e.trail);
        this.drones.delete(id);
      }
    }
  }

  clear() {
    for (const [, e] of this.drones) { this.scene.remove(e.group); this.scene.remove(e.trail); }
    this.drones.clear();
  }
}
