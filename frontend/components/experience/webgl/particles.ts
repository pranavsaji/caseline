import * as THREE from "three";

/** Soft round sprite so points read as luminous motes, not hard squares. */
export function makeSprite(): THREE.Texture {
  const s = 64;
  const c = document.createElement("canvas");
  c.width = c.height = s;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.35, "rgba(200,220,255,0.55)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, s, s);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/**
 * Build a shell-ish point cloud (the orb sits in a central clearing). Colors
 * are a cold-blue majority with teal + violet accents so they harmonize with
 * the orb and bloom warmly through the fog.
 */
export function makeCloudGeometry(count: number, radius: number, spread: number) {
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const teal = new THREE.Color("#2dd4bf");
  const violet = new THREE.Color("#8b5cf6");
  const cold = new THREE.Color("#6f8bff");
  for (let i = 0; i < count; i++) {
    const r = radius + Math.random() * spread;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.cos(phi) * 0.55;
    positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta) - 2;
    const pick = Math.random();
    const col = pick < 0.5 ? cold : pick < 0.8 ? teal : violet;
    colors[i * 3] = col.r;
    colors[i * 3 + 1] = col.g;
    colors[i * 3 + 2] = col.b;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  return geo;
}
