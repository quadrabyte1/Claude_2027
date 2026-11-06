// Node-side checks of static/preview3d.js core logic (no DOM, no three.js).  Run by test_preview3d_v72.py,
// which reads the verdicts from stdout (JSON: {check name: "ok" | failure text}).  Every value comes from
// Preview3D.CONFIG (the single constants table), never a re-typed literal.
'use strict';
const path = require('path');
const P = require(path.resolve(process.argv[2]));
const C = P.CONFIG;
const results = {};

function fakeClock() {
  let now = 0, id = 1; const timers = new Map();
  return {
    setTimer(f, ms) { const h = id++; timers.set(h, { at: now + ms, f }); return h; },
    clearTimer(h) { timers.delete(h); },
    pending() { return timers.size; },
    async advance(ms) {
      const end = now + ms;
      for (;;) {
        let best = null;
        for (const [h, t] of timers) if (t.at <= end && (!best || t.at < best[1].at)) best = [h, t];
        if (!best) break;
        timers.delete(best[0]); now = Math.max(now, best[1].at); best[1].f();
        await flush();
      }
      now = end; await flush();
    },
  };
}
const flush = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); };

// minimal valid wire payload: header only (0 parts, 0 markers)
function emptyPayload(seq) {
  const b = new ArrayBuffer(C.HEADER_BYTES), dv = new DataView(b);
  for (let i = 0; i < C.WIRE_MAGIC.length; i++) dv.setUint8(i, C.WIRE_MAGIC.charCodeAt(i));
  dv.setUint16(4, C.WIRE_VERSION, true); dv.setUint32(8, seq, true);
  return b;
}
const okResp = (seq) => ({ ok: true, status: 200, arrayBuffer: async () => emptyPayload(seq) });
const errResp = (status, code, msg) => ({ ok: false, status, json: async () => ({ status: 'error', code, msg: msg || code }) });

function rig(over) {
  const clock = fakeClock();
  const env = { open: true, snap: { image: 'x' }, calls: [], surfaces: [], status: [], stale: [], respond: null };
  Object.assign(env, over || {});
  const r = P.createRefresher({
    isOpen: () => env.open, getSnapshot: () => env.snap,
    fetchFn: (url, init) => { const body = JSON.parse(init.body); env.calls.push({ url, body }); return env.respond(body); },
    setTimer: clock.setTimer, clearTimer: clock.clearTimer,
    onSurface: (d) => env.surfaces.push(d), onStatus: (s) => env.status.push(s), onGreenStale: (v) => env.stale.push(v),
  });
  return { r, clock, env };
}
const check = async (name, fn) => { try { const v = await fn(); results[name] = v === undefined || v === true ? 'ok' : String(v); } catch (e) { results[name] = 'threw: ' + e.stack; } };

