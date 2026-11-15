// In-memory fdd.rule_config for hooks/tuning.js tests: the statements hooks/lib/timescale.js issues, with real
// transaction semantics (BEGIN snapshots the store, ROLLBACK restores it), so a test can prove a write is all-or-nothing.
export function ruleConfigClient({ failInsert = null } = {}) {
  let store = [];
  let snapshot = null;
  let seq = 0;
  const clone = (rows) => rows.map((r) => ({ ...r }));
  const client = {
    get rows() { return store; },
    failInsert,
    async query(sql, params = []) {
      const s = String(sql);
      if (s === "BEGIN") { snapshot = clone(store); return { rows: [] }; }
      if (s === "COMMIT") { snapshot = null; return { rows: [] }; }
      if (s === "ROLLBACK") { if (snapshot) store = snapshot; snapshot = null; return { rows: [] }; }
      if (s.includes("to_regclass('fdd.point')")) return { rows: [{ ok: true }] };
      if (s.includes("pg_advisory_xact_lock")) return { rows: [] };
      const pick = (site, rid, scope) => store.filter((r) => r.site_id === site && r.rule_id === rid && r.scope_key === scope);
      if (s.includes("SELECT site_id, rule_id, scope_key, revision, parameters FROM fdd.rule_config")) {
        const [rid, site] = params;
        return { rows: store.filter((r) => (!rid || r.rule_id === rid) && (!site || r.site_id === site) && r.active) };
      }
      if (s.includes("SELECT revision FROM fdd.rule_config") && s.includes("AND active")) return { rows: pick(...params).filter((r) => r.active) };
      if (s.includes("SELECT parameters FROM fdd.rule_config")) return { rows: pick(params[0], params[1], params[2]).filter((r) => r.revision === params[3]) };
      if (s.includes("FROM fdd.rule_config") && s.includes("ORDER BY revision DESC LIMIT")) {
        return { rows: pick(params[0], params[1], params[2]).sort((a, b) => b.revision - a.revision).slice(0, params[3]) };
      }
      if (s.includes("coalesce(max(revision), 0) + 1 AS rev")) return { rows: [{ rev: pick(...params).reduce((m, r) => Math.max(m, r.revision), 0) + 1 }] };
      if (s.includes("UPDATE fdd.rule_config SET active = false")) { for (const r of pick(...params)) r.active = false; return { rows: [] }; }
      if (s.includes("INSERT INTO fdd.rule_config")) {
        const [site, rid, scope, rev, json, by] = params;
        if (client.failInsert && client.failInsert(rid)) throw new Error(`simulated write failure on ${rid}`);
        store.push({ site_id: site, rule_id: rid, scope_key: scope, revision: rev, parameters: JSON.parse(json), created_by: by,
          created_at: new Date(Date.UTC(2026, 10, 1) + (++seq) * 1000), active: true });
        return { rows: [] };
      }
      throw new Error(`unexpected SQL in ruleConfigClient: ${s}`);
    },
  };
  return client;
}