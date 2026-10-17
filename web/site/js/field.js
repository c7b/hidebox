// SPDX-License-Identifier: MIT
// The field behind the home's hero (17-site-brief §1, 17-brand.md "The field"): the static grid of
// home.css, drawn again in WebGL2 so ripples can bend it. A port of the idea of react-bits' RippleGrid
// (MIT): one fullscreen fragment pass, grid lines with their exact pixel coverage, ink only (no glow, no
// second hue), up to four ripples. Ripples start at the hero's brand button: one 300 ms after the first
// frame, one every 7 s while the hero is on screen and the tab visible, and one when the pointer enters
// the button or it takes focus (at most one per 1.5 s). Each travels and fades in 2.4 s. Between them
// nothing is drawn: frames run only while a ripple moves. site.js loads this after the load event, with a
// WebGL2 context already made, and never with reduced motion; a lost context brings the CSS grid back.
import { quietZone } from './site.js';

const LIFE = 2400, EVERY = 7000, GAP = 1500, AMP = 0.6 * 12;
const VERT = `#version 300 es
in vec2 p;
void main() { gl_Position = vec4(p, 0., 1.); }`;
// Same geometry and masks as .hero-field::before: lines 1 CSS px wide at x = W/2 + 48k and y = 48k - 1;
// the quiet ellipse (x uQuiet inside 75 % of its radii), a fade from 40 % to 92 % of the height and over
// 14 % at each side. Crossings add up the way two CSS gradient layers do.
const FRAG = `#version 300 es
precision highp float;
uniform vec2 uRes, uSize;
uniform float uDpr, uAlpha, uQuiet, uReach;
uniform vec3 uInk;
uniform vec4 uZone, uRip[4];
out vec4 o;
float cover(float d) { return clamp((.5 + .5 / uDpr - d) * uDpr, 0., 1.); }
void main() {
  vec2 size = uSize;
  vec2 p = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y) * (uSize / uRes), q = p;
  for (int i = 0; i < 4; i++) {
    vec4 r = uRip[i];
    if (r.w < .5) continue;
    vec2 v = p - r.xy;
    float d = max(length(v), .001), x = (d - uReach * (1. - (1. - r.z) * (1. - r.z))) / 40.;
    q += v / d * sin(x * 3.14159) * exp(-x * x) * (1. - r.z) * ${AMP.toFixed(2)};
  }
  float dx = abs(mod(q.x - size.x * .5 - .5 + 24., 48.) - 24.);
  float dy = abs(mod(q.y + .5 + 24., 48.) - 24.);
  float a = 1. - (1. - uAlpha * cover(dx)) * (1. - uAlpha * cover(dy));
  a *= mix(uQuiet, 1., clamp((length((p - uZone.xy) / uZone.zw) - .75) / .25, 0., 1.));
  a *= 1. - clamp((p.y / size.y - .4) / .52, 0., 1.);
  float s = p.x / size.x;
  a *= clamp(s / .14, 0., 1.) * clamp((1. - s) / .14, 0., 1.);
  o = vec4(uInk * a, a);
}`;

