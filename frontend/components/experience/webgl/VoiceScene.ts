import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { experience, damp } from "../lib/store";
import { samplePath } from "../lib/sections";
import { ORB_VERTEX, ORB_FRAGMENT } from "./orbShaders";
import { makeSprite, makeCloudGeometry } from "./particles";
import type { Tier } from "../lib/capabilities";

/**
 * The cinematic scene, rendered with vanilla Three.js and driven imperatively
 * from React (see Canvas3D). This deliberately does NOT use react-three-fiber:
 * in this Next 15 + React 19 environment R3F's reconciler mounts the <Canvas>
 * but never commits the scene subtree, so the declarative layer is replaced by
 * this hand-rolled renderer. Everything else — the orb shader, particle field,
 * camera path, and the shared scroll/pointer store — is reused unchanged.
 *
 * Lifecycle: construct with a canvas, call start(); dispose() frees all GPU
 * resources. The render loop reads the shared `experience` store each frame
 * (scroll, pointer, speak/hover energy, reduced-motion, visibility) so it never
 * triggers React re-renders.
 */
export class VoiceScene {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private composer: EffectComposer;
  private clock = new THREE.Clock();

  private orbMat: THREE.ShaderMaterial;
  private orbGroup = new THREE.Group();
  private far: THREE.Points;
  private near: THREE.Points;
  private sprite: THREE.Texture;

  private curLook = new THREE.Vector3(0, 0, 0);
  private tgtPos = new THREE.Vector3();
  private tgtLook = new THREE.Vector3();
  private px = 0;
  private py = 0;
  private raf = 0;
  private running = false;
  private ro: ResizeObserver;
  private canvas: HTMLCanvasElement;

