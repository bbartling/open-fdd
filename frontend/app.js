// Open-FDD Rust Edge: algorithm + modeling dashboard prototype.
// Plain React + Plotly from CDNs so Docker Desktop can serve it fast.

const { useEffect, useMemo, useState } = React;

const authStore = {
  get token() { return localStorage.getItem("openfdd_edge_jwt") || ""; },
  set token(v) { localStorage.setItem("openfdd_edge_jwt", v); },
  clear() { localStorage.removeItem("openfdd_edge_jwt"); },
};

const api = {
  headers() {
    const headers = { "Content-Type": "application/json" };
    if (authStore.token) headers.Authorization = `Bearer ${authStore.token}`;
    return headers;
  },
  async login(role = "integrator") {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sub: "ui-agent", role }),
    });
    if (!res.ok) throw new Error(`/api/auth/login -> ${res.status}`);
    const data = await res.json();
    authStore.token = data.access_token;
    return data;
  },
  async get(path) {
    const res = await fetch(path, { headers: this.headers() });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  },
  async post(path, body = {}) {
    const res = await fetch(path, {
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  },
};

const tabs = [
  ["overview", "Open-FDD"],
  ["bridge", "Bridge API"],
  ["commission", "BACnet Commission"],
  ["poll", "BACnet Poll"],
  ["haystack", "Haystack Model"],
  ["assignments", "Assignments"],
  ["algorithms", "CDL Algorithms"],
  ["fdd", "DataFusion FDD"],
  ["rulelab", "Rule Lab"],
  ["modbus", "Modbus"],
  ["json", "JSON API"],
  ["reports", "Reports"],
  ["agent", "AI API"],
  ["ops", "Ops"],
];

function Pill({ label, tone = "neutral" }) {
  return React.createElement("span", { className: `pill ${tone}` }, label);
}

function MetricCard({ label, value, sub, tone = "" }) {
  return React.createElement("div", { className: `metric-card ${tone}` },
    React.createElement("div", { className: "metric-label" }, label),
    React.createElement("div", { className: "metric-value" }, value),
    sub && React.createElement("div", { className: "metric-sub" }, sub)
  );
}

function Section({ title, kicker, children, actions }) {
  return React.createElement("section", { className: "panel" },
    React.createElement("div", { className: "panel-head" },
      React.createElement("div", null,
        kicker && React.createElement("div", { className: "kicker" }, kicker),
        React.createElement("h2", null, title)
      ),
      actions && React.createElement("div", { className: "actions" }, actions)
    ),
    children
  );
}

function DataTable({ rows }) {
  if (!rows || rows.length === 0) return React.createElement("p", { className: "muted" }, "No rows yet.");
  const columns = Object.keys(rows[0]);
  return React.createElement("div", { className: "table-wrap" },
    React.createElement("table", null,
      React.createElement("thead", null,
        React.createElement("tr", null, columns.map(c => React.createElement("th", { key: c }, c)))
      ),
      React.createElement("tbody", null,
        rows.map((row, i) => React.createElement("tr", { key: i },
          columns.map(c => React.createElement("td", { key: c }, typeof row[c] === "object" ? JSON.stringify(row[c]) : String(row[c])))
        ))
      )
    )
  );
}

function Chart({ rows }) {
  useEffect(() => {
    if (!rows || !rows.length || !window.Plotly) return;
    const x = rows.map(r => r.ts);
    const data = [
      { x, y: rows.map(r => r.sat), name: "SAT", type: "scatter", mode: "lines+markers" },
      { x, y: rows.map(r => r.sat_sp), name: "SAT SP", type: "scatter", mode: "lines" },
      { x, y: rows.map(r => r.duct_static), name: "Duct Static", type: "scatter", mode: "lines+markers", yaxis: "y2" },
      { x, y: rows.map(r => r.duct_static_sp), name: "Duct Static SP", type: "scatter", mode: "lines", yaxis: "y2" },
    ];
    const layout = {
      margin: { l: 42, r: 42, t: 24, b: 42 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "#dbeafe" },
      legend: { orientation: "h" },
      xaxis: { gridcolor: "rgba(148,163,184,.15)" },
      yaxis: { title: "Temp °F", gridcolor: "rgba(148,163,184,.15)" },
      yaxis2: { title: "in.w.c.", overlaying: "y", side: "right", gridcolor: "rgba(148,163,184,.08)" },
    };
    Plotly.newPlot("trend-chart", data, layout, { responsive: true, displayModeBar: false });
  }, [rows]);
  return React.createElement("div", { id: "trend-chart", className: "plot" });
}

function Overview({ state }) {
  const faults = state.fdd?.faults || [];
  const overrides = state.overrides?.overrides || [];
  return React.createElement("div", { className: "grid" },
    React.createElement("div", { className: "metrics" },
      React.createElement(MetricCard, { label: "Site health", value: "82%", sub: "demo edge score", tone: "good" }),
      React.createElement(MetricCard, { label: "Active faults", value: faults.length, sub: "DataFusion SQL" }),
      React.createElement(MetricCard, { label: "Overrides", value: overrides.length, sub: "priority-array scan" }),
      React.createElement(MetricCard, { label: "Points modeled", value: (state.haystack?.rows || []).filter(r => r.point).length, sub: "Haystack grid" })
    ),
    React.createElement(Section, { title: "Building telemetry", kicker: "Apache Arrow rows → Plotly.js" },
      React.createElement(Chart, { rows: state.arrowRows || [] })
    ),
    React.createElement(Section, { title: "Current fault leaderboard", kicker: "Rust DataFusion SQL output" },
      React.createElement(DataTable, { rows: faults })
    ),
    React.createElement(Section, { title: "RCx reporting", kicker: "agent-drivable report generation" },
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/reports/rcx/generate", {}), null, 2)) }, "Generate RCx Report")
    )
  );
}


function Assignments({ state }) {
  const [assignments, setAssignments] = useState(null);
  const [bindings, setBindings] = useState(null);
  useEffect(() => {
    api.get("/api/model/assignments").then(setAssignments).catch(() => {});
    api.get("/api/model/algorithm-bindings").then(setBindings).catch(() => {});
  }, []);
  const rows = assignments?.points || [];
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "AI Assignment Matrix", kicker: "Haystack refs are the contract" },
      React.createElement("p", null, "AI agents assign driver points, fault equation inputs, historian storage refs, external refs, and CDL algorithm I/O through Haystack IDs. Algorithms never care whether the source is BACnet, Modbus, JSON API, or Haystack."),
      React.createElement(DataTable, { rows: rows.map(r => ({
        haystack_id: r.haystack_id,
        dis: r.dis,
        kind: r.kind,
        equip_ref: r.equip_ref,
        unit: r.unit,
        storage_ref: r.storage_ref,
        driver_bindings: (r.driver_bindings || []).map(b => `${b.driver}:${b.ref}`).join(", ")
      })) })
    ),
    React.createElement(Section, { title: "Fault Equation Bindings", kicker: "DataFusion SQL inputs resolve by Haystack ID" },
      React.createElement(DataTable, { rows: assignments?.fault_equation_bindings || [] }),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/model/assignments/save", { scope: "fault_equation_bindings" }), null, 2)) }, "Save Fault Bindings")
    ),
    React.createElement(Section, { title: "CDL Algorithm Bindings", kicker: "protocol agnostic algorithm I/O" },
      React.createElement("pre", null, JSON.stringify(bindings || assignments?.algorithm_bindings || {}, null, 2)),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/control/cdl/bindings/save", { algorithm_id: "g36_ahu_vav_trim_respond" }), null, 2)) }, "Save CDL Bindings"),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/model/assignments/resolve", { haystack_id: "point:sat" }), null, 2)) }, "Resolve point:sat")
    )
  );
}