export function start(field, canvas, gl) {
  const root = document.documentElement;
  const hero = field.parentElement;
  const shader = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    return s;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, shader(gl.VERTEX_SHADER, VERT));
  gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FRAG));
  gl.bindAttribLocation(prog, 0, 'p');
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;   // the static grid stays
  gl.useProgram(prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  const u = Object.fromEntries(['uRes', 'uSize', 'uDpr', 'uAlpha', 'uQuiet', 'uReach', 'uInk', 'uZone', 'uRip']
    .map((n) => [n, gl.getUniformLocation(prog, n)]));

  let ripples = [], count = 0, last = -1e9, raf = 0, timer = 0, onScreen = true, stopped = false;
  let dpr = 1, css = { w: 1, h: 1 }, zone = { x: 0, y: 0, rx: 1, ry: 1 }, ink = [0, 0, 0], alpha = 0.3, quiet = 0.4;

  // The brand colour and strengths, from the tokens (light, dark, increased contrast).
  const colours = () => {
    const css = getComputedStyle(field);
    ink = css.color.match(/[\d.]+/g).slice(0, 3).map((c) => c / 255);
    alpha = parseFloat(css.getPropertyValue('--field-alpha')) || 0.3;
    quiet = parseFloat(css.getPropertyValue('--field-quiet')) || 0.4;
  };
  // The button on screen: Open your drive, to /drive?make, or to /drive?open when this browser has a drive.
  const brand = () => hero.querySelector(root.hasAttribute('data-has-drive') ? '.cta-open' : '.cta-make');
  const active = () => onScreen && !document.hidden && !stopped;

  function draw(now = performance.now()) {
    const w = canvas.width, h = canvas.height;
    const reach = Math.hypot(Math.max(...ripples.map((r) => Math.max(r.x, css.w - r.x)), 0), css.h) + 80;
    const rip = new Float32Array(16);
    ripples.forEach((r, i) => rip.set([r.x, r.y, Math.min((now - r.t0) / LIFE, 1), 1], i * 4));
    gl.viewport(0, 0, w, h);
    gl.uniform2f(u.uRes, w, h);
    gl.uniform2f(u.uSize, css.w, css.h);
    gl.uniform1f(u.uDpr, dpr);
    gl.uniform1f(u.uAlpha, alpha);
    gl.uniform1f(u.uQuiet, quiet);
    gl.uniform1f(u.uReach, reach);
    gl.uniform3f(u.uInk, ...ink);
    gl.uniform4f(u.uZone, zone.x, zone.y, zone.rx, zone.ry);
    gl.uniform4fv(u.uRip, rip);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    if (!field.classList.contains('live')) {
      field.classList.add('live');   // the canvas fades in over the CSS grid, which fades out (300 ms)
      schedule(300);
    }
  }
  function frame(now) {
    raf = 0;
    ripples = ripples.filter((r) => now - r.t0 < LIFE);
    draw(now);
    if (ripples.length && active()) raf = requestAnimationFrame(frame);
  }
  function ripple() {
    const b = brand()?.getBoundingClientRect(), f = field.getBoundingClientRect();
    if (!b || !active()) return;
    last = performance.now();
    ripples = [...ripples, { x: b.left + b.width / 2 - f.left, y: b.top + b.height / 2 - f.top, t0: last }].slice(-4);
    field.dataset.ripples = ++count;
    if (!raf) raf = requestAnimationFrame(frame);
  }
  function schedule(wait) {
    clearTimeout(timer);
    if (active()) timer = setTimeout(() => { ripple(); schedule(EVERY); }, wait);
  }
  function pause() {
    cancelAnimationFrame(raf);
    raf = 0;
    clearTimeout(timer);
  }
  function resume() {
    if (!active() || !field.classList.contains('live')) return;
    const now = performance.now();
    ripples = ripples.filter((r) => now - r.t0 < LIFE);
    if (ripples.length) raf ||= requestAnimationFrame(frame);
    else draw(now);
    schedule(Math.max(300, EVERY - (performance.now() - last)));
  }
  function stop() {
    stopped = true;
    pause();
    field.classList.remove('live');
  }

  colours();
  field.append(canvas);
  new ResizeObserver(() => {
    const r = field.getBoundingClientRect();
    dpr = Math.min(devicePixelRatio || 1, matchMedia('(pointer: coarse)').matches ? 1.5 : 2);
    css = { w: Math.max(1, r.width), h: Math.max(1, r.height) };
    canvas.width = Math.max(1, Math.round(css.w * dpr));
    canvas.height = Math.max(1, Math.round(css.h * dpr));
    dpr = canvas.width / css.w;
    zone = quietZone();
    if (!stopped) draw();
  }).observe(field);
  new IntersectionObserver((entries) => { onScreen = entries.at(-1).isIntersecting; onScreen ? resume() : pause(); }).observe(hero);
  document.addEventListener('visibilitychange', () => (document.hidden ? pause() : resume()));
  for (const b of hero.querySelectorAll('.cta-make, .cta-open')) {
    for (const type of ['pointerenter', 'focus']) {
      b.addEventListener(type, () => {
        if (b !== brand() || performance.now() - last < GAP) return;
        ripple();
        schedule(EVERY);
      });
    }
  }
  const redraw = () => { colours(); if (!stopped && !raf) draw(); };
  hero.addEventListener('animationend', () => { zone = quietZone(); redraw(); });   // the words settled (site v3)
  new MutationObserver(redraw).observe(root, { attributes: true, attributeFilter: ['data-theme'] });
  for (const q of ['(prefers-color-scheme: dark)', '(prefers-contrast: more)']) matchMedia(q).addEventListener('change', redraw);
  matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', (m) => m.matches && stop());
  canvas.addEventListener('webglcontextlost', stop);
}