  constructor(
    private container: HTMLElement,
    private tier: Tier,
  ) {
    // Own the <canvas> (create + append + remove on dispose) rather than reuse
    // a React-rendered one. React 19 StrictMode double-invokes effects in dev
    // (mount → dispose → mount); a disposed WebGL context can't be re-acquired
    // on the same canvas element, so a shared canvas renders black on the 2nd
    // mount. A scene-owned canvas gives each mount a fresh context.
    this.canvas = document.createElement("canvas");
    this.canvas.style.cssText = "display:block;width:100%;height:100%";
    container.appendChild(this.canvas);

    const high = tier === "high";
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
      stencil: false,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, high ? 1.75 : 1.35));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;

    this.scene.background = new THREE.Color("#05060f");
    this.scene.fog = new THREE.Fog("#05060f", 6, 17);

    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    this.camera.position.set(0, 0.15, 5.2);

    // Lights (only the floor + particles are lit; the orb is a custom unlit
    // shader that computes its own colour).
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.35));
    const key = new THREE.PointLight("#2dd4bf", 40, 30);
    key.position.set(4, 3, 5);
    const rim = new THREE.PointLight("#8b5cf6", 30, 30);
    rim.position.set(-5, -2, 2);
    const fill = new THREE.PointLight("#dfe7ff", 12, 12);
    fill.position.set(0, 0, 3);
    this.scene.add(key, rim, fill);

    // The orb.
    const geo = new THREE.IcosahedronGeometry(1.35, high ? 24 : 12);
    this.orbMat = new THREE.ShaderMaterial({
      vertexShader: ORB_VERTEX,
      fragmentShader: ORB_FRAGMENT,
      uniforms: {
        uTime: { value: 0 },
        uSpeak: { value: 0.12 },
        uHover: { value: 0 },
        uColorA: { value: new THREE.Color("#2dd4bf") },
        uColorB: { value: new THREE.Color("#8b5cf6") },
        uColorC: { value: new THREE.Color("#0a1230") },
      },
    });
    this.orbGroup.add(new THREE.Mesh(geo, this.orbMat));
    this.scene.add(this.orbGroup);

    // Particle field (two layers for depth).
    this.sprite = makeSprite();
    const count = high ? 1200 : 380;
    const farMat = new THREE.PointsMaterial({
      size: 0.05,
      map: this.sprite,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
      opacity: 0.85,
    });
    const nearMat = new THREE.PointsMaterial({
      size: 0.22,
      map: this.sprite,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
      opacity: 0.5,
    });
    this.far = new THREE.Points(makeCloudGeometry(count, 6, 10), farMat);
    this.near = new THREE.Points(makeCloudGeometry(Math.round(count * 0.14), 3.5, 3), nearMat);
    this.scene.add(this.far, this.near);

    // Post-processing: bloom for the luminous, "shot on a lens" quality.
    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    const bloom = new UnrealBloomPass(
      new THREE.Vector2(1, 1),
      high ? 0.85 : 0.6, // strength
      0.7, // radius
      0.2, // threshold
    );
    this.composer.addPass(bloom);
    this.composer.addPass(new OutputPass());

    this.resize();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(this.container);
  }

  private resize = () => {
    const w = this.container.clientWidth || window.innerWidth;
    const h = this.container.clientHeight || window.innerHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
    this.composer.setSize(w, h);
    this.composer.setPixelRatio(this.renderer.getPixelRatio());
  };

  start() {
    if (this.running) return;
    this.running = true;
    this.clock.start();
    this.loop();
  }

  stop() {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }

  private loop = () => {
    if (!this.running) return;
    this.raf = requestAnimationFrame(this.loop);
    const dt = Math.min(this.clock.getDelta(), 1 / 30);
    const reduced = experience.reducedMotion;

    // Orb uniforms — idle breathing baseline + demo "speaking" energy.
    const u = this.orbMat.uniforms;
    u.uTime.value += dt;
    u.uSpeak.value = damp(u.uSpeak.value, Math.min(1, 0.12 + experience.speak), 3, dt);
    u.uHover.value = damp(u.uHover.value, experience.hover, 4, dt);
    if (!reduced) {
      this.orbGroup.rotation.y += dt * 0.08;
      this.orbGroup.rotation.x = Math.sin(u.uTime.value * 0.2) * 0.08;
    }

    // Particle drift + cursor parallax on the near layer.
    this.px = damp(this.px, experience.pointerX, 2, dt);
    this.py = damp(this.py, experience.pointerY, 2, dt);
    if (!reduced) this.far.rotation.y += dt * 0.012;
    this.near.rotation.y += dt * 0.03;
    this.near.position.x = -this.px * 0.5;
    this.near.position.y = -this.py * 0.35;

    // Camera flies along the scroll-driven path + subtle pointer sway.
    samplePath(experience.scroll, this.tgtPos, this.tgtLook);
    const swayX = reduced ? 0 : this.px * 0.6;
    const swayY = reduced ? 0 : this.py * 0.4;
    const lambda = reduced ? 12 : 3.2;
    this.camera.position.x = damp(this.camera.position.x, this.tgtPos.x + swayX, lambda, dt);
    this.camera.position.y = damp(this.camera.position.y, this.tgtPos.y + swayY, lambda, dt);
    this.camera.position.z = damp(this.camera.position.z, this.tgtPos.z, lambda, dt);
    this.curLook.x = damp(this.curLook.x, this.tgtLook.x + swayX * 0.3, lambda, dt);
    this.curLook.y = damp(this.curLook.y, this.tgtLook.y + swayY * 0.3, lambda, dt);
    this.curLook.z = damp(this.curLook.z, this.tgtLook.z, lambda, dt);
    this.camera.lookAt(this.curLook);

    // Pause rendering entirely when the tab is hidden (saves GPU); the loop
    // keeps ticking cheaply so it resumes instantly.
    if (experience.visible) this.composer.render();
  };

  dispose() {
    this.stop();
    this.ro.disconnect();
    this.scene.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (mesh.geometry) mesh.geometry.dispose();
      const mat = (mesh as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else if (mat) mat.dispose();
    });
    this.sprite.dispose();
    this.composer.dispose();
    this.renderer.dispose();
    this.canvas.remove();
  }
}
