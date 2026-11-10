// The dev mock NF (nf-app/dev/mock-nf.mjs): write endpoints + the mock-only debug route.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";

const MOCK = fileURLToPath(new URL("../dev/mock-nf.mjs", import.meta.url));
let child, base;

const freePort = () => new Promise((resolve, reject) => {
  const s = net.createServer();
  s.once("error", reject);
  s.listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => resolve(port)); });
});
const post = (p, body) => fetch(base + p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const writes = async () => (await fetch(base + "/api/v1/_mock/writes")).json();

before(async () => {
  const port = await freePort();
  base = `http://127.0.0.1:${port}`;
  child = spawn(process.execPath, [MOCK, String(port)], { stdio: ["ignore", "pipe", "inherit"] });
  await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (c) => reject(new Error("mock exited " + c)));
    child.stdout.on("data", (d) => { if (String(d).includes("mock NF:")) resolve(); });
  });
});
after(() => { child.removeAllListeners("exit"); child.kill(); });

test("mock NF: starts empty, stores point/points, point/data and the batched points/data writes", async () => {
  assert.deepEqual(await writes(), { points: [], data: [], calls: [] });

  let r = await post("/api/v1/point/points", { points: [{ uuid: "u1", name: "a", layer: "model" }, { uuid: "u2", name: "b", layer: "automation" }] });
  assert.equal(r.status, 200);
  assert.deepEqual((await r.json()).results.map((x) => [x.uuid, x.success]), [["u1", true], ["u2", true]]);

  r = await post("/api/v1/point/data", { uuid: "u1", values: [{ ts: "2026-11-05T12:00:00Z", real: 1.5 }] });
  assert.equal(r.status, 200);
  assert.deepEqual(await r.json(), { success: true });

  r = await post("/api/v1/points/data", { points: [
    { uuid: "u1", values: [{ ts: "2026-11-05T12:05:00Z", real: 2 }] },
    { uuid: "u2", values: [{ ts: "2026-11-05T12:05:00Z", real: 3 }] },
  ] });
  assert.equal(r.status, 200);
  assert.deepEqual(await r.json(), { success: true });

  const w = await writes();
  assert.deepEqual(w.points.map((p) => p.uuid), ["u1", "u2"]);
  assert.deepEqual(w.data.map((d) => [d.uuid, d.values[0].real]), [["u1", 1.5], ["u1", 2], ["u2", 3]]);
  assert.deepEqual(w.calls, [{ route: "/api/v1/point/points", n: 2 }, { route: "/api/v1/point/data", n: 1 }, { route: "/api/v1/points/data", n: 2 }]);
});

test("mock NF: rejects malformed writes with 400 and survives them; DELETE clears the store", async () => {
  assert.equal((await post("/api/v1/points/data", { points: [{ values: [] }] })).status, 400);
  assert.equal((await post("/api/v1/points/data", {})).status, 400);
  assert.equal((await post("/api/v1/point/points", { points: "x" })).status, 400);
  assert.equal((await post("/api/v1/point/data", { values: [] })).status, 400);
  const bad = await fetch(base + "/api/v1/point/points", { method: "POST", body: "{not json" });
  assert.equal(bad.status, 400);
  assert.equal((await fetch(base + "/api/v1/platform/info")).status, 200, "still up");
  assert.equal((await fetch(base + "/api/v1/_mock/writes", { method: "DELETE" })).status, 200);
  assert.deepEqual(await writes(), { points: [], data: [], calls: [] });
});

test("mock NF: the GET history route still works next to the POST data route", async () => {
  const r = await fetch(base + "/api/v1/point/data?uuids=nope&window=300s&method=AVERAGE");
  assert.equal(r.status, 200);
  assert.deepEqual((await r.json()).data, [{ uuid: "nope", values: [] }]);
});