(async () => {
  await check('closed_pane_sends_nothing_and_arms_no_timer', async () => {
    const { r, clock, env } = rig({ open: false, respond: async (b) => okResp(b.seq) });
    r.request('paint'); r.setDragging(true); r.request('paint'); r.setDragging(false);
    await clock.advance(10 * C.BUSY_RETRY_MS);
    if (env.calls.length) return 'fetch while closed: ' + env.calls.length;
    if (clock.pending()) return 'timers armed while closed';
  });

  await check('discrete_edits_debounce_into_one_full_request', async () => {
    const { r, clock, env } = rig({ respond: async (b) => okResp(b.seq) });
    r.request('a'); await clock.advance(C.DEBOUNCE_MS / 2); r.request('b'); await clock.advance(C.DEBOUNCE_MS / 2); r.request('c');
    if (env.calls.length) return 'sent before debounce settled';
    await clock.advance(C.DEBOUNCE_MS + 1);
    if (env.calls.length !== 1) return 'expected 1 request, got ' + env.calls.length;
    const b = env.calls[0].body;
    if (b[C.REQ_GREEN_MODE] !== C.GREEN_MODE_AUTO || b[C.REQ_FRINGE_RES] !== C.FRINGE_RES_FULL) return 'wrong mode ' + JSON.stringify(b);
    if (env.calls[0].url !== C.API_ROUTE) return 'wrong url';
  });

  await check('drag_throttles_cheap_then_release_sends_one_full', async () => {
    const { r, clock, env } = rig({ respond: async (b) => okResp(b.seq) });
    r.setDragging(true);
    for (let i = 0; i < 12; i++) { r.request('drag'); await clock.advance(C.THROTTLE_MS / 4); }   // 3 throttle periods
    const during = env.calls.slice();
    if (during.length < 2 || during.length > 4) return 'throttle count ' + during.length;
    if (!during.every((c) => c.body[C.REQ_GREEN_MODE] === C.GREEN_MODE_CACHED_ONLY && c.body[C.REQ_FRINGE_RES] === C.FRINGE_RES_DRAG)) return 'drag requests not cheap';
    r.request('last'); r.setDragging(false);
    await clock.advance(C.RELEASE_MS + C.DEBOUNCE_MS);
    const last = env.calls[env.calls.length - 1].body;
    if (last[C.REQ_GREEN_MODE] !== C.GREEN_MODE_AUTO || last[C.REQ_FRINGE_RES] !== C.FRINGE_RES_FULL) return 'trailing refresh not full: ' + JSON.stringify([last[C.REQ_GREEN_MODE], last[C.REQ_FRINGE_RES]]);
  });

  await check('one_request_in_flight_latest_wins', async () => {
    const gates = [];
    const { r, clock, env } = rig({ respond: (b) => new Promise((res) => gates.push(() => res(okResp(b.seq)))) });
    r.request('1'); await clock.advance(C.DEBOUNCE_MS + 1);
    r.request('2'); await clock.advance(C.DEBOUNCE_MS + 1);
    r.request('3'); await clock.advance(C.DEBOUNCE_MS + 1);
    if (env.calls.length !== 1) return 'second request sent while first in flight';
    gates[0](); await flush();
    if (env.calls.length !== 2) return 'queued request not sent after first finished (' + env.calls.length + ')';
    gates[1](); await flush();
    if (env.surfaces.length !== 2) return 'surfaces ' + env.surfaces.length;
    if (env.calls[1].body[C.REQ_SEQ] <= env.calls[0].body[C.REQ_SEQ]) return 'seq not increasing';
  });

  await check('older_sequence_is_discarded', async () => {
    const { r, env } = rig({ respond: async (b) => okResp(b.seq) });
    const dec = (s) => P.decodePreview(emptyPayload(s));
    if (!r.deliver(7, dec(7))) return 'newest rejected';
    if (r.deliver(3, dec(3))) return 'older result was shown';
    if (!r.deliver(8, dec(8))) return 'newer rejected';
    if (env.surfaces.length !== 2 || r.state.discarded !== 1) return 'surfaces=' + env.surfaces.length + ' discarded=' + r.state.discarded;
  });

  await check('result_after_pane_closed_is_dropped', async () => {
    let gate; const { r, clock, env } = rig({ respond: (b) => new Promise((res) => { gate = () => res(okResp(b.seq)); }) });
    r.request('x'); await clock.advance(C.DEBOUNCE_MS + 1); env.open = false; gate(); await flush();
    if (env.surfaces.length) return 'surface applied after close';
  });

  await check('slow_indicator_only_past_threshold', async () => {
    let gate; const { r, clock, env } = rig({ respond: (b) => new Promise((res) => { gate = () => res(okResp(b.seq)); }) });
    // first (cold) request shows the loading state, not the dot
    r.request('x'); await clock.advance(C.DEBOUNCE_MS + 1);
    if (!env.status.some((s) => s.kind === 'loading')) return 'no loading state on first request';
    gate(); await flush();
    // quick second request: finishes before the threshold -> never 'updating'
    env.status.length = 0; r.request('y'); await clock.advance(C.DEBOUNCE_MS + 1); await clock.advance(C.SLOW_INDICATOR_MS / 2); gate(); await flush();
    if (env.status.some((s) => s.kind === 'updating')) return 'dot shown for a fast refresh';
    // slow third request: dot appears past the threshold
    env.status.length = 0; r.request('z'); await clock.advance(C.DEBOUNCE_MS + 1); await clock.advance(C.SLOW_INDICATOR_MS + 1);
    if (!env.status.some((s) => s.kind === 'updating')) return 'dot missing for a slow refresh';
    gate(); await flush();
    if (env.status[env.status.length - 1].kind !== 'idle') return 'not idle after finish';
  });

  await check('green_cache_miss_409_keeps_surface_and_marks_stale', async () => {
    const { r, clock, env } = rig({ respond: async (b) => (b[C.REQ_GREEN_MODE] === C.GREEN_MODE_CACHED_ONLY ? errResp(C.HTTP_STATUS_CONFLICT, C.ERR_CODE_GREEN_CACHE_MISS) : okResp(b.seq)) });
    r.request('seed'); await clock.advance(C.DEBOUNCE_MS + 1);
    const before = env.surfaces.length;
    r.setDragging(true); r.request('drag'); await clock.advance(C.THROTTLE_MS + 1);
    if (env.surfaces.length !== before) return 'surface replaced by a 409';
    if (env.stale[env.stale.length - 1] !== true) return 'green not marked stale';
    r.setDragging(false); await clock.advance(C.RELEASE_MS + C.DEBOUNCE_MS + 1);
    if (env.stale[env.stale.length - 1] !== false) return 'stale not cleared by the release refresh';
    if (env.surfaces.length !== before + 1) return 'release refresh not applied';
  });

  await check('busy_503_keeps_surface_and_retries', async () => {
    let n = 0;
    const { r, clock, env } = rig({ respond: async (b) => (++n === 1 ? errResp(C.HTTP_STATUS_UNAVAILABLE, C.ERR_CODE_BUSY) : okResp(b.seq)) });
    r.request('x'); await clock.advance(C.DEBOUNCE_MS + 1);
    if (env.status[env.status.length - 1].kind !== 'busy') return 'no busy status';
    await clock.advance(C.BUSY_RETRY_MS + C.DEBOUNCE_MS + 1);
    if (env.calls.length !== 2 || env.surfaces.length !== 1) return 'no retry: calls=' + env.calls.length;
  });

  await check('server_error_and_network_failure_are_quiet_statuses', async () => {
    let mode = 'err';
    const { r, clock, env } = rig({ respond: async (b) => { if (mode === 'net') throw new Error('offline'); return errResp(500, 'internal_error', 'boom'); } });
    r.request('x'); await clock.advance(C.DEBOUNCE_MS + 1);
    const s1 = env.status[env.status.length - 1];
    if (s1.kind !== 'error' || !s1.message.includes('boom')) return 'error status wrong: ' + JSON.stringify(s1);
    mode = 'net'; r.request('y'); await clock.advance(C.DEBOUNCE_MS + 1);
    const s2 = env.status[env.status.length - 1];
    if (s2.kind !== 'error' || s2.message !== C.MSG_NETWORK) return 'network status wrong';
    if (env.surfaces.length) return 'surface drawn from an error';
  });

  await check('no_snapshot_means_needs_message_and_no_fetch', async () => {
    const { r, clock, env } = rig({ snap: null, respond: async (b) => okResp(b.seq) });
    r.request('x'); await clock.advance(C.DEBOUNCE_MS + 1);
    if (env.calls.length) return 'fetched without a snapshot';
    if (env.status[env.status.length - 1].kind !== 'needs') return 'no needs status';
  });

  await check('terrace_quantiser_matches_contract', async () => {
    const part = { heights: new Float32Array([0, 0.4, 1.0, 2.0, 9]), mask: new Uint8Array([1, 1, 1, 1, 0]), zmin: 0, zmax: 2 };
    const out = P.terraceHeights(part, 1.0);     // range 2 / step 1 -> 2 levels of 1.0
    const want = [0, 0, 1, 2, 9];
    if (want.some((v, i) => Math.abs(out[i] - v) > 1e-6)) return JSON.stringify(Array.from(out));
    if (part.heights[1] !== Math.fround(0.4)) return 'input mutated';
    const out0 = P.terraceHeights(part, 0);      // contourStep 0 -> TERRACE_DEFAULT_LEVELS levels
    const step = 2 / C.TERRACE_DEFAULT_LEVELS;
    if (Math.abs(out0[1] - Math.round(0.4 / step) * step) > 1e-5) return 'default-levels branch wrong';
  });

  await check('grid_mesh_skips_masked_triangles', async () => {
    const part = { nx: 3, ny: 2, xmin: 0, xmax: 2, ymin: 0, ymax: 1, mask: new Uint8Array([1, 1, 1, 1, 1, 0]) };
    const m = P.gridMeshArrays(part, new Float32Array([0, 0, 0, 1, 1, 1]));
    // quads: (0,1,3,4) full -> 2 tris; (1,2,4,5) has node 5 masked -> only tri (1,2,4)? tri(a,b,e)=(1,2,5) masked, tri(a,e,d)=(1,5,4) masked -> 0
    if (m.indices.length !== 2 * 3) return 'index count ' + m.indices.length;
    if (m.positions[3 * 4] !== 1 || m.positions[3 * 4 + 1] !== 1) return 'node xy wrong';
  });

  await check('snapshot_comes_from_memory_and_is_null_without_green', async () => {
    const st = { imgLoaded: true, selectedImage: 'a.png', selectedImageCourse: 'C', imgW: 10, imgH: 20, elevationRange: 5, zScale: 1,
      greenScale: 1, baseThicknessMm: 1.5, includeBoundaryRegion: false, flagOffsetXMm: 0, flagOffsetYMm: 0, gridMode: 'delta', gridN: 20,
      gridCellHeights: { 5: 1.5 }, teeHole: { x_mm: 1, y_mm: 2 },
      polygons: [{ name: 'g', type: C.POLY_TYPE_GREEN, points: [{ x: 1, y: 2 }] }] };
    const s = P.buildSnapshot(st);
    if (!s || s.polygons.length !== 1 || s.gridResolution !== 20 || s.tee_hole.x_mm !== 1) return 'bad snapshot ' + JSON.stringify(s);
    if ('greenStyle' in s || 'contourStep' in s) return 'style leaked to the server snapshot';
    st.polygons = []; if (P.buildSnapshot(st) !== null) return 'snapshot without green';
    st.polygons = [{ type: C.POLY_TYPE_GREEN, points: [] }]; st.imgLoaded = false; if (P.buildSnapshot(st) !== null) return 'snapshot before image load';
  });

  await check('signature_is_free_when_closed_and_changes_with_state', async () => {
    const st = { preview3dOpen: false, imgLoaded: true, selectedImage: 'a', polygons: [{ type: C.POLY_TYPE_GREEN, points: [{ x: 1, y: 1 }] }], gridCellHeights: {} };
    if (P.signature(st) !== '') return 'not empty when closed';
    st.preview3dOpen = true; const a = P.signature(st);
    st.gridCellHeights = { 3: 2 }; const b = P.signature(st);
    if (a === b) return 'signature ignored a cell change';
    st.greenStyle = C.GREEN_STYLE_TERRACED; st.contourStep = 0.5;
    if (P.signature(st) !== b) return 'greenStyle/contourStep must not change the server signature';
    if (P.styleSignature(st) === '') return 'style signature empty while open';
  });

  console.log(JSON.stringify(results));
})();
