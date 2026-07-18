import * as THREE from "three";

/**
 * The camera path. Each keyframe is anchored to a normalized scroll position
 * `at` (0 = top of page, 1 = bottom). `CameraRig` samples this spline every
 * frame so the camera glides continuously through the scene as the user
 * scrolls — no abrupt section jumps. `look` is the world-space target the
 * camera aims at (the orb sits at the origin, so most keyframes look near it).
 *
 * Tuned so the 3D framing lines up with the seven content sections stacked in
 * the DOM overlay (see `EXPERIENCE_SECTIONS`).
 */
export type CamKey = { at: number; pos: THREE.Vector3; look: THREE.Vector3 };

export const CAMERA_PATH: CamKey[] = [
  // 0 — Hero: intimate, close on the orb, slightly below eye-line.
  { at: 0.0, pos: new THREE.Vector3(0, 0.15, 5.2), look: new THREE.Vector3(0, 0, 0) },
  // 1 — Intro: pull back to reveal scale + the particle field.
  { at: 0.17, pos: new THREE.Vector3(0.6, 0.6, 8.4), look: new THREE.Vector3(0, 0, 0) },
  // 2 — Features: orbit to the right, camera drifts around the orb.
  { at: 0.4, pos: new THREE.Vector3(4.2, 0.2, 5.6), look: new THREE.Vector3(0, 0, 0) },
  // 3 — Demo: swing back to a near, head-on "listening" framing.
  { at: 0.6, pos: new THREE.Vector3(-1.4, -0.2, 4.4), look: new THREE.Vector3(0, 0, 0) },
  // 4 — Proof: rise up and back, looking down across the drifting field.
  { at: 0.8, pos: new THREE.Vector3(-0.4, 1.6, 7.6), look: new THREE.Vector3(0, -0.2, 0) },
  // 5 — CTA / Footer: recenter, the orb glows dead-center, calm and resolved.
  { at: 1.0, pos: new THREE.Vector3(0, 0, 5.0), look: new THREE.Vector3(0, 0, 0) },
];

const smoothstep = (t: number) => t * t * (3 - 2 * t);

/** Sample the camera keyframe spline at normalized scroll `p` (0..1), writing
 * the interpolated position + look-at target into the provided vectors. Shared
 * by the render loop so the camera glides continuously as the user scrolls. */
export function samplePath(p: number, pos: THREE.Vector3, look: THREE.Vector3) {
  const keys = CAMERA_PATH;
  if (p <= keys[0].at) {
    pos.copy(keys[0].pos);
    look.copy(keys[0].look);
    return;
  }
  const last = keys[keys.length - 1];
  if (p >= last.at) {
    pos.copy(last.pos);
    look.copy(last.look);
    return;
  }
  for (let i = 0; i < keys.length - 1; i++) {
    const a = keys[i];
    const b = keys[i + 1];
    if (p >= a.at && p <= b.at) {
      const t = smoothstep((p - a.at) / (b.at - a.at));
      pos.copy(a.pos).lerp(b.pos, t);
      look.copy(a.look).lerp(b.look, t);
      return;
    }
  }
}

export type SectionDef = {
  id: string;
  eyebrow: string;
};

/** DOM overlay sections, in order. Rendered as full-viewport scroll panels. */
export const EXPERIENCE_SECTIONS: SectionDef[] = [
  { id: "hero", eyebrow: "Caseline" },
  { id: "intro", eyebrow: "The intake employee" },
  { id: "features", eyebrow: "How it works" },
  { id: "demo", eyebrow: "Listen in" },
  { id: "proof", eyebrow: "Proof" },
  { id: "cta", eyebrow: "Get started" },
];
