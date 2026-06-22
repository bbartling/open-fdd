
// Open-FDD Rust Edge UI - REAL DEAL BACNET CSV BUILD
// Niagara-style driver tree + focused tabs.
// Legacy tabs are removed. FDD is DataFusion SQL. Data model is Haystack + assignment graph.

const { useEffect, useMemo, useState } = React;

const api = {
  token: localStorage.getItem("openfdd_token") || "",
  session: (() => {
    try { return JSON.parse(localStorage.getItem("openfdd_session") || "null"); }
    catch { return null; }
  })(),
  headers() {
    const h = { "Content-Type": "application/json" };
    if (this.token) h.Authorization = `Bearer ${this.token}`;
    return h;
  },
  decodeJwt(token) {
    try {
      const part = token.split(".")[1];
      const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
      return JSON.parse(json);
    } catch {
      return null;
    }
  },
  tokenExpired(token = this.token) {
    const claims = this.decodeJwt(token);
    if (!claims || !claims.exp) return true;
    return claims.exp * 1000 <= Date.now();
  },
  restoreSession() {
    if (!this.token || this.tokenExpired()) {
      this.logout(false);
      return false;
    }
    return true;
  },
  async login(username, password) {
    const r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `Login failed (${r.status})`);
    this.token = j.token || j.access_token || "";
    this.session = {
      username: j.subject || username,
      role: j.role || "operator",
      expires_at: j.expires_at || null
    };
    localStorage.setItem("openfdd_token", this.token);
    localStorage.setItem("openfdd_session", JSON.stringify(this.session));
    return j;
  },
  logout(callServer = true) {
    if (callServer && this.token) {
      fetch("/api/auth/logout", { method: "POST", headers: this.headers() }).catch(() => {});
    }
    this.token = "";
    this.session = null;
    localStorage.removeItem("openfdd_token");
    localStorage.removeItem("openfdd_session");
  },
  async get(path) {
    const r = await fetch(path, { headers: this.headers() });
    if (r.status === 401) {
      this.logout(false);
      throw new Error("Session expired — sign in again");
    }
    if (!r.ok) throw new Error(`${path} ${r.status}`);
    return r.json();
  },
  async post(path, body = {}) {
    const r = await fetch(path, { method: "POST", headers: this.headers(), body: JSON.stringify(body) });
    if (r.status === 401) {
      this.logout(false);
      throw new Error("Session expired — sign in again");
    }
    if (!r.ok) throw new Error(`${path} ${r.status}`);
    return r.json();
  },
  async put(path, body = {}) {
    const r = await fetch(path, { method: "PUT", headers: this.headers(), body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`${path} ${r.status}`);
    return r.json();
  }
};

const TABS = [
  ["dashboard", "Dashboard"],
  ["fdd-wires", "FDD Wires"],
  ["rules", "SQL Rules"],
  ["fdd", "SQL FDD"],
  ["plots", "Plots"],
  ["haystack", "Haystack"],
  ["algorithms", "CDL"],
  ["assignments", "Wire Sheet"]
];

function cx(...parts) { return parts.filter(Boolean).join(" "); }

function safeRows(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (Array.isArray(value.rows)) return value.rows;
  if (value.rows && Array.isArray(value.rows.rows)) return value.rows.rows;
  return [];
}

function Metric({ label, value, tone }) {
  return React.createElement("div", { className: cx("metric", tone) },
    React.createElement("div", { className: "metric-value" }, value),
    React.createElement("div", { className: "metric-label" }, label)
  );
}