function Algorithms({ state }) {
  const algorithms = [
    { name: "G36 AHU/VAV Trim & Respond", status: "running", input: "zone calls + duct pressure + SAT", output: "duct static SP / SAT SP", mode: "CDL" },
    { name: "SAT Deviation Detector", status: "active", input: "sat, sat_sp, fan_cmd", output: "SAT_DEVIATION_HIGH", mode: "DataFusion SQL" },
    { name: "Duct Static Deviation", status: "active", input: "duct_static, duct_static_sp", output: "DUCT_STATIC_DEVIATION", mode: "DataFusion SQL" },
    { name: "Supervisory Override Watch", status: "hourly", input: "BACnet priority-array", output: "operator/supervisory overrides", mode: "BACnet RP" },
  ];
  return React.createElement("div", { className: "algo-grid" },
    algorithms.map(a => React.createElement("div", { className: "algo-card", key: a.name },
      React.createElement("div", { className: "algo-top" },
        React.createElement("h3", null, a.name),
        React.createElement(Pill, { label: a.mode, tone: a.status === "running" ? "green" : "blue" })
      ),
      React.createElement("p", null, a.input),
      React.createElement("div", { className: "flowline" },
        React.createElement("span", null, "inputs"),
        React.createElement("b", null, "→"),
        React.createElement("span", null, a.output)
      ),
      React.createElement("div", { className: "algo-status" }, a.status)
    )),
    React.createElement(Section, { title: "Control sequence snapshot", kicker: "open-control-engine / CDL concept" },
      React.createElement("pre", null, JSON.stringify(state.control || {}, null, 2)),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.get("/api/control/cdl/bindings"), null, 2)) }, "Show CDL Bindings")
    )
  );
}