test("mock NF: UpdatePoints merges attrs within a layer, including explicit empty values", async () => {
  const basePoint = { uuid: "fixture-merge", name: "fixture", layer: "model" };
  assert.equal((await post("/api/v1/point/points", { points: [
    { ...basePoint, attrs: { a: "1", b: "2" } },
    { ...basePoint, layer: "automation", attrs: { a: "other layer" } },
  ] })).status, 200);
  const findPoint = async () => (await (await post("/api/v1/point/query", { layer: "model", pageSize: 500 })).json())
    .points.find(({ uuid }) => uuid === basePoint.uuid);
  assert.equal((await post("/api/v1/point/points", { points: [{ ...basePoint, attrs: { a: "3" } }] })).status, 200);
  assert.deepEqual((await findPoint()).attrs, { a: "3", b: "2" });
  assert.equal((await post("/api/v1/point/points", { points: [{ ...basePoint, attrs: { b: "" } }] })).status, 200);
  assert.deepEqual((await findPoint()).attrs, { a: "3", b: "" });
  assert.equal((await post("/api/v1/point/points", { points: [{ ...basePoint, attrs: { a: null } }] })).status, 200);
  assert.deepEqual((await findPoint()).attrs, { a: "", b: "" });
  const automation = await (await post("/api/v1/point/query", { layer: "automation", pageSize: 500 })).json();
  assert.deepEqual(automation.points.find(({ uuid }) => uuid === basePoint.uuid).attrs, { a: "other layer" });
});

test("mock NF: omitted page size is empty, offsets are ordered, and tokens are ignored on 3.10.9-1", async () => {
  const query = async (args) => (await post("/api/v1/point/query", { layer: "model", ...args })).json();
  const empty = await query({});
  assert.equal(empty.points.length, 0);
  assert.ok(Number(empty.totalCount) > 4);
  const first = await query({ pageSize: 2 });
  assert.deepEqual(await query({ pageSize: 2, pageToken: "ignored" }), first);
  const next = await query({ pageSize: 2, pageOffset: 2 });
  assert.equal(next.totalCount, first.totalCount);
  const ids = [...first.points, ...next.points].map((point) => point.uuid);
  assert.equal(new Set(ids).size, 4);
  assert.deepEqual(ids, [...ids].sort());
  assert.equal((await post("/api/v1/point/query", { pageSize: 2, pageOffset: -1 })).status, 400);
});

test("real mock rejects unchunked history for 161 and 709 UUIDs and the browser merges bounded reads", async () => {
  const seed = await (await post("/api/v1/point/query", { pageSize: 500 })).json();
  const known = [...new Set(seed.points.filter((p) => p.latestValue).map((p) => p.uuid))];
  assert.ok(known.length >= 2);
  const requests = [];
  const ctx = createContext({
    parseTs: Date.parse,
    api: async (url) => {
      requests.push(url);
      const res = await fetch(base + url);
      assert.equal(res.status, 200);
      return res.json();
    },
  });
  runInContext(readFileSync(new URL("../static/charts.js", import.meta.url), "utf8"), ctx);
  for (const count of [161, 709]) {
    const points = Array.from({ length: count }, (_, i) => ({
      uuid: `00000000-0000-4000-8000-${(count * 1000 + i).toString(16).padStart(12, "0")}`,
    }));
    points[0].uuid = known[0];
    points[count - 1].uuid = known[1];
    const end = Date.now();
    const url = ctx.historyUrl(points, new Date(end - 86400e3).toISOString(),
      new Date(end).toISOString(), 3600, "AVERAGE");
    assert.equal((await fetch(base + url)).status, 431, `${count} UUIDs exceed the mock front door`);
    const before = requests.length;
    const merged = await ctx.fetchSeries(points, 24, { windowSec: 3600 });
    assert.equal(merged.size, count);
    assert.ok(merged.get(known[0]).length && merged.get(known[1]).length, "first and last chunks both contribute samples");
    const used = requests.slice(before);
    assert.ok(used.length > 1 && used.every((path) => Buffer.byteLength(path) < 6500));
  }
  assert.equal((await fetch(base + "/api/v1/platform/info", { headers: { "x-test-padding": "x".repeat(8300) } })).status, 431);
});