function DriverNode({ driver, overrides, onAction }) {
  const [open, setOpen] = useState(true);
  const [enabled, setEnabled] = useState(true);
  const devices = driver.devices || [];
  const sources = driver.sources || [];
  const isBacnet = String(driver.id || "").includes("bacnet");
  const p8 = isBacnet ? (overrides.overrides || []).filter(o => o.priority === 8).length : 0;
  const other = isBacnet ? (overrides.overrides || []).filter(o => o.priority !== 8).length : 0;

  return React.createElement("div", { className: cx("tree-node", enabled ? "enabled" : "disabled") },
    React.createElement("div", { className: "tree-row driver-row" },
      React.createElement("button", { className: "twisty", onClick: () => setOpen(!open) }, open ? "▾" : "▸"),
      React.createElement("span", { className: "driver-dot" }),
      React.createElement("strong", null, driver.label || driver.id),
      React.createElement("button", { className: cx("slider", enabled && "on"), onClick: () => setEnabled(!enabled), title: "Enable driver" }, enabled ? "ON" : "OFF")
    ),
    isBacnet && React.createElement("div", { className: "override-strip" },
      React.createElement("button", { className: "chip danger", onClick: () => onAction("p8") }, `P8 ${p8}`),
      React.createElement("button", { className: "chip warn", onClick: () => onAction("nonp8") }, `Other ${other}`),
      React.createElement("button", { className: "chip", onClick: () => window.open("/api/bacnet/overrides/export", "_blank") }, "CSV"),
      React.createElement("button", { className: "chip", onClick: () => onAction("scan") }, "Scan Once")
    ),
    open && devices.map((dev, i) =>
      React.createElement("div", { className: "device-block", key: `${driver.id}-${i}` },
        React.createElement("div", { className: "tree-row device-row" },
          React.createElement("span", null, "▣"),
          React.createElement("span", null, dev.name || dev.address || `Device ${dev.device_instance || dev.unit_id || i + 1}`),
          dev.polling_enabled !== undefined && React.createElement("span", { className: "tiny" }, dev.polling_enabled ? "polling" : "off")
        ),
        (dev.points || []).map((p, n) =>
          React.createElement("button", {
            key: `${p.id || p.name}-${n}`,
            className: cx("point-row", p.writable && "writable"),
            title: "Right-click style actions are represented by action chips for now.",
            onClick: () => onAction("point", p)
          },
            React.createElement("span", null, p.writable ? "◆" : "◇"),
            React.createElement("span", null, p.name || p.id),
            React.createElement("span", { className: "tiny" }, p.haystack_id || "")
          )
        )
      )
    ),
    open && sources.map((src, i) =>
      React.createElement("button", { className: "point-row", key: `${src.id}-${i}`, onClick: () => onAction("source", src) },
        React.createElement("span", null, "◎"),
        React.createElement("span", null, src.id),
        React.createElement("span", { className: "tiny" }, src.maps_to || "")
      )
    ),
    open && driver.note && React.createElement("div", { className: "tree-note" }, driver.note)
  );
}

function DriverTree({ tree, overrides, refresh }) {
  const drivers = tree?.drivers || [];
  async function action(name, payload) {
    try {
      if (name === "scan") {
        await api.post("/api/bacnet/overrides/scan-once", {});
        await refresh();
        return;
      }
      if (name === "p8") {
        window.open("/api/bacnet/overrides/export/p8", "_blank");
        return;
      }
      if (name === "nonp8") {
        window.open("/api/bacnet/overrides/export/non-p8", "_blank");
        return;
      }
      alert(JSON.stringify(payload || { action: name }, null, 2));
    } catch (err) {
      alert(String(err));
    }
  }
  return React.createElement("aside", { className: "sidebar" },
    React.createElement("div", { className: "sidebar-title" }, "Driver Tree"),
    React.createElement("button", { className: "primary full", onClick: refresh }, "Refresh Tree"),
    drivers.map(d => React.createElement(DriverNode, { key: d.id, driver: d, overrides, onAction: action })),
    React.createElement("div", { className: "sidebar-footer" }, "Future roles can hide this tree.")
  );
}