function Model({ state }) {
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "Haystack entity graph", kicker: "site / equip / point / protocol refs", actions:
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/haystack/read", { filter: "site or equip or point" }), null, 2)) }, "Haystack Read/Nav")
    },
      React.createElement(DataTable, { rows: state.haystack?.rows || [] })
    ),
    React.createElement(Section, { title: "Protocol mapping", kicker: "One model, many drivers" },
      React.createElement("div", { className: "model-map" },
        React.createElement("div", null, React.createElement("b", null, "AHU-1"), React.createElement("span", null, "equip")),
        React.createElement("div", null, React.createElement("b", null, "BACnet analog-input:1"), React.createElement("span", null, "SAT")),
        React.createElement("div", null, React.createElement("b", null, "Modbus 40001"), React.createElement("span", null, "CHWST")),
        React.createElement("div", null, React.createElement("b", null, "JSON API OAT"), React.createElement("span", null, "weather compare"))
      )
    )
  );
}

function Fdd({ state }) {
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "DataFusion SQL rule", kicker: "100% Rust Apache Arrow runtime" },
      React.createElement("pre", { className: "sql" }, state.fdd?.sql || "loading SQL...")
    ),
    React.createElement(Section, { title: "Fault results", kicker: "Arrow RecordBatch → DataFusion collect" },
      React.createElement(DataTable, { rows: state.fdd?.faults || [] })
    ),
    React.createElement(Section, { title: "Rule Lab", kicker: "save and batch-run SQL rules" },
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/rules/save", { id: "custom_sql_rule", engine: "datafusion_sql" }), null, 2)) }, "Save DataFusion SQL Rule"),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/rules/batch", {}), null, 2)) }, "Run Rule Batch")
    ),
    React.createElement(Section, { title: "Raw Arrow-shaped telemetry", kicker: "JSON view of demo RecordBatch rows for UI plotting" },
      React.createElement(DataTable, { rows: state.arrowRows || [] })
    )
  );
}

function Bacnet({ state, reload }) {
  const [busy, setBusy] = useState(false);
  const [devices, setDevices] = useState(state.devices || []);
  async function whois() {
    setBusy(true);
    try { setDevices(await api.post("/api/bacnet/whois")); }
    finally { setBusy(false); }
  }
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "BACnet commissioning", kicker: "Who-Is / I-Am / ReadProperty / priority-array", actions:
      React.createElement("button", { onClick: whois, disabled: busy }, busy ? "Scanning..." : "Broadcast Who-Is")
    },
      React.createElement(DataTable, { rows: devices })
    ),
    React.createElement(Section, { title: "Hourly override scanner", kicker: "Writable points → ReadProperty(priority-array)" },
      React.createElement(DataTable, { rows: state.overrides?.overrides || [] })
    ),
    React.createElement(Section, { title: "BACnet point registry", kicker: "commissioned points", actions:
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.get("/api/bacnet/driver/tree"), null, 2)) }, "Show Driver Tree")
    },
      React.createElement(DataTable, { rows: state.points || [] })
    )
  );
}

