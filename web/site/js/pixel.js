// SPDX-License-Identifier: MIT
// The pixel field behind the home's closing (site v3, docs/review/site-v3.md): a dependency-free port of the
// idea of react-bits' PixelBlast (MIT): value-noise fbm thresholded through an 8 × 8 Bayer matrix into square
// pixels that drift slowly, with ripples. One WebGL2 pass at one fragment per pattern pixel (4 CSS px), scaled
// up crisp by the browser (image-rendering: pixelated), so it costs about 1/16 of a full-size pass. In the brand
// lime: --brand-px where the pattern is thin, the fill's lime where it is dense. A quiet box around the words
// (alpha 0 there, so their contrast is the page's own) and a fade at every edge. It opens with a blast from
// Open your drive the first time it is seen, ripples again when the pointer meets that button or it takes focus
// (at most once per 1.5 s), and draws only while it is on screen in a visible tab. site.js loads it after the
// load event, when the section comes near, never with reduced motion or Data Saver; a lost context, or a device
// too slow for it (the hero field's check, box.dataset.slow), brings the CSS pixels back.
const PX = 4, GAP = 1500, INTRO = 1400, SLOW = 40, FRAMES = 20;   // too slow: the median frame gap of the first FRAMES
const VERT = `#version 300 es
in vec2 p;
void main() { gl_Position = vec4(p, 0., 1.); }`;
const FRAG = `#version 300 es
precision highp float;
uniform vec2 uRes, uC;
uniform float uT, uIntro, uAlpha;
uniform vec3 uInk, uHot;
uniform vec4 uBox, uRip[3];
out vec4 o;
float h(vec3 p) { return fract(sin(dot(p, vec3(1., 57., 113.))) * 43758.5453); }
float vn(vec3 p) {
  vec3 i = floor(p), f = fract(p), w = f * f * f * (f * (f * 6. - 15.) + 10.);
  vec2 e = vec2(1., 0.);
  return mix(mix(mix(h(i), h(i + e.xyy), w.x), mix(h(i + e.yxy), h(i + e.xxy), w.x), w.y),
             mix(mix(h(i + e.yyx), h(i + e.xyx), w.x), mix(h(i + e.yxx), h(i + 1.), w.x), w.y), w.z) * 2. - 1.;
}
int bayer(ivec2 q) {
  int x = q.x & 7, y = q.y & 7, z = x ^ y;
  return (z & 1) << 5 | (y & 1) << 4 | (z & 2) << 2 | (y & 2) << 1 | (z & 4) >> 1 | (y & 4) >> 2;
}
void main() {
  vec2 p = gl_FragCoord.xy, uv = p / uRes.y;
  vec3 q = vec3(uv * 2.4, uT * .05);
  float s = 1., f = 1.;
  for (int i = 0; i < 5; i++) { s += vn(q * f); f *= 1.25; }
  float feed = (s * .5 + .5) * .5 - .48;
  for (int i = 0; i < 3; i++) {
    vec4 r = uRip[i];
    if (r.w < .5) continue;
    float d = distance(uv, r.xy / uRes.y);
    feed = max(feed, exp(-pow((d - .45 * r.z) / .09, 2.)) * exp(-1.2 * r.z) * exp(-3. * d) * 1.3);
  }
  if (uIntro < 1.) {
    float d = distance(uv, uC / uRes.y), front = (1. - pow(1. - uIntro, 2.4)) * (length(uRes) / uRes.y + .2);
    feed = mix(-1., feed, smoothstep(front + .04, front - .06, d));
    feed = max(feed, exp(-pow((d - front) / .07, 2.)) * (1. - uIntro) * 1.4);
  }
  float a = step(1., feed + float(bayer(ivec2(p))) / 64.) * uAlpha;
  vec2 b = abs(p - uBox.xy) - uBox.zw;
  a *= smoothstep(4., 16., length(max(b, 0.)) + min(max(b.x, b.y), 0.));
  vec2 e = clamp(min(p, uRes - p) / vec2(uRes.x * .08, uRes.y * .1), 0., 1.);
  e *= e * (3. - 2. * e);
  a *= e.x * e.y;
  o = vec4(mix(uInk, uHot, smoothstep(.3, 1., feed) * .85) * a, a);
}`;