function Dashboard({ health, overrides, tree }) {
  const o = overrides.overrides || [];
  const p8 = o.filter(x => x.priority === 8).length;
  const other = o.filter(x => x.priority !== 8).length;
  const driverCount = (tree?.drivers || []).length;
  return React.createElement("div", null,
    React.createElement("div", { className: "grid metrics" },
      React.createElement(Metric, { label: "Drivers", value: driverCount, tone: "blue" }),
      React.createElement(Metric, { label: "P8 Overrides", value: p8, tone: p8 ? "red" : "green" }),
      React.createElement(Metric, { label: "Other Overrides", value: other, tone: other ? "amber" : "green" }),
      React.createElement(Metric, { label: "Services", value: (health.services || []).length, tone: "blue" })
    ),
    React.createElement("div", { className: "panel" },
      React.createElement("h2", null, "Supervisory Override Watch"),
      React.createElement("div", { className: "split" },
        React.createElement("div", null,
          React.createElement("h3", null, "Priority 8"),
          React.createElement("div", { className: "list" }, o.filter(x => x.priority === 8).map((x, i) => React.createElement("div", { className: "list-row danger", key: i }, `${x.point} = ${x.value} (${x.age_minutes} min)`)))
        ),
        React.createElement("div", null,
          React.createElement("h3", null, "Non-P8"),
          React.createElement("div", { className: "list" }, o.filter(x => x.priority !== 8).map((x, i) => React.createElement("div", { className: "list-row warn", key: i }, `P${x.priority} ${x.point} = ${x.value} (${x.age_minutes} min)`)))
        )
      )
    )
  );
}

function SqlFdd({ fdd }) {
  const faults = fdd.faults || [];
  return React.createElement("div", { className: "panel" },
    React.createElement("h2", null, "DataFusion SQL FDD"),
    React.createElement("pre", { className: "sql" }, fdd.sql || ""),
    React.createElement("div", { className: "table" },
      faults.map((f, i) => React.createElement("div", { className: cx("table-row", f.severity), key: i },
        React.createElement("span", null, f.equip),
        React.createElement("strong", null, f.fault_code),
        React.createElement("span", null, `samples ${f.sample_count}`),
        React.createElement("span", null, `max error ${f.max_abs_error}`)
      ))
    )
  );
}

function Plots({ rows, fdd }) {
  const [yMin, setYMin] = useState("");
  const [yMax, setYMax] = useState("");
  const [xMin, setXMin] = useState("");
  const [xMax, setXMax] = useState("");

  const dataRows = safeRows(rows);
  useEffect(() => {
    const ts = dataRows.map(r => r.ts);
    const sat = dataRows.map(r => r.sat);
    const sp = dataRows.map(r => r.sat_sp);
    const faults = (fdd.faults || []).length ? [{
      x: ts.slice(1, 4),
      y: sat.slice(1, 4),
      mode: "markers",
      name: "Fault Overlay",
      marker: { size: 14, symbol: "x" }
    }] : [];
    const traces = [
      { x: ts, y: sat, mode: "lines+markers", name: "SAT" },
      { x: ts, y: sp, mode: "lines", name: "SAT SP" },
      ...faults
    ];
    const layout = {
      margin: { t: 30, r: 20, b: 40, l: 45 },
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: { color: getComputedStyle(document.body).getPropertyValue("--text") || "#e5eefb" },
      xaxis: { title: "Time" },
      yaxis: { title: "Value" }
    };
    if (window.Plotly && dataRows.length) Plotly.newPlot("trend", traces, layout, { responsive: true });
  }, [JSON.stringify(dataRows), JSON.stringify(fdd)]);

  function applyAxes() {
    const update = {};
    if (yMin !== "" || yMax !== "") update["yaxis.range"] = [yMin === "" ? null : Number(yMin), yMax === "" ? null : Number(yMax)];
    if (xMin !== "" || xMax !== "") update["xaxis.range"] = [xMin || null, xMax || null];
    Plotly.relayout("trend", update);
  }

  return React.createElement("div", { className: "panel" },
    React.createElement("h2", null, "Plots"),
    React.createElement("div", { className: "toolbar" },
      React.createElement("input", { placeholder: "Y min", value: yMin, onChange: e => setYMin(e.target.value) }),
      React.createElement("input", { placeholder: "Y max", value: yMax, onChange: e => setYMax(e.target.value) }),
      React.createElement("input", { placeholder: "X min", value: xMin, onChange: e => setXMin(e.target.value) }),
      React.createElement("input", { placeholder: "X max", value: xMax, onChange: e => setXMax(e.target.value) }),
      React.createElement("button", { className: "primary", onClick: applyAxes }, "Apply Axes")
    ),
    React.createElement("div", { id: "trend", className: "plot" })
  );
}

