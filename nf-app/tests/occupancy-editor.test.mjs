// The Overview occupancy editor must render without throwing, and its day-row
// controls must use the calendar field names (occupied / start / end).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const dir = new URL("../static/", import.meta.url);

function el(tag) {
  const e = {
    tagName: String(tag).toUpperCase(),
    children: [],
    textContent: "",
    hidden: false,
    isConnected: true,
    className: "",
    type: "",
    value: "",
    checked: false,
    disabled: false,
    id: "",
    classList: { add() {}, remove() {} },
    setAttribute() {},
    addEventListener() {},
    append(...nodes) {
      for (const n of nodes) {
        if (!n) continue;
        this.children.push(n);
        n.isConnected = true;
      }
    },
    replaceChildren(...nodes) {
      this.children = [];
      this.append(...nodes);
    },
  };
  return e;
}

function walk(node, acc = []) {
  acc.push(node);
  for (const c of node.children || []) walk(c, acc);
  return acc;
}

test("Overview occupancy editor draws a calendar without throwing on .disabled", async () => {
  const host = el("section");
  host.id = "overviewOccupancy";
  const byId = new Map([["overviewOccupancy", host]]);
  const ctx = vm.createContext({
    console,
    Date,
    Math,
    JSON,
    Intl,
    setTimeout,
    clearTimeout,
    document: {
      getElementById: (id) => byId.get(id) || null,
      createElement: (tag) => {
        const e = el(tag);
        const desc = Object.getOwnPropertyDescriptor(e, "id");
        Object.defineProperty(e, "id", {
          get: () => desc.get ? desc.get.call(e) : e._id || "",
          set(v) { e._id = v; if (v) byId.set(v, e); },
          configurable: true,
          enumerable: true,
        });
        return e;
      },
    },
  });
  for (const f of ["occupancy.js", "occupancy-editor.js"]) {
    vm.runInContext(readFileSync(new URL(f, dir), "utf8"), ctx, { filename: f });
  }
  ctx.ofddTuning = { callHook: async () => ({ ok: true, source: "default", calendar: null, active: {} }) };
  await assert.doesNotReject(() => ctx.ofddOccupancyEditor.render({
    site: "acme",
    timezone: "America/Chicago",
    onChange: () => {},
  }));
  const nodes = walk(host);
  const occupied = nodes.filter((n) => n.type === "checkbox");
  const times = nodes.filter((n) => n.type === "time");
  assert.equal(occupied.length, 7, "one Occupied checkbox per day");
  assert.equal(times.length, 14, "start and end time inputs per day");
  assert.equal(occupied.filter((n) => n.checked).length, 5, "Mon-Fri occupied by default");
  assert.ok(nodes.some((n) => /60/.test(String(n.textContent))), "default calendar is 60 h/week");
  assert.ok(occupied.every((n) => n.disabled === false), "inputs stay enabled after the first draw");
  const src = readFileSync(new URL("occupancy-editor.js", dir), "utf8");
  assert.match(src, /\["occupied", "checkbox"\]/);
  assert.doesNotMatch(src, /\["occupancy_status", "checkbox"\]/);
});