export function start(box, canvas, gl) {
  const sec = box.parentElement, words = sec.querySelector('.wrap');
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
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;   // the CSS pixels stay
  gl.useProgram(prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  const u = Object.fromEntries(['uRes', 'uC', 'uT', 'uIntro', 'uAlpha', 'uInk', 'uHot', 'uBox', 'uRip']
    .map((n) => [n, gl.getUniformLocation(prog, n)]));

  let raf = 0, onScreen = false, stopped = false, intro0 = 0, last = -1e9, clock = 0, prev = 0, ripples = [];
  let ink = [0, 0, 0], hot = [0, 0, 0], alpha = 0.5, wbox = [0, 0, 1, 1], frames = 0;
  const hex = (v) => (v.match(/[0-9a-f]{2}/gi) || [0, 0, 0]).slice(0, 3).map((x) => parseInt(x, 16) / 255);
  const colours = () => {
    const css = getComputedStyle(box);
    ink = hex(css.getPropertyValue('--brand-px'));
    hot = hex(css.getPropertyValue('--brand-solid'));
    alpha = parseFloat(css.getPropertyValue('--px-alpha')) || 0.5;
  };
  // CSS px on screen -> pattern px inside the box, y up
  const at = (x, y, b = box.getBoundingClientRect()) => [(x - b.left) / PX, (b.bottom - y) / PX];
  const button = () => [...words.querySelectorAll('.btn-xl')].find((b) => b.offsetWidth);
  const centre = (el) => {
    const r = el.getBoundingClientRect();
    return at(r.left + r.width / 2, r.top + r.height / 2);
  };
  function measure() {
    const rect = box.getBoundingClientRect();
    canvas.width = Math.max(1, Math.ceil(rect.width / PX));
    canvas.height = Math.max(1, Math.ceil(rect.height / PX));
    const parts = [...words.querySelectorAll('h2, p, .btn-xl')].map((e) => e.getBoundingClientRect()).filter((r) => r.width);
    const [l, t, r, b] = [Math.min(...parts.map((p) => p.left)), Math.min(...parts.map((p) => p.top)),
      Math.max(...parts.map((p) => p.right)), Math.max(...parts.map((p) => p.bottom))];
    const [x0, y0] = at(l, b, rect), [x1, y1] = at(r, t, rect);
    wbox = [(x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2];
  }
  const active = () => onScreen && !document.hidden && !stopped;
  function draw(now) {
    clock += Math.min(now - prev, 100) / 1000;   // the pattern's time stands still while paused
    prev = now;
    const rip = new Float32Array(12);
    ripples = ripples.filter((r) => now - r.t0 < 4000);
    ripples.forEach((r, i) => rip.set([r.x, r.y, (now - r.t0) / 1000, 1], i * 4));
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform2f(u.uRes, canvas.width, canvas.height);
    gl.uniform2f(u.uC, ...(intro0 ? centre(button() || words) : [0, 0]));
    gl.uniform1f(u.uT, clock * 0.5);
    gl.uniform1f(u.uIntro, intro0 ? Math.min((now - intro0) / INTRO, 1) : 1);
    gl.uniform1f(u.uAlpha, alpha);
    gl.uniform3f(u.uInk, ...ink);
    gl.uniform3f(u.uHot, ...hot);
    gl.uniform4f(u.uBox, ...wbox);
    gl.uniform4fv(u.uRip, rip);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    box.frames = ++frames;   // for the tests
  }
  let gaps = [], last0 = 0;
  function frame(now) {
    raf = 0;
    draw(now);
    if (gaps && last0) gaps.push(now - last0);
    last0 = now;
    if (gaps?.length >= FRAMES) {
      const median = gaps.sort((a, b) => a - b)[gaps.length >> 1];
      gaps = null;
      if (median > SLOW) { box.dataset.slow = String(Math.round(median)); return stop(); }
    }
    if (intro0 && now - intro0 > INTRO) intro0 = 0;
    if (active()) raf = requestAnimationFrame(frame);
  }
  function resume() {
    if (!active() || raf) return;
    prev = performance.now();
    if (!box.classList.contains('live')) {
      box.classList.add('live');   // the canvas fades in over the CSS pixels, which fade out
      intro0 = prev;
    }
    raf = requestAnimationFrame(frame);
  }
  function pause() {
    cancelAnimationFrame(raf);
    raf = 0;
    last0 = 0;   // a hidden tab's gap isn't the device's
  }
  function ripple() {
    const b = button();
    if (!b || !active() || performance.now() - last < GAP) return;
    last = performance.now();
    const [x, y] = centre(b);
    ripples = [...ripples, { x, y, t0: last }].slice(-3);
    box.dataset.ripples = (+box.dataset.ripples || 0) + 1;
  }
  function stop() {
    stopped = true;
    pause();
    box.classList.remove('live');
  }

  colours();
  box.append(canvas);
  new ResizeObserver(() => { measure(); if (!stopped && !raf) draw(performance.now()); }).observe(sec);
  new IntersectionObserver((e) => { onScreen = e.at(-1).isIntersecting; onScreen ? resume() : pause(); }).observe(box);
  document.addEventListener('visibilitychange', () => (document.hidden ? pause() : resume()));
  for (const b of words.querySelectorAll('.btn-xl')) for (const type of ['pointerenter', 'focus']) b.addEventListener(type, ripple);
  const redraw = () => { colours(); if (!stopped && !raf) draw(performance.now()); };
  new MutationObserver(redraw).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  for (const q of ['(prefers-color-scheme: dark)', '(prefers-contrast: more)']) matchMedia(q).addEventListener('change', redraw);
  matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', (m) => m.matches && stop());
  canvas.addEventListener('webglcontextlost', stop);
}