function Modbus({ state }) {
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "Modbus driver", kicker: "rusty-modbus integration path" },
      React.createElement(DataTable, { rows: state.modbus || [] })
    ),
    React.createElement(Section, { title: "Use case", kicker: "Plant and meter telemetry" },
      React.createElement("p", null, "Modbus points can be normalized into the same Arrow table and Haystack model as BACnet and JSON API points, then used by DataFusion SQL fault rules.")
    )
  );
}

function JsonApi({ state }) {
  const [form, setForm] = useState({ id: "weather-oat", url: "https://api.openweathermap.org/data/2.5/weather", maps_to: "outside_air_temperature" });
  const [result, setResult] = useState(null);
  async function submit() {
    setResult(await api.post("/api/json-api/register", form));
  }
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "JSON API source registration", kicker: "external telemetry → Arrow table" },
      React.createElement("div", { className: "form" },
        ["id", "url", "maps_to"].map(k => React.createElement("label", { key: k }, k,
          React.createElement("input", { value: form[k], onChange: e => setForm({ ...form, [k]: e.target.value }) })
        )),
        React.createElement("button", { onClick: submit }, "Register JSON Source")
      ),
      result && React.createElement("pre", null, JSON.stringify(result, null, 2))
    ),
    React.createElement(Section, { title: "Configured JSON sources", kicker: "demo sources" },
      React.createElement(DataTable, { rows: state.jsonSources || [] })
    )
  );
}


function AgentApi({ state }) {
  const [manifest, setManifest] = useState(null);
  const [tools, setTools] = useState(null);
  const [updatePlan, setUpdatePlan] = useState(null);
  async function loadAgent() {
    setManifest(await api.get("/api/agent/manifest"));
    setTools(await api.get("/api/agent/tools"));
  }
  async function updateDryRun() {
    setUpdatePlan(await api.post("/api/ops/docker/update", { dry_run: true }));
  }
  useEffect(() => { loadAgent().catch(() => {}); }, []);
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "AI Agent Manifest", kicker: "JWT-driven machine API" },
      React.createElement("p", null, "Everything important is exposed as JSON endpoints behind Bearer JWT auth: health, check-in, BACnet, Modbus, Haystack modeling, algorithms, DataFusion FDD, RCx report planning, and safe update workflows."),
      React.createElement("pre", null, JSON.stringify(manifest || {}, null, 2))
    ),
    React.createElement(Section, { title: "Agent Tools", kicker: "Open-FDD style route map" },
      React.createElement(DataTable, { rows: tools?.tools || [] })
    ),
    React.createElement(Section, { title: "Health Stack", kicker: "openfdd-bridge / commission / haystack-gateway" },
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.get("/api/health/stack"), null, 2)) }, "Show Stack Health")
    ),
    React.createElement(Section, { title: "Safe update workflow", kicker: "backup → pull → recreate → validate" , actions:
      React.createElement("button", { onClick: updateDryRun }, "Run Update Dry-Run")
    },
      updatePlan && React.createElement("pre", null, JSON.stringify(updatePlan, null, 2))
    )
  );
}



function BridgeApi({ state }) {
  const [status, setStatus] = useState(null);
  useEffect(() => { api.get("/api/bridge/status").then(setStatus).catch(() => {}); }, []);
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "openfdd-bridge", kicker: "API + dashboard + historian" },
      React.createElement("p", null, "Rust now serves the frontend, JWT API, and historian query facade."),
      React.createElement("pre", null, JSON.stringify(status || {}, null, 2))
    ),
    React.createElement(Section, { title: "Historian", kicker: "Arrow-shaped rows, DataFusion query path" },
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.get("/api/historian/query"), null, 2)) }, "Query Historian")
    )
  );
}

