/* Boundary Editor live 3D preview pane (phase 1, APP_VERSION v7.2).
 *
 * One classic script, loaded by templates/editor.html.  three.js (pinned, vendored in static/vendor/three/) is
 * lazy-loaded on the first time the pane opens.  The editor owns only: a "3D" button, a container element, the hotkey
 * and Preview3D.attach() / watcher calls.  Everything else lives here.
 *
 * Layers (the first three have no DOM or three.js dependency and are unit-tested under node):
 *   1. CONFIG            every constant (hotkey, timings, labels, colours, wire format, ...), defined once.
 *   2. wire / geometry   decodePreview(), terraceHeights(), gridMeshArrays()   (contract: owner_inbox/preview_api_contract.md)
 *   3. createRefresher   throttle / debounce / sequence numbers / error states   (the engine behind requestPreviewRefresh)
 *   4. snapshot          buildSnapshot() from the editor's IN-MEMORY state (never the file, never autosave)
 *   5. view + pane       three.js scene, DOM pane, attach()/setOpen()
 */
(function (root) {
  'use strict';

  // ═══ 1. CONFIG ═══════════════════════════════════════════════════════════════════════════════════════════════════
  const CONFIG = Object.freeze({
    VERSION: 'v7.2',
    THREE_VERSION: 'r160',                       // vendored build, see static/vendor/three/
    HOTKEY: '3',                                 // plain key, ignored while typing (the editor checks this)
    BUTTON_LABEL: '3D',
    BUTTON_TITLE: 'Show / hide the live 3D preview (key 3)',
    LABEL_APPROX: 'Preview - approximate; texture, engraving and holes not shown',
    LABEL_RESET_VIEW: 'Reset view',
    LABEL_SCALE_FMT: 'True vertical scale ({style} green)',
    LABEL_STYLE_SMOOTH: 'smooth',
    LABEL_STYLE_TERRACED: 'terraced',
    LABEL_LOADING: 'Building the 3D preview. The first one takes a few seconds.',
    LABEL_UPDATING: 'updating...',
    LABEL_GREEN_STALE: 'Green outline changed. Updating when you let go.',
    MSG_NEEDS_GREEN: 'Open a project with a green outline to see the preview.',
    MSG_BUSY: 'Generate is running. The preview is paused and will resume.',
    MSG_FAILED_FMT: 'Preview unavailable: {msg}',
    MSG_NETWORK: 'Preview unavailable: could not reach the server.',
    MSG_THREE_FAILED: 'Preview unavailable: the 3D library could not be loaded.',
    MSG_BAD_FORMAT: 'Preview unavailable: unexpected data from the server.',
    MSG_NO_WEBGL: 'Preview unavailable: this browser cannot create a WebGL view.',

    // server API
    API_ROUTE: '/api/preview',
    HTTP_METHOD: 'POST',
    HEADER_CONTENT_TYPE: 'Content-Type',
    CONTENT_TYPE_JSON: 'application/json',
    REQ_SNAPSHOT: 'snapshot', REQ_SEQ: 'seq', REQ_FRINGE_RES: 'fringeRes', REQ_GREEN_MODE: 'greenMode',
    GREEN_MODE_AUTO: 'auto', GREEN_MODE_CACHED_ONLY: 'cachedOnly',
    FRINGE_RES_FULL: 96, FRINGE_RES_DRAG: 48,
    ERR_CODE_GREEN_CACHE_MISS: 'green_cache_miss', ERR_CODE_BUSY: 'busy', ERR_CODE_NO_GREEN: 'no_green',
    HTTP_STATUS_CONFLICT: 409, HTTP_STATUS_UNAVAILABLE: 503,

    // timing (ms)
    THROTTLE_MS: 100,           // while a drag is in progress: at most one cheap request per this
    DEBOUNCE_MS: 50,            // discrete edits (click, undo, Options field)
    RELEASE_MS: 30,             // trailing full refresh after a drag is released
    SLOW_INDICATOR_MS: 300,     // "updating..." dot appears only if a refresh takes longer
    BUSY_RETRY_MS: 2000,        // retry after 503 busy

    // refresh modes
    MODE_FULL: 'full', MODE_DRAG: 'drag',

    // wire format (little endian)
    WIRE_MAGIC: 'EGMP', WIRE_VERSION: 1,
    HEADER_BYTES: 40, PART_BYTES: 36, MARKER_BYTES: 20, ALIGN_BYTES: 4,
    KIND_GREEN: 1, KIND_FRINGE: 2, KIND_BUNKER: 3, KIND_WATER: 4, KIND_BOULDERS: 5,
    MARKER_TEE: 1, MARKER_FLAG: 2,
    FLAG_GREEN_CACHE_HIT: 1, FLAG_GREEN_FLAT: 2, FLAG_WATER_LIFT: 4, FLAG_TAIL_CACHE_HIT: 8,
    TERRACE_DEFAULT_LEVELS: 27,

    // editor state field names the snapshot reads (the same keys autoSave() posts)
    POLY_TYPE_GREEN: 'green', GREEN_STYLE_TERRACED: 'terraced', GREEN_STYLE_SMOOTH: 'smooth',

    // colours: print filament colours, one table shared by the meshes and the legend
    COLORS: Object.freeze({
      green: 0x1f7a3a, fringe: 0x8dc26f, bunker: 0xe3d3a0, water: 0x3b82c4, boulders: 0x8a8a8a,
      base: 0x4a4a4a, tee: 0xd94f1f, flagPole: 0xf5f5f5, flag: 0xe11d48,
      background: 0xeef0f3, light: 0xffffff, hemiSky: 0xffffff, hemiGround: 0x8a8a8a,
    }),
    GREEN_STALE_OPACITY: 0.35,
    LIGHT_AMBIENT: 0.85, LIGHT_SUN: 0.65, LIGHT_SUN_POS: [-1, -1.2, 1.1],

    // scene geometry (mm)
    CAMERA_FOV_DEG: 38, CAMERA_NEAR_MM: 1, CAMERA_FAR_MM: 3000,
    CAMERA_DIRECTION: [0, -1, 1.05],            // from the plate centre towards the camera (south, tilted up)
    FIT_RADIUS_FACTOR: 1.25,                    // fitted sphere radius, in plate half-sizes (plate corner is 1.41)
    CAMERA_MIN_DISTANCE_MM: 20, CAMERA_MAX_DISTANCE_MM: 1200,
    DEFAULT_PLATE_HALF_MM: 85.2,
    PIXEL_RATIO_MAX: 2,
    TEE_HEIGHT_MM: 3.5, FLAG_POLE_HEIGHT_MM: 20, FLAG_POLE_RADIUS_MM: 0.6,
    FLAG_W_MM: 7, FLAG_H_MM: 4.5, FLAG_T_MM: 0.5, CYL_SEGMENTS: 20,

    // vendored three.js (relative to this script)
    VENDOR_DIR: 'vendor/three/', THREE_FILE: 'three.module.min.js', ORBIT_FILE: 'OrbitControls.js',
    FALLBACK_SCRIPT_BASE: '/static/',

    // pane DOM
    TESTID_PANE: 'preview3d-pane', TESTID_CANVAS_HOST: 'preview3d-host', TESTID_MSG: 'preview3d-msg',
    TESTID_DOT: 'preview3d-dot', TESTID_LOADING: 'preview3d-loading', TESTID_RESET: 'preview3d-reset',
    TESTID_STALE: 'preview3d-stale', TESTID_SCALE: 'preview3d-scale',
    STYLE_ELEMENT_ID: 'preview3d-style',
    UI: Object.freeze({
      bg: '#eef0f3', border: '#e5e7eb', text: '#37352f', muted: '#6b7280', dot: '#4f46e5', panel: 'rgba(255,255,255,0.88)',
      minHeightVar: 'var(--editor-canvas-min-height, 400px)',
    }),
  });

  // ═══ 2. wire format + geometry (pure) ════════════════════════════════════════════════════════════════════════════
  function roundUp(n, to) { return Math.ceil(n / to) * to; }

  /** Decode the binary preview (contract section 4).  Throws Error('bad_format') on anything unexpected. */
  function decodePreview(buf) {
    const C = CONFIG;
    if (!buf || buf.byteLength < C.HEADER_BYTES) throw new Error('bad_format');
    const dv = new DataView(buf);
    let magic = '';
    for (let i = 0; i < C.WIRE_MAGIC.length; i++) magic += String.fromCharCode(dv.getUint8(i));
    if (magic !== C.WIRE_MAGIC || dv.getUint16(4, true) !== C.WIRE_VERSION) throw new Error('bad_format');
    const header = {
      flags: dv.getUint16(6, true), seq: dv.getUint32(8, true), plateHalf: dv.getFloat32(12, true),
      lift: dv.getFloat32(16, true), base: dv.getFloat32(20, true), totalMs: dv.getFloat32(24, true),
      greenMs: dv.getFloat32(28, true), fringeMs: dv.getFloat32(32, true),
      nParts: dv.getUint16(36, true), nMarkers: dv.getUint16(38, true),
    };
    const blobStart = C.HEADER_BYTES + C.PART_BYTES * header.nParts + C.MARKER_BYTES * header.nMarkers;
    if (buf.byteLength < blobStart) throw new Error('bad_format');
    const parts = [];
    for (let p = 0; p < header.nParts; p++) {
      const o = C.HEADER_BYTES + C.PART_BYTES * p;
      const part = {
        kind: dv.getUint8(o), index: dv.getUint8(o + 1), nx: dv.getUint16(o + 2, true), ny: dv.getUint16(o + 4, true),
        xmin: dv.getFloat32(o + 8, true), ymin: dv.getFloat32(o + 12, true), xmax: dv.getFloat32(o + 16, true),
        ymax: dv.getFloat32(o + 20, true), zmin: dv.getFloat32(o + 24, true), zmax: dv.getFloat32(o + 28, true),
      };
      const off = blobStart + dv.getUint32(o + 32, true);
      const n = part.nx * part.ny;
      if (off + n * 4 + n > buf.byteLength) throw new Error('bad_format');
      part.heights = new Float32Array(buf.slice(off, off + n * 4));
      part.mask = new Uint8Array(buf.slice(off + n * 4, off + n * 4 + n));
      parts.push(part);
    }
    const markers = [];
    for (let m = 0; m < header.nMarkers; m++) {
      const o = C.HEADER_BYTES + C.PART_BYTES * header.nParts + C.MARKER_BYTES * m;
      markers.push({ kind: dv.getUint8(o), x: dv.getFloat32(o + 4, true), y: dv.getFloat32(o + 8, true),
                     z: dv.getFloat32(o + 12, true), radius: dv.getFloat32(o + 16, true) });
    }
    return { header, parts, markers };
  }

  /** Generate's quantiser on a green part (contract section 7).  Returns a NEW Float32Array; mask=0 nodes untouched. */
  function terraceHeights(part, contourStep) {
    const out = new Float32Array(part.heights);
    const range = part.zmax - part.zmin;
    if (!(range > 0)) return out;
    const levels = contourStep > 0 ? Math.max(1, Math.round(range / contourStep)) : CONFIG.TERRACE_DEFAULT_LEVELS;
    const step = range / levels;
    for (let i = 0; i < out.length; i++) {
      if (part.mask[i]) out[i] = Math.round((part.heights[i] - part.zmin) / step) * step + part.zmin;
    }
    return out;
  }

  /** Vertex positions (world mm, true scale) and triangle indices of one grid part. */
  function gridMeshArrays(part, heights) {
    const { nx, ny } = part;
    const pos = new Float32Array(nx * ny * 3);
    const dx = nx > 1 ? (part.xmax - part.xmin) / (nx - 1) : 0;
    const dy = ny > 1 ? (part.ymax - part.ymin) / (ny - 1) : 0;
    for (let r = 0; r < ny; r++) {
      for (let c = 0; c < nx; c++) {
        const i = r * nx + c;
        pos[i * 3] = part.xmin + c * dx; pos[i * 3 + 1] = part.ymin + r * dy; pos[i * 3 + 2] = heights[i];
      }
    }
    const idx = [];
    const m = part.mask;
    for (let r = 0; r < ny - 1; r++) {
      for (let c = 0; c < nx - 1; c++) {
        const a = r * nx + c, b = a + 1, d = a + nx, e = d + 1;
        if (m[a] && m[b] && m[e]) idx.push(a, b, e);
        if (m[a] && m[e] && m[d]) idx.push(a, e, d);
      }
    }
    return { positions: pos, indices: new Uint32Array(idx) };
  }

  // ═══ 3. refresh engine ═══════════════════════════════════════════════════════════════════════════════════════════
  /**
   * Throttle / debounce / sequence-number engine.  All environment access is injected so it runs under node.
   * o: { isOpen(), getSnapshot() -> object|null, fetchFn(url, init) -> Promise<Response-like>, setTimer, clearTimer,
   *      onSurface(decoded), onStatus({kind, message?}), onGreenStale(bool) }
   * Status kinds: 'loading' (no surface yet), 'updating' (slow refresh), 'idle', 'busy', 'error', 'needs'.
   */
  function createRefresher(o) {
    const C = CONFIG;
    const setT = o.setTimer || ((f, ms) => setTimeout(f, ms));
    const clrT = o.clearTimer || ((h) => clearTimeout(h));
    const st = { seq: 0, shownSeq: -1, inFlight: false, dragging: false, dirty: false, pendingMode: null,
                 debounce: null, throttle: null, retry: null, slow: null, hasSurface: false, needsFull: false,
                 sent: 0, shown: 0, discarded: 0, lastMode: null };

    function clearAll(k) { if (st[k] !== null) { clrT(st[k]); st[k] = null; } }
    function mergeMode(a, b) { return (a === C.MODE_FULL || b === C.MODE_FULL) ? C.MODE_FULL : C.MODE_DRAG; }

    /** requestPreviewRefresh(reason): the single entry point.  Free when the pane is closed. */
    function request(reason) {
      if (!o.isOpen()) return;
      st.dirty = true;
      st.lastReason = reason;
      if (st.dragging) {
        if (st.throttle === null) st.throttle = setT(() => { st.throttle = null; send(C.MODE_DRAG); }, C.THROTTLE_MS);
        return;
      }
      clearAll('debounce');
      st.debounce = setT(() => { st.debounce = null; send(C.MODE_FULL); }, C.DEBOUNCE_MS);
    }

    /** A pointer drag started (true) or ended (false) somewhere in the editor. */
    function setDragging(on) {
      on = !!on;
      if (on === st.dragging) return;
      st.dragging = on;
      if (!on) {
        clearAll('throttle');
        if (st.dirty || st.needsFull) { clearAll('debounce'); st.debounce = setT(() => { st.debounce = null; send(C.MODE_FULL); }, C.RELEASE_MS); }
      }
    }

    function send(mode) {
      if (!o.isOpen()) return;
      if (st.inFlight) { st.pendingMode = st.pendingMode ? mergeMode(st.pendingMode, mode) : mode; return; }
      const snap = o.getSnapshot();
      if (!snap) { st.dirty = false; o.onStatus({ kind: 'needs', message: C.MSG_NEEDS_GREEN }); return; }
      st.dirty = false; st.inFlight = true; st.lastMode = mode;
      st.needsFull = mode === C.MODE_DRAG;   // a cheap drag-mode result is always followed by one full refresh on release
      const mySeq = ++st.seq; st.sent++;
      const body = {};
      body[C.REQ_SNAPSHOT] = snap; body[C.REQ_SEQ] = mySeq;
      body[C.REQ_FRINGE_RES] = mode === C.MODE_DRAG ? C.FRINGE_RES_DRAG : C.FRINGE_RES_FULL;
      body[C.REQ_GREEN_MODE] = mode === C.MODE_DRAG ? C.GREEN_MODE_CACHED_ONLY : C.GREEN_MODE_AUTO;
      if (!st.hasSurface) o.onStatus({ kind: 'loading' });
      else { clearAll('slow'); st.slow = setT(() => { st.slow = null; o.onStatus({ kind: 'updating' }); }, C.SLOW_INDICATOR_MS); }
      const headers = {}; headers[C.HEADER_CONTENT_TYPE] = C.CONTENT_TYPE_JSON;
      let p;
      try { p = Promise.resolve(o.fetchFn(C.API_ROUTE, { method: C.HTTP_METHOD, headers, body: JSON.stringify(body) })); }
      catch (e) { p = Promise.reject(e); }
      p.then((resp) => handleResponse(mySeq, resp))
       .catch(() => fail({ kind: 'error', message: C.MSG_NETWORK }))
       .then(() => {
         clearAll('slow'); st.inFlight = false;
         if (st.pendingMode) { const m = st.pendingMode; st.pendingMode = null; send(m); }
       });
    }

    async function handleResponse(mySeq, resp) {
      if (resp.ok) {
        let decoded;
        try { decoded = decodePreview(await resp.arrayBuffer()); }
        catch (e) { return fail({ kind: 'error', message: C.MSG_BAD_FORMAT }); }
        return deliver(mySeq, decoded);
      }
      let code = '', msg = '';
      try { const j = await resp.json(); code = j.code || ''; msg = j.msg || ''; } catch (e) { /* non-JSON error body */ }
      if (resp.status === C.HTTP_STATUS_CONFLICT || code === C.ERR_CODE_GREEN_CACHE_MISS) {
        o.onGreenStale(true);
        return o.onStatus({ kind: 'stale', message: C.LABEL_GREEN_STALE });
      }
      if (resp.status === C.HTTP_STATUS_UNAVAILABLE || code === C.ERR_CODE_BUSY) {
        clearAll('retry'); st.retry = setT(() => { st.retry = null; request('busy-retry'); }, C.BUSY_RETRY_MS);
        return o.onStatus({ kind: 'busy', message: C.MSG_BUSY });
      }
      if (code === C.ERR_CODE_NO_GREEN) return o.onStatus({ kind: 'needs', message: C.MSG_NEEDS_GREEN });
      return fail({ kind: 'error', message: C.MSG_FAILED_FMT.replace('{msg}', msg || ('HTTP ' + resp.status)) });
    }

    /** Latest sequence wins: a result older than the newest one already shown is dropped. */
    function deliver(seq, decoded) {
      if (!o.isOpen() || seq < st.shownSeq) { st.discarded++; return false; }
      st.shownSeq = seq; st.shown++; st.hasSurface = true;
      o.onGreenStale(false);
      o.onSurface(decoded);
      o.onStatus({ kind: 'idle' });
      return true;
    }
    function fail(status) { o.onStatus(status); }

    function reset() {                       // pane closed: drop timers; the last surface is kept by the view layer
      ['debounce', 'throttle', 'retry', 'slow'].forEach(clearAll);
      st.dirty = false; st.pendingMode = null; st.dragging = false;
    }
    return { request, setDragging, deliver, reset, state: st };
  }

  // ═══ 4. snapshot from IN-MEMORY editor state ════════════════════════════════════════════════════════════════════
  /**
   * Same keys and shapes autoSave() posts, restricted to what the preview endpoint reads.  Returns null when there is
   * nothing to preview (no image, or no green outline).  Reads Alpine state, so calling it inside a watcher getter
   * subscribes to every field it touches.
   */
  function buildSnapshot(s) {
    if (!s || !s.imgLoaded || !s.selectedImage) return null;
    const polys = (s.polygons || []).map((p) => ({
      name: p.name, type: p.type, closed: true, points: p.points.map((pt) => ({ x: pt.x, y: pt.y })),
    }));
    if (!polys.some((p) => p.type === CONFIG.POLY_TYPE_GREEN)) return null;
    const snap = {
      image: s.selectedImage,
      imageCourse: s.selectedImageCourse || (s.courseName || '').trim(),
      imageSize: { width: s.imgW, height: s.imgH },
      elevationRange: s.elevationRange, zScale: s.zScale, greenScale: s.greenScale,
      baseThicknessMm: s.baseThicknessMm, includeBoundaryRegion: s.includeBoundaryRegion,
      flagOffsetXMm: s.flagOffsetXMm, flagOffsetYMm: s.flagOffsetYMm,
      polygons: polys, gridMode: s.gridMode, gridResolution: s.gridN,
      gridCellHeights: Object.assign({}, s.gridCellHeights || {}),
    };
    if (s.teeHole && typeof s.teeHole.x_mm === 'number' && typeof s.teeHole.y_mm === 'number') {
      snap.tee_hole = { x_mm: s.teeHole.x_mm, y_mm: s.teeHole.y_mm };
    }
    return snap;
  }

  /** Watcher getter value for the editor: '' when closed (free), else the snapshot JSON (changes <=> a refresh is due). */
  function signature(s) {
    if (!s || !s.preview3dOpen) return '';
    const snap = buildSnapshot(s);
    return snap ? JSON.stringify(snap) : 'none';
  }
  /** Smooth / Terraced + step: handled in the browser, never sent to the server. */
  function styleSignature(s) {
    if (!s || !s.preview3dOpen) return '';
    return [s.greenStyle, s.contourStep].join('|');
  }

  // ═══ 5. view (three.js) + pane DOM ══════════════════════════════════════════════════════════════════════════════
  const scriptBase = (function () {
    try { const src = document.currentScript && document.currentScript.src; if (src) return src.replace(/[^/]*$/, ''); } catch (e) { /* node */ }
    return CONFIG.FALLBACK_SCRIPT_BASE;
  })();

  let threePromise = null;
  function loadThree() {
    if (!threePromise) {
      const base = scriptBase + CONFIG.VENDOR_DIR;
      threePromise = Promise.all([import(base + CONFIG.THREE_FILE), import(base + CONFIG.ORBIT_FILE)])
        .then(([T, O]) => ({ THREE: T, OrbitControls: O.OrbitControls }))
        .catch((e) => { threePromise = null; throw e; });
    }
    return threePromise;
  }

  function injectStyle() {
    if (document.getElementById(CONFIG.STYLE_ELEMENT_ID)) return;
    const U = CONFIG.UI;
    const css = `
      :root { --p3d-bg:${U.bg}; --p3d-border:${U.border}; --p3d-text:${U.text}; --p3d-muted:${U.muted}; --p3d-dot:${U.dot}; --p3d-panel:${U.panel}; }
      .p3d-pane { position:relative; min-height:${U.minHeightVar}; background:var(--p3d-bg); border:1px solid var(--p3d-border); border-radius:8px; overflow:hidden; font-size:12px; color:var(--p3d-text); }
      .p3d-host { position:absolute; inset:0; outline:none; }
      .p3d-host canvas { display:block; width:100%; height:100%; }
      .p3d-top { position:absolute; left:8px; right:8px; top:6px; display:flex; gap:8px; align-items:center; justify-content:space-between; pointer-events:none; z-index:2; }
      .p3d-chip { background:var(--p3d-panel); border-radius:6px; padding:3px 8px; color:var(--p3d-muted); pointer-events:auto; }
      .p3d-btn { background:var(--p3d-panel); border:1px solid var(--p3d-border); border-radius:6px; padding:3px 10px; color:var(--p3d-text); cursor:pointer; pointer-events:auto; }
      .p3d-btn:hover { background:#fff; }
      .p3d-bottom { position:absolute; left:8px; right:8px; bottom:6px; display:flex; justify-content:space-between; gap:8px; pointer-events:none; z-index:2; }
      .p3d-msg { background:var(--p3d-panel); border-radius:6px; padding:3px 8px; color:var(--p3d-muted); }
      .p3d-center { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; text-align:center; padding:24px; color:var(--p3d-muted); z-index:1; pointer-events:none; }
      .p3d-dot { position:absolute; right:12px; top:40px; width:9px; height:9px; border-radius:50%; background:var(--p3d-dot); opacity:.85; z-index:3; animation:p3d-pulse 1s ease-in-out infinite; }
      @keyframes p3d-pulse { 0%,100% { opacity:.25; } 50% { opacity:.9; } }
      [hidden].p3d-dot, [hidden].p3d-center, [hidden].p3d-msg { display:none !important; }
    `;
    const el = document.createElement('style');
    el.id = CONFIG.STYLE_ELEMENT_ID; el.textContent = css;
    document.head.appendChild(el);
  }

  const P = {                     // pane state (browser only)
    container: null, getState: null, dom: null, view: null, viewPromise: null, open: false,
    lastResult: null, greenStale: false, status: { kind: 'idle' }, refresher: null, detach: [],
    greenStyle: CONFIG.GREEN_STYLE_SMOOTH, contourStep: 0,
  };

  function buildDom(container) {
    const C = CONFIG, d = document;
    container.innerHTML = '';
    container.classList.add('p3d-pane');
    container.setAttribute('data-testid', C.TESTID_PANE);
    const mk = (tag, cls, attrs, text) => {
      const e = d.createElement(tag); if (cls) e.className = cls;
      Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, v));
      if (text !== undefined) e.textContent = text; return e;
    };
    const host = mk('div', 'p3d-host', { 'data-testid': C.TESTID_CANVAS_HOST, tabindex: '0' });
    const top = mk('div', 'p3d-top');
    top.appendChild(mk('span', 'p3d-chip', { 'data-testid': 'preview3d-label' }, C.LABEL_APPROX));
    const reset = mk('button', 'p3d-btn', { type: 'button', 'data-testid': C.TESTID_RESET }, C.LABEL_RESET_VIEW);
    top.appendChild(reset);
    const bottom = mk('div', 'p3d-bottom');
    const scale = mk('span', 'p3d-msg', { 'data-testid': C.TESTID_SCALE });
    const msg = mk('span', 'p3d-msg', { 'data-testid': C.TESTID_MSG }); msg.hidden = true;
    bottom.appendChild(scale); bottom.appendChild(msg);
    const loading = mk('div', 'p3d-center', { 'data-testid': C.TESTID_LOADING }, C.LABEL_LOADING); loading.hidden = true;
    const dot = mk('div', 'p3d-dot', { 'data-testid': C.TESTID_DOT, title: C.LABEL_UPDATING }); dot.hidden = true;
    [host, top, bottom, loading, dot].forEach((e) => container.appendChild(e));
    reset.addEventListener('click', () => { if (P.view) P.view.resetView(); });
    return { host, reset, scale, msg, loading, dot };
  }

  function renderScaleLabel() {
    if (!P.dom) return;
    const style = P.greenStyle === CONFIG.GREEN_STYLE_TERRACED ? CONFIG.LABEL_STYLE_TERRACED : CONFIG.LABEL_STYLE_SMOOTH;
    P.dom.scale.textContent = CONFIG.LABEL_SCALE_FMT.replace('{style}', style);
  }

  function onStatus(status) {
    P.status = status;
    if (!P.dom) return;
    const { msg, loading, dot } = P.dom;
    loading.hidden = status.kind !== 'loading';
    dot.hidden = status.kind !== 'updating';
    const text = ['busy', 'error', 'needs', 'stale'].includes(status.kind) ? status.message : '';
    msg.textContent = text; msg.hidden = !text;
    msg.setAttribute('data-kind', status.kind);
    const ctr = P.dom.host.parentElement;
    if (ctr) ctr.setAttribute('data-status', status.kind);
  }

  // --- the three.js view ---
  function createView(host, lib) {
    const { THREE, OrbitControls } = lib;
    const C = CONFIG;
    let renderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false }); }
    catch (e) { throw new Error('no_webgl'); }
    renderer.setPixelRatio(Math.min(root.devicePixelRatio || 1, C.PIXEL_RATIO_MAX));
    renderer.setClearColor(C.COLORS.background, 1);
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(C.CAMERA_FOV_DEG, 1, C.CAMERA_NEAR_MM, C.CAMERA_FAR_MM);
    camera.up.set(0, 0, 1);                      // world is Z-up (mm): +X right, +Y plate-up, +Z height
    scene.add(new THREE.HemisphereLight(C.COLORS.hemiSky, C.COLORS.hemiGround, C.LIGHT_AMBIENT));
    const sun = new THREE.DirectionalLight(C.COLORS.light, C.LIGHT_SUN);
    sun.position.set(...C.LIGHT_SUN_POS); scene.add(sun);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = false;
    controls.minDistance = C.CAMERA_MIN_DISTANCE_MM; controls.maxDistance = C.CAMERA_MAX_DISTANCE_MM;

    const group = new THREE.Group(); scene.add(group);
    let plateHalf = C.DEFAULT_PLATE_HALF_MM, framed = false, raf = 0, disposed = false, greenMeshes = [];
    let data = null, style = C.GREEN_STYLE_SMOOTH, step = 0;
    const view = { renderCount: 0, canvas: renderer.domElement };

    function requestRender() {
      if (raf || disposed) return;
      raf = root.requestAnimationFrame(() => { raf = 0; if (disposed) return; renderer.render(scene, camera); view.renderCount++; });
    }
    controls.addEventListener('change', requestRender);

    function resetView() {
      const vHalf = THREE.MathUtils.degToRad(C.CAMERA_FOV_DEG) / 2;
      const fitHalf = Math.min(vHalf, Math.atan(Math.tan(vHalf) * camera.aspect));   // narrower of vertical / horizontal
      const dist = plateHalf * C.FIT_RADIUS_FACTOR / Math.sin(fitHalf);
      camera.position.copy(new THREE.Vector3(...C.CAMERA_DIRECTION).normalize().multiplyScalar(dist));
      controls.target.set(0, 0, 0); controls.update(); requestRender();
    }
    function resize() {
      const w = Math.max(1, host.clientWidth), hgt = Math.max(1, host.clientHeight);
      renderer.setSize(w, hgt, false); camera.aspect = w / hgt; camera.updateProjectionMatrix(); requestRender();
    }
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
    if (ro) ro.observe(host);
    resize();

    function clearGroup() {
      group.children.slice().forEach((m) => {
        group.remove(m);
        if (m.geometry) m.geometry.dispose();
        if (m.material) m.material.dispose();
      });
      greenMeshes = [];
    }
    function partColor(kind) {
      return ({ [C.KIND_GREEN]: C.COLORS.green, [C.KIND_FRINGE]: C.COLORS.fringe, [C.KIND_BUNKER]: C.COLORS.bunker,
                [C.KIND_WATER]: C.COLORS.water, [C.KIND_BOULDERS]: C.COLORS.boulders })[kind];
    }
    function partMesh(part, heights) {
      const arr = gridMeshArrays(part, heights);
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(arr.positions, 3));
      g.setIndex(new THREE.BufferAttribute(arr.indices, 1));
      g.computeVertexNormals();
      const mat = new THREE.MeshLambertMaterial({ color: partColor(part.kind), side: THREE.DoubleSide });
      const mesh = new THREE.Mesh(g, mat);
      mesh.userData.kind = part.kind; mesh.userData.index = part.index;
      return mesh;
    }
    function greenHeights(part) { return style === C.GREEN_STYLE_TERRACED ? terraceHeights(part, step) : part.heights; }
    function marker(m) {
      const col = m.kind === C.MARKER_TEE ? C.COLORS.tee : C.COLORS.flagPole;
      const mat = new THREE.MeshLambertMaterial({ color: col });
      const out = new THREE.Group();
      const h = m.kind === C.MARKER_TEE ? C.TEE_HEIGHT_MM : C.FLAG_POLE_HEIGHT_MM;
      const r = m.kind === C.MARKER_TEE ? m.radius : C.FLAG_POLE_RADIUS_MM;
      const cyl = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, C.CYL_SEGMENTS), mat);
      cyl.rotation.x = Math.PI / 2; cyl.position.set(0, 0, h / 2); out.add(cyl);
      if (m.kind === C.MARKER_FLAG) {
        const f = new THREE.Mesh(new THREE.BoxGeometry(C.FLAG_W_MM, C.FLAG_T_MM, C.FLAG_H_MM),
                                 new THREE.MeshLambertMaterial({ color: C.COLORS.flag, side: THREE.DoubleSide }));
        f.position.set(C.FLAG_W_MM / 2, 0, h - C.FLAG_H_MM / 2); out.add(f);
      }
      out.position.set(m.x, m.y, m.z);
      return out;
    }
    function applyStale(on) {
      greenMeshes.forEach((m) => { m.material.transparent = on; m.material.opacity = on ? C.GREEN_STALE_OPACITY : 1; m.material.needsUpdate = true; });
    }
    function build() {
      clearGroup();
      if (!data) return;
      plateHalf = data.header.plateHalf || plateHalf;
      const base = new THREE.Mesh(new THREE.PlaneGeometry(plateHalf * 2, plateHalf * 2), new THREE.MeshLambertMaterial({ color: C.COLORS.base }));
      base.position.z = 0; group.add(base);
      data.parts.forEach((part) => {
        const mesh = partMesh(part, part.kind === C.KIND_GREEN ? greenHeights(part) : part.heights);
        group.add(mesh);
        if (part.kind === C.KIND_GREEN) greenMeshes.push(mesh);
      });
      data.markers.forEach((m) => group.add(marker(m)));
      applyStale(view.greenStale);
      if (!framed) { framed = true; resetView(); }
      requestRender();
    }
    view.greenStale = false;
    view.setData = (d) => { data = d; build(); };
    view.setGreenStyle = (s, st2) => {
      const ns = s === C.GREEN_STYLE_TERRACED ? s : C.GREEN_STYLE_SMOOTH;
      if (ns === style && st2 === step) return;
      style = ns; step = Number(st2) || 0;
      if (!data) return;
      const part = data.parts.find((p) => p.kind === C.KIND_GREEN);
      const old = greenMeshes.pop();
      if (part && old) {                       // rebuild only the green mesh: no server call
        const mesh = partMesh(part, greenHeights(part));
        group.remove(old); old.geometry.dispose(); old.material.dispose();
        group.add(mesh);
        greenMeshes.push(mesh); applyStale(view.greenStale);
      }
      requestRender();
    };
    view.setGreenStale = (on) => { view.greenStale = !!on; applyStale(view.greenStale); requestRender(); };
    view.resetView = resetView;
    view.resize = resize;
    view.dispose = () => {
      disposed = true; if (raf) root.cancelAnimationFrame(raf);
      if (ro) ro.disconnect();
      clearGroup(); controls.dispose();
      renderer.dispose();
      try { renderer.forceContextLoss(); } catch (e) { /* ignore */ }
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
    };
    view.partCount = () => group.children.filter((m) => m.userData && m.userData.kind).length;
    view.requestRender = requestRender;
    return view;
  }

  function onSurface(decoded) {
    P.lastResult = decoded;
    if (P.view) P.view.setData(decoded);
  }
  function onGreenStale(on) {
    P.greenStale = !!on;
    if (P.view) P.view.setGreenStale(on);
  }

  function ensureRefresher() {
    if (P.refresher) return P.refresher;
    P.refresher = createRefresher({
      isOpen: () => P.open,
      getSnapshot: () => buildSnapshot(P.getState && P.getState()),
      fetchFn: (url, init) => root.fetch(url, init),
      onSurface, onStatus, onGreenStale,
    });
    return P.refresher;
  }

  /** requestPreviewRefresh(reason): the one function every editor trigger funnels into. */
  function requestPreviewRefresh(reason) { ensureRefresher().request(reason || 'unspecified'); }

  /** Called once by the editor's init(): container element + a function returning the editor state object. */
  function attach(container, getState) {
    P.container = container; P.getState = getState;
    ensureRefresher();
  }

  function installDragTracking() {
    const d = root.document;
    const down = (e) => { if (P.container && P.container.contains(e.target)) return; ensureRefresher().setDragging(true); };
    const up = () => ensureRefresher().setDragging(false);
    d.addEventListener('pointerdown', down, true);
    d.addEventListener('mousedown', down, true);
    d.addEventListener('pointerup', up, true);
    d.addEventListener('mouseup', up, true);
    d.addEventListener('pointercancel', up, true);
    root.addEventListener('blur', up);
    P.detach.push(() => {
      d.removeEventListener('pointerdown', down, true); d.removeEventListener('mousedown', down, true);
      d.removeEventListener('pointerup', up, true); d.removeEventListener('mouseup', up, true);
      d.removeEventListener('pointercancel', up, true); root.removeEventListener('blur', up);
    });
  }

  /** Open / close the pane.  Closed = no GL context, no timers, no requests. */
  async function setOpen(open) {
    open = !!open;
    if (open === P.open) return;
    P.open = open;
    if (!P.container) return;
    if (!open) {
      ensureRefresher().reset();
      if (P.view) { P.view.dispose(); P.view = null; }
      P.viewPromise = null;
      P.detach.splice(0).forEach((f) => f());
      return;
    }
    injectStyle();
    P.dom = buildDom(P.container);
    renderScaleLabel();
    installDragTracking();
    onStatus(P.lastResult ? { kind: 'idle' } : { kind: 'loading' });
    requestPreviewRefresh('open');
    const my = (P.viewPromise = loadThree().then((lib) => {
      if (!P.open || P.viewPromise !== my) return;
      P.view = createView(P.dom.host, lib);
      P.view.setGreenStyle(P.greenStyle, P.contourStep);
      P.view.setGreenStale(P.greenStale);
      if (P.lastResult) P.view.setData(P.lastResult);
    }).catch((e) => {
      onStatus({ kind: 'error', message: e && e.message === 'no_webgl' ? CONFIG.MSG_NO_WEBGL : CONFIG.MSG_THREE_FAILED });
    }));
  }

  /** Smooth / Terraced switch: purely local. */
  function setGreenStyle(style, contourStep) {
    P.greenStyle = style === CONFIG.GREEN_STYLE_TERRACED ? style : CONFIG.GREEN_STYLE_SMOOTH;
    P.contourStep = Number(contourStep) || 0;
    renderScaleLabel();
    if (P.view) P.view.setGreenStyle(P.greenStyle, P.contourStep);
  }

  /** Test / diagnostics hook (read-only). */
  function debug() {
    const st = P.refresher ? P.refresher.state : {};
    const fringe = P.lastResult && P.lastResult.parts.find((p) => p.kind === CONFIG.KIND_FRINGE);
    const green = P.lastResult && P.lastResult.parts.find((p) => p.kind === CONFIG.KIND_GREEN);
    const sum = (a) => { let t = 0; for (let i = 0; i < a.length; i++) t += a[i]; return t; };
    return {
      open: P.open, hasView: !!P.view, glActive: !!(P.view && P.view.canvas && P.view.canvas.isConnected),
      meshCount: P.view ? P.view.partCount() : 0, renderCount: P.view ? P.view.renderCount : 0,
      seq: st.seq, shownSeq: st.shownSeq, sent: st.sent, shown: st.shown, discarded: st.discarded,
      status: P.status.kind, greenStale: P.greenStale, greenStyle: P.greenStyle,
      parts: P.lastResult ? P.lastResult.parts.map((p) => p.kind) : [],
      fringeSum: fringe ? sum(fringe.heights) : null, greenSum: green ? sum(green.heights) : null,
      serverMs: P.lastResult ? P.lastResult.header.totalMs : null,
    };
  }

  const api = {
    CONFIG, decodePreview, terraceHeights, gridMeshArrays, createRefresher, buildSnapshot, signature, styleSignature,
    attach, setOpen, setGreenStyle, requestPreviewRefresh, debug,
  };
  root.Preview3D = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
