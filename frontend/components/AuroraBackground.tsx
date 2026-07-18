"use client";

import { useEffect, useRef } from "react";

/**
 * Live WebGL aurora — a fixed, full-viewport fragment-shader field that flows
 * violet/teal light over the deep-space base. Self-contained raw WebGL (no
 * three.js) so it stays tiny and React-19 safe. It is purely decorative
 * (aria-hidden, pointer-events:none) and sits at z-index:-1 behind the shell.
 *
 * Guards: caps devicePixelRatio, pauses the RAF loop when the tab is hidden,
 * and honours prefers-reduced-motion by drawing a single static frame (no
 * animation) — so it never costs battery or fights the Lighthouse score.
 */

const FRAG = `#version 300 es
precision highp float;
out vec4 outColor;
uniform vec2 u_res;
uniform float u_time;

// value-noise + fbm
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }
float noise(vec2 p){
  vec2 i = floor(p), f = fract(p);
  float a = hash(i), b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0)), d = hash(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}
float fbm(vec2 p){
  float v = 0.0, amp = 0.5;
  for (int i = 0; i < 5; i++){ v += amp * noise(p); p *= 2.02; amp *= 0.5; }
  return v;
}

void main(){
  vec2 uv = gl_FragCoord.xy / u_res.xy;
  vec2 p = uv;
  p.x *= u_res.x / u_res.y;
  float t = u_time * 0.05;

  // flowing domain-warped field
  vec2 q = vec2(fbm(p + vec2(0.0, t)), fbm(p + vec2(5.2, -t)));
  vec2 r = vec2(fbm(p + 1.6 * q + vec2(1.7, 9.2) + 0.15 * t),
                fbm(p + 1.6 * q + vec2(8.3, 2.8) - 0.12 * t));
  float f = fbm(p + 2.2 * r);

  vec3 space  = vec3(0.024, 0.027, 0.067);   // #060711
  vec3 teal   = vec3(0.133, 0.878, 0.780);   // #22e0c7
  vec3 violet = vec3(0.616, 0.482, 1.000);   // #9d7bff
  vec3 blue   = vec3(0.353, 0.659, 1.000);   // #5aa8ff (indigo->cyan midpoint)
  vec3 indigo = vec3(0.055, 0.067, 0.176);

  // Controlled glow: keep the base deep so glass panels read crisply, then let
  // saturated ribbons of the indigo->cyan gradient flow through the negative
  // space between them.
  vec3 col = space;
  col = mix(col, indigo, clamp(f * 0.95, 0.0, 1.0));
  col = mix(col, violet, clamp(pow(r.x, 1.9) * 0.85, 0.0, 1.0));
  col = mix(col, blue,   clamp(pow(q.x, 2.0) * 0.55, 0.0, 1.0));
  col = mix(col, teal,   clamp(pow(q.y, 2.0) * 0.80, 0.0, 1.0));

  // faint top glow + a deeper vignette so the eye settles on the content
  col += teal * 0.05 * smoothstep(1.0, 0.2, uv.y);
  float vig = smoothstep(1.35, 0.15, length(uv - 0.5));
  col *= 0.40 + 0.60 * vig;

  outColor = vec4(col, 1.0);
}`;

const VERT = `#version 300 es
in vec2 a_pos;
void main(){ gl_Position = vec4(a_pos, 0.0, 1.0); }`;

export default function AuroraBackground() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl2", { antialias: false, alpha: false });
    if (!gl) return; // WebGL2 unavailable → CSS gradient backdrop remains

    const compile = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    };
    const prog = gl.createProgram()!;
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "a_pos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(prog, "u_res");
    const uTime = gl.getUniformLocation(prog, "u_time");

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const w = Math.floor(window.innerWidth * dpr);
      const h = Math.floor(window.innerHeight * dpr);
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);
      }
      gl.uniform2f(uRes, w, h);
    };
    resize();
    window.addEventListener("resize", resize);

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    const start = performance.now();
    const draw = (now: number) => {
      gl.uniform1f(uTime, (now - start) / 1000);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      raf = requestAnimationFrame(draw);
    };

    if (reduce) {
      gl.uniform1f(uTime, 12.0); // one static, pleasant frame
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    } else {
      raf = requestAnimationFrame(draw);
    }

    const onVisibility = () => {
      if (reduce) return;
      if (document.hidden) {
        cancelAnimationFrame(raf);
        raf = 0;
      } else if (!raf) {
        raf = requestAnimationFrame(draw);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
      gl.deleteProgram(prog);
      gl.deleteBuffer(buf);
    };
  }, []);

  return <canvas ref={canvasRef} className="auroraCanvas" aria-hidden />;
}