function BacnetCommission({ state }) {
  const [status, setStatus] = useState(null);
  useEffect(() => { api.get("/api/bacnet/commission/status").then(setStatus).catch(() => {}); }, []);
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "BACnet Commission", kicker: "Who-Is / I-Am / ReadProperty / object-list" },
      React.createElement("pre", null, JSON.stringify(status || {}, null, 2)),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/bacnet/whois", {}), null, 2)) }, "Broadcast Who-Is"),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.get("/api/bacnet/driver/tree"), null, 2)) }, "Show Driver Tree")
    ),
    React.createElement(Section, { title: "Point Registry", kicker: "Haystack assignments preserved as refs" },
      React.createElement(DataTable, { rows: state.points || [] })
    )
  );
}

function BacnetPoll({ state }) {
  const [poll, setPoll] = useState(null);
  useEffect(() => { api.get("/api/bacnet/poll/status").then(setPoll).catch(() => {}); }, []);
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "BACnet Poll", kicker: "poll loop / present-value / override scans" },
      React.createElement("pre", null, JSON.stringify(poll || {}, null, 2))
    ),
    React.createElement(Section, { title: "Priority-array overrides", kicker: "operator + supervisory override watch" },
      React.createElement(DataTable, { rows: state.overrides?.overrides || [] }),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/bacnet/overrides/scan-once", {}), null, 2)) }, "Run Scan Once")
    )
  );
}

function HaystackModel({ state }) {
  const [status, setStatus] = useState(null);
  useEffect(() => { api.get("/api/haystack/status").then(setStatus).catch(() => {}); }, []);
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "Haystack Model", kicker: "Niagara tab converted to Project Haystack" },
      React.createElement("pre", null, JSON.stringify(status || {}, null, 2)),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/haystack/read", { filter: "site or equip or point" }), null, 2)) }, "Haystack Read"),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/haystack/nav", {}), null, 2)) }, "Haystack Nav")
    ),
    React.createElement(Section, { title: "Assignments", kicker: "same assignment/rule-binding style via Haystack refs" },
      React.createElement(DataTable, { rows: state.haystack?.rows || [] })
    )
  );
}

function RuleLab({ state }) {
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "Rule Lab", kicker: "DataFusion SQL only; inputs bound by Haystack refs" },
      React.createElement("pre", { className: "sql" }, state.fdd?.sql || ""),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/rules/save", { id: "custom_sql_rule", engine: "datafusion_sql" }), null, 2)) }, "Save DataFusion SQL Rule"),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/rules/batch", {}), null, 2)) }, "Run Rule Batch")
    ),
    React.createElement(Section, { title: "Rules", kicker: "saved Rust/DataFusion rule list" },
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.get("/api/rules"), null, 2)) }, "List Rules")
    )
  );
}

function Reports({ state }) {
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "RCx Reports", kicker: "agent-drivable report plan/generate" },
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/reports/rcx/plan", {}), null, 2)) }, "Plan Report"),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.post("/api/reports/rcx/generate", {}), null, 2)) }, "Generate Report"),
      React.createElement("button", { onClick: async () => alert(JSON.stringify(await api.get("/api/reports/rcx/list"), null, 2)) }, "List Reports")
    )
  );
}

function Ops({ state }) {
  const [tabs, setTabs] = useState(null);
  const [stack, setStack] = useState(null);
  useEffect(() => {
    api.get("/api/ui/tabs").then(setTabs).catch(() => {});
    api.get("/api/health/stack").then(setStack).catch(() => {});
  }, []);
  return React.createElement("div", { className: "split" },
    React.createElement(Section, { title: "Tab Porting Matrix", kicker: "old Open-FDD tabs accounted for" },
      React.createElement(DataTable, { rows: tabs?.tabs || [] }),
      tabs?.removed_or_deferred && React.createElement("pre", null, JSON.stringify(tabs.removed_or_deferred, null, 2))
    ),
    React.createElement(Section, { title: "Stack", kicker: "Rust split services" },
      React.createElement("pre", null, JSON.stringify(stack || {}, null, 2))
    )
  );
}