function Haystack({ model }) {
  const rows = safeRows(model);
  return React.createElement("div", { className: "panel" },
    React.createElement("h2", null, "Haystack Model"),
    React.createElement("div", { className: "table" }, rows.map((r, i) =>
      React.createElement("div", { className: "table-row", key: i },
        React.createElement("strong", null, r.id || ""),
        React.createElement("span", null, r.dis || ""),
        React.createElement("span", null, r.site ? "site" : r.equip ? "equip" : r.point ? "point" : "")
      )
    ))
  );
}

function Algorithms({ bindings }) {
  return React.createElement("div", { className: "panel" },
    React.createElement("h2", null, "CDL Algorithms"),
    React.createElement("div", { className: "wire-card" },
      React.createElement("strong", null, bindings.algorithm_id || "g36_ahu_vav_trim_respond"),
      React.createElement("span", null, "Protocol agnostic"),
      React.createElement("pre", null, JSON.stringify(bindings.bindings || {}, null, 2))
    )
  );
}

function WireSheet({ assignments }) {
  const pts = assignments.points || [];
  const rules = assignments.fault_equation_bindings || [];
  const algs = assignments.algorithm_bindings || [];
  return React.createElement("div", { className: "panel" },
    React.createElement("h2", null, "Assignment Wire Sheet"),
    React.createElement("div", { className: "wire-sheet" },
      React.createElement("div", { className: "wire-col" },
        React.createElement("h3", null, "Drivers → Haystack"),
        pts.map((p, i) => React.createElement("div", { className: "wire-node", key: i }, p.haystack_id, React.createElement("small", null, p.storage_ref)))
      ),
      React.createElement("div", { className: "wire-col" },
        React.createElement("h3", null, "SQL FDD"),
        rules.map((r, i) => React.createElement("div", { className: "wire-node rule", key: i }, r.rule_id, React.createElement("small", null, Object.values(r.inputs || {}).join(" → "))))
      ),
      React.createElement("div", { className: "wire-col" },
        React.createElement("h3", null, "CDL"),
        algs.map((a, i) => React.createElement("div", { className: "wire-node alg", key: i }, a.algorithm_id, React.createElement("small", null, "any driver via Haystack")))
      )
    )
  );
}

function LoginScreen({ onSuccess }) {
  const [username, setUsername] = useState("integrator");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.login(username.trim(), password);
      onSuccess();
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return React.createElement("div", { className: "login-shell" },
    React.createElement("form", { className: "login-card", onSubmit: submit },
      React.createElement("div", { className: "eyebrow" }, "Open-FDD Edge"),
      React.createElement("h1", null, "Sign in"),
      React.createElement("p", { className: "login-copy" }, "Use credentials from workspace/auth.env.local. Secrets are never shown in logs."),
      React.createElement("label", { className: "login-label" }, "Username"),
      React.createElement("input", {
        className: "login-input",
        autoComplete: "username",
        value: username,
        onChange: (e) => setUsername(e.target.value),
        disabled: busy
      }),
      React.createElement("label", { className: "login-label" }, "Password"),
      React.createElement("input", {
        className: "login-input",
        type: "password",
        autoComplete: "current-password",
        value: password,
        onChange: (e) => setPassword(e.target.value),
        disabled: busy
      }),
      error && React.createElement("div", { className: "error login-error" }, error),
      React.createElement("button", { className: "login-submit", type: "submit", disabled: busy }, busy ? "Signing in…" : "Sign in")
    )
  );
}

