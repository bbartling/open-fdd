// Review follow-ups: the pager refuses overlapping offset pages and enforces maxRecords after a page; the weather mirror
// never overwrites an analog value it did not create.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const paging = require("../hooks/lib/paging.js");
const fullWeather = require("../hooks/weather.js");
const liteWeather = require("../../lite/hooks/open_meteo_weather.js");

const rec = (uuid) => ({ uuid, name: uuid });
const list = (n, prefix = "p") => Array.from({ length: n }, (_, i) => rec(`${prefix}-${String(i).padStart(4, "0")}`));

test("pager: an insert between offset pages (a repeated record) is a PagingError, not a short list", async () => {
  const all = list(10);
  let calls = 0;
  const serve = async ({ pageSize, pageOffset = 0 }) => {
    calls += 1;
    // page 2 is read after a record was inserted at the front: it repeats the last record of page 1 and the tail shifts
    const view = calls === 1 ? all : [rec("new-0000"), ...all];
    return { points: view.slice(pageOffset, pageOffset + pageSize), totalCount: String(all.length) };
  };
  await assert.rejects(paging.pageAll(serve, { pageSize: 5 }), /pages overlapped \(9 distinct of totalCount 10/);
});

test("pager: one page larger than maxRecords is refused", async () => {
  const all = list(500);
  const serve = async ({ pageSize, pageOffset = 0 }) => ({ points: all.slice(pageOffset, pageOffset + pageSize), totalCount: "500" });
  await assert.rejects(paging.pageAll(serve, { pageSize: 500, maxRecords: 100 }), /paging cap reached after 500 records \(maxRecords 100/);
  assert.equal((await paging.pageAll(serve, { pageSize: 500, maxRecords: 500 })).length, 500);
});

for (const [ed, hook] of [["full", fullWeather], ["lite", liteWeather]]) {
  test(`[${ed}] weather mirror leaves a foreign analog value on a configured instance untouched`, async () => {
    const named = (instance, name) => ({ objectId: { objectType: "OBJECT_ANALOG_VALUE", instance },
      props: [{ property: "PROP_OBJECT_NAME", value: { characterString: name } }] });
    const writes = [];
    const logs = [];
    const sdk = { http: {
      get: async () => ({ data: { objects: [named(1, "Chiller Setpoint"), named(2, "WEB OA-H")] } }),
      post: async (url, body) => { writes.push(["POST", body.objectId.instance]); return { data: {} }; },
      patch: async (url, body) => { writes.push(["PATCH", body.objectId.instance]); return { data: {} }; },
    } };
    const objects = hook.bacnetObjects("Site", [1, 2, 3]);
    const out = await hook.mirrorToBacnet(sdk, objects, { oa_dry_bulb_web: 50, oa_rh_web: 40, oa_dewpoint_web: 30 }, "now", (m) => logs.push(m));
    assert.deepEqual(writes, [["PATCH", 2], ["POST", 3]], "av.1 belongs to someone else: no write");
    assert.deepEqual(Object.keys(out), ["av.2", "av.3"]);
    assert.ok(logs.some((m) => /av\.1 is "Chiller Setpoint".*left untouched/.test(m)), logs.join(" | "));
  });
}