function App() {
  const [tab, setTab] = useState("overview");
  const [role, setRole] = useState(localStorage.getItem("openfdd_edge_role") || "integrator");
  const [authInfo, setAuthInfo] = useState(authStore.token ? { role: localStorage.getItem("openfdd_edge_role") || "integrator" } : null);
  const [state, setState] = useState({ loading: true, error: null });

  async function load() {
    try {
      if (!authStore.token) {
        const login = await api.login(role);
        localStorage.setItem("openfdd_edge_role", role);
        setAuthInfo(login);
      }
      const [health, arrowRows, fdd, haystack, modbus, overrides, points, control, jsonSources] = await Promise.all([
        api.get("/api/health"),
        api.get("/api/arrow/demo"),
        api.get("/api/fdd/datafusion/demo"),
        api.get("/api/haystack/model"),
        api.get("/api/modbus/points"),
        api.get("/api/bacnet/overrides/status"),
        api.get("/api/bacnet/points"),
        api.get("/api/control/status"),
        api.get("/api/json-api/sources"),
      ]);
      setState({ loading: false, health, arrowRows, fdd, haystack, modbus, overrides, points, control, jsonSources });
    } catch (e) {
      setState({ loading: false, error: String(e) });
    }
  }
  useEffect(() => { load(); }, []);

  let body;
  if (state.loading) body = React.createElement("div", { className: "splash" }, "Loading edge dashboard...");
  else if (state.error) body = React.createElement("div", { className: "error" }, state.error);
  else {
    body = tab === "overview" ? React.createElement(Overview, { state }) :
      tab === "bridge" ? React.createElement(BridgeApi, { state }) :
      tab === "commission" ? React.createElement(BacnetCommission, { state }) :
      tab === "poll" ? React.createElement(BacnetPoll, { state }) :
      tab === "haystack" ? React.createElement(HaystackModel, { state }) :
      tab === "assignments" ? React.createElement(Assignments, { state }) :
      tab === "algorithms" ? React.createElement(Algorithms, { state }) :
      tab === "fdd" ? React.createElement(Fdd, { state }) :
      tab === "rulelab" ? React.createElement(RuleLab, { state }) :
      tab === "modbus" ? React.createElement(Modbus, { state }) :
      tab === "json" ? React.createElement(JsonApi, { state }) :
      tab === "reports" ? React.createElement(Reports, { state }) :
      tab === "agent" ? React.createElement(AgentApi, { state }) :
      React.createElement(Ops, { state });
  }

  return React.createElement("div", null,
    React.createElement("header", { className: "hero" },
      React.createElement("div", null,
        React.createElement("div", { className: "eyebrow" }, "Open-FDD Rust Edge"),
        React.createElement("h1", null, "Open-FDD Rust Edge Console"),
        React.createElement("p", null, "Open-FDD-style tabs ported to a Rust-served frontend: BACnet commission, BACnet poll, Haystack model, Modbus, JSON API, CDL algorithms, DataFusion FDD, reports, and agent APIs.")
      ),
      React.createElement("div", { className: "hero-status" },
        React.createElement(Pill, { label: authStore.token ? `JWT ${role}` : "auth pending", tone: authStore.token ? "green" : "blue" }),
        React.createElement("select", { value: role, onChange: async e => {
          const next = e.target.value;
          setRole(next);
          localStorage.setItem("openfdd_edge_role", next);
          authStore.clear();
          setAuthInfo(await api.login(next));
          load();
        } },
          ["operator", "integrator", "agent"].map(r => React.createElement("option", { key: r, value: r }, r))
        ),
        React.createElement("button", { onClick: async () => { authStore.clear(); setAuthInfo(await api.login(role)); load(); } }, "Refresh JWT"),
        React.createElement(Pill, { label: "100% Rust backend path", tone: "blue" })
      )
    ),
    React.createElement("nav", { className: "tabs" },
      tabs.map(([id, label]) => React.createElement("button", { key: id, className: tab === id ? "active" : "", onClick: () => setTab(id) }, label))
    ),
    React.createElement("main", { className: "content" }, body)
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(React.createElement(App));
