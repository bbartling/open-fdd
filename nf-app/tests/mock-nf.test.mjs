// The dev mock NF (nf-app/dev/mock-nf.mjs): write endpoints + the mock-only debug route.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import net from "node:net";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

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
