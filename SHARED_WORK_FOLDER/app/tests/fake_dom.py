"""Minimal fake DOM + localStorage for node-run tests of the v6.12 in-page notice dialog (showNoticeDialog)."""

# Provide FAKE_DOM_JS before running editor code. Records each opened notice as ['notice', message] in window.dialogs.
# globalThis.__autoOk = true  -> the OK button is pressed as soon as the dialog opens (keeps old synchronous flows moving).
FAKE_DOM_JS = r"""
globalThis.__store = {}; globalThis.__storeBroken = false;
globalThis.localStorage = {
  getItem(k) { if (globalThis.__storeBroken) throw new Error('x'); return k in globalThis.__store ? globalThis.__store[k] : null; },
  setItem(k, v) { if (globalThis.__storeBroken) throw new Error('x'); globalThis.__store[k] = String(v); },
  removeItem(k) { if (globalThis.__storeBroken) throw new Error('x'); delete globalThis.__store[k]; } };
class FakeEl {
  constructor(tag) { this.tagName = tag.toUpperCase(); this.children = []; this.parentNode = null; this.id = ''; this.className = '';
    this.textContent = ''; this.checked = false; this.attrs = {}; this.handlers = {}; this.style = {}; }
  setAttribute(k, v) { this.attrs[k] = v; }
  appendChild(c) { c.parentNode = this; this.children.push(c); if (this === document.body && globalThis.__onBody) globalThis.__onBody(c); return c; }
  removeChild(c) { this.children = this.children.filter(x => x !== c); c.parentNode = null; return c; }
  addEventListener(t, f) { (this.handlers[t] = this.handlers[t] || []).push(f); }
  focus() { document.activeElement = this; }
  click() { (this.handlers.click || []).forEach(f => f({stopPropagation() {}})); }
  find(id) { if (this.id === id) return this; for (const c of this.children) { const r = c.find(id); if (r) return r; } return null; }
  text() { return this.textContent + this.children.map(c => c.text()).join(''); }
}
const __docL = [];
globalThis.document = { body: new FakeEl('body'), activeElement: null, createElement: (t) => new FakeEl(t),
  getElementById(id) { return this.body.find(id); },
  addEventListener(t, f, cap) { __docL.push([t, f, cap]); }, removeEventListener(t, f) { const i = __docL.findIndex(x => x[1] === f); if (i >= 0) __docL.splice(i, 1); },
  // dispatch a keydown the way the browser would: the capture listener first; returns true if the page's own handler would still see it
  key(k, kw = {}) { const e = Object.assign({key: k, shiftKey: false, prevented: false, stopped: false,
      preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; }}, kw);
    __docL.filter(x => x[0] === 'keydown').forEach(x => x[1](e)); return e; },
  listeners: () => __docL.length };
document.body.focus = () => {};
window.dialogs = window.dialogs || [];
globalThis.__onBody = (c) => {
  if (c.id !== NOTICE_BACKDROP_ID) return;
  window.dialogs.push(['notice', c.find(NOTICE_MESSAGE_ID).textContent]);
  if (globalThis.__autoOk) c.find(NOTICE_OK_ID).click();
};
globalThis.__autoOk = true;
"""