function App() {
  const [authed, setAuthed] = useState(() => api.restoreSession());
  const [tab, setTab] = useState("dashboard");
  const [theme, setTheme] = useState(localStorage.getItem("openfdd_theme") || "dark");
  const [state, setState] = useState({ health: {}, tree: {}, overrides: {}, fdd: {}, rows: [], model: {}, assignments: {}, bindings: {} });
  const [error, setError] = useState("");
  const [online, setOnline] = useState(false);

  async function load() {
    if (!api.restoreSession()) {
      setAuthed(false);
      return;
    }
    try {
      const [health, tree, overrides, fdd, rows, model, assignments, bindings] = await Promise.all([
        api.get("/api/health"),
        api.get("/api/bacnet/driver/tree"),
        api.get("/api/bacnet/overrides/status"),
        api.get("/api/fdd/datafusion/demo"),
        api.get("/api/arrow/demo"),
        api.get("/api/model/haystack"),
        api.get("/api/model/assignments"),
        api.get("/api/control/cdl/bindings")
      ]);
      setState({ health, tree, overrides, fdd, rows, model, assignments, bindings });
      setOnline(true);
      setError("");
    } catch (err) {
      setOnline(false);
      if (String(err).includes("Session expired")) setAuthed(false);
      setError(String(err));
    }
  }

  useEffect(() => { document.body.dataset.theme = theme; localStorage.setItem("openfdd_theme", theme); }, [theme]);
  useEffect(() => { if (authed) load(); }, [authed]);

  if (!authed) {
    return React.createElement(LoginScreen, { onSuccess: () => setAuthed(true) });
  }

  let body = null;
  if (tab === "dashboard") body = React.createElement(Dashboard, { health: state.health, overrides: state.overrides, tree: state.tree });
  if (tab === "fdd-wires" && window.OpenFddFddWires) body = React.createElement(window.OpenFddFddWires.FddWiresWorkspace, { apiClient: api, driverTree: state.tree, onRefresh: load });
  if (tab === "rules" && window.OpenFddFddWires) body = React.createElement(window.OpenFddFddWires.SqlRuleBuilder, { apiClient: api });
  if (tab === "fdd") body = React.createElement(SqlFdd, { fdd: state.fdd });
  if (tab === "plots") body = React.createElement(Plots, { rows: state.rows, fdd: state.fdd });
  if (tab === "haystack") body = React.createElement(Haystack, { model: state.model });
  if (tab === "algorithms") body = React.createElement(Algorithms, { bindings: state.bindings });
  if (tab === "assignments") body = React.createElement(WireSheet, { assignments: state.assignments });

  return React.createElement("div", { className: "shell" },
    React.createElement("header", { className: "topbar" },
      React.createElement("div", null,
        React.createElement("div", { className: "eyebrow" }, "Rust Edge"),
        React.createElement("h1", null, "Open-FDD")
      ),
      React.createElement("div", { className: "top-actions" },
        React.createElement("div", { className: "auth-status" },
          React.createElement("span", { className: cx("status-dot", online && "online") }),
          React.createElement("span", null, online ? "API online" : "API offline"),
          React.createElement("span", { className: "auth-meta" }, `user ${api.session?.username || "—"} · role ${api.session?.role || "—"} · auth ${state.health?.auth_required ? "required" : "optional"}`)
        ),
        React.createElement("button", { onClick: load }, "Refresh"),
        React.createElement("button", { onClick: () => { api.logout(); setAuthed(false); } }, "Logout"),
        React.createElement("button", { onClick: () => setTheme(theme === "dark" ? "light" : "dark") }, theme === "dark" ? "Light" : "Dark")
      )
    ),
    React.createElement("main", { className: "workspace" },
      React.createElement(DriverTree, { tree: state.tree, overrides: state.overrides, refresh: load }),
      React.createElement("section", { className: "mainpane" },
        error && React.createElement("div", { className: "error" }, error),
        React.createElement("nav", { className: "tabs" }, TABS.map(([id, label]) =>
          React.createElement("button", { key: id, className: cx(tab === id && "active"), onClick: () => setTab(id) }, label)
        )),
        body
      )
    )
  );
}

ReactDOM.render(React.createElement(App), document.getElementById("root"));
