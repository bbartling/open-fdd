// #1643: Overview draws RCx cards lazily (static/lazy-cards.js). An IntersectionObserver double drives visibility.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const src = readFileSync(new URL("../static/lazy-cards.js", import.meta.url), "utf8");

function harness(n, { concurrency = 2 } = {}) {
  /** @type {any} */
  let observer = null;
  class FakeObserver {
    constructor(cb, opts) { this.cb = cb; this.opts = opts; this.watched = new Set(); this.disconnected = false; observer = this; }
    observe(el) { this.watched.add(el); }
    unobserve(el) { this.watched.delete(el); }
    disconnect() { this.watched.clear(); this.disconnected = true; }
    show(...els) { this.cb(els.filter((el) => this.watched.has(el)).map((target) => ({ target, isIntersecting: true }))); }
  }
  const ctx = vm.createContext({ Promise });
  vm.runInContext(src, ctx, { filename: "lazy-cards.js" });
  const els = Array.from({ length: n }, (_, i) => ({ id: `card-${i}` }));
  const started = [], pending = new Map();
  let live = true, done = 0;
  const draw = (i) => { started.push(i); return new Promise((resolve, reject) => pending.set(i, { resolve, reject })); };
  const stop = ctx.lazyDrawCards({ els, draw, isLive: () => live, onDone: () => { done++; }, concurrency,
    rootMargin: "600px 0px", Observer: FakeObserver });
  const settle = () => new Promise((r) => setImmediate(r));
  const finish = async (i, fail = false) => { const p = pending.get(i); if (fail) p.reject(new Error("draw failed")); else p.resolve(); pending.delete(i); await settle(); };
  return { els, started, finish, settle, stop, observer: () => observer, setLive: (v) => { live = v; }, done: () => done };
}

test("offscreen cards never draw; the margin is passed to the observer", async () => {
  const h = harness(6);
  await h.settle();
  assert.deepEqual(h.started, []);
  assert.equal(h.observer().opts.rootMargin, "600px 0px");
  assert.equal(h.observer().watched.size, 6);
});

test("at most two cards draw at once, and the queue moves on as each finishes", async () => {
  const h = harness(6);
  h.observer().show(...h.els.slice(0, 4));
  await h.settle();
  assert.deepEqual(h.started, [0, 1]);
  await h.finish(0);
  assert.deepEqual(h.started, [0, 1, 2]);
  await h.finish(1);
  await h.finish(2);
  await h.finish(3);
  assert.deepEqual(h.started, [0, 1, 2, 3]);
  assert.equal(h.done(), 0, "cards 4 and 5 have not been seen yet");
  h.observer().show(h.els[4], h.els[5]);
  await h.settle();
  await h.finish(4);
  await h.finish(5);
  assert.equal(h.done(), 1);
});

test("leaving the tab (isLive false) stops queued cards and disconnects the observer", async () => {
  const h = harness(6);
  h.observer().show(...h.els.slice(0, 4));
  await h.settle();
  h.setLive(false);                    // e.g. showTab("charts"): activeTab is no longer "overview"
  await h.finish(0);                   // in-flight work may finish, but nothing new starts
  await h.finish(1);
  assert.deepEqual(h.started, [0, 1]);
  assert.ok(h.observer().disconnected);
  assert.equal(h.done(), 0);
});

test("a newer render's stop() drops the old queue", async () => {
  const h = harness(4);
  h.observer().show(...h.els);
  await h.settle();
  h.stop();
  await h.finish(0);
  await h.finish(1);
  assert.deepEqual(h.started, [0, 1]);
  assert.ok(h.observer().disconnected);
});

test("a failed card still frees its slot", async () => {
  const h = harness(3, { concurrency: 1 });
  h.observer().show(...h.els);
  await h.settle();
  assert.deepEqual(h.started, [0]);
  await h.finish(0, true);
  assert.deepEqual(h.started, [0, 1]);
});

test("Overview wires the queue to the active tab and the render run", () => {
  const app = readFileSync(new URL("../static/app.js", import.meta.url), "utf8");
  assert.match(app, /isLive: \(\) => run === viewTabRuns\[tab\] && activeTab === "overview"/);
  const html = readFileSync(new URL("../static/index.html", import.meta.url), "utf8");
  assert.ok(html.indexOf('src="lazy-cards.js"') < html.indexOf('src="app.js"'), "lazy-cards.js loads before app.js");
  const manifest = JSON.parse(readFileSync(new URL("../app.json", import.meta.url), "utf8"));
  assert.ok(JSON.stringify(manifest).includes('"/static/lazy-cards.js"'), "app.json ships lazy-cards.js");
});
