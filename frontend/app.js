
// Open-FDD Rust Edge UI - REAL DEAL BACNET CSV BUILD
// Niagara-style driver tree + focused tabs.
// Legacy tabs are removed. FDD is DataFusion SQL. Data model is Haystack + assignment graph.

const { useEffect, useState, useRef, useCallback } = React;

let onAuthRequired = () => {};

const api = {
  token: localStorage.getItem("openfdd_token") || "",
  loginRequired: false,
  headers() {
    const h = { "Content-Type": "application/json" };
    if (this.token) h.Authorization = `Bearer ${this.token}`;
    return h;
  },
  async login(role = "agent") {
    const r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sub: "ui-agent", role })
    });
    if (!r.ok) throw new Error(`login ${r.status}`);
    const j = await r.json();
    this.token = j.access_token;
    this.loginRequired = false;
    localStorage.setItem("openfdd_token", this.token);
    return j;
  },
  async get(path) {
    const r = await fetch(path, { headers: this.headers() });
    if (r.status === 401) {
      this.token = "";
      localStorage.removeItem("openfdd_token");
      this.loginRequired = true;
      onAuthRequired();
      throw new Error("login required");
    }
    if (!r.ok) throw new Error(`${path} ${r.status}`);
    return r.json();
  },
  async post(path, body = {}) {
    const r = await fetch(path, { method: "POST", headers: this.headers(), body: JSON.stringify(body) });
    if (r.status === 401) {
      this.token = "";
      localStorage.removeItem("openfdd_token");
      this.loginRequired = true;
      onAuthRequired();
      throw new Error("login required");
    }
    if (!r.ok) throw new Error(`${path} ${r.status}`);
    return r.json();
  }
};

async function downloadAuthenticated(path, filename) {
  const r = await fetch(path, { headers: api.headers() });
  if (r.status === 401) {
    api.token = "";
    localStorage.removeItem("openfdd_token");
    api.loginRequired = true;
    onAuthRequired();
    throw new Error("login required");
  }
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || path.split("/").pop() || "download.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(typeof text === "string" ? text : JSON.stringify(text, null, 2));
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = typeof text === "string" ? text : JSON.stringify(text, null, 2);
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

const TABS = [
  ["dashboard", "Dashboard"],
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

function parseHostPort(address) {
  if (!address) return { host: "", port: "" };
  const s = String(address);
  const idx = s.lastIndexOf(":");
  if (idx <= 0) return { host: s, port: "" };
  return { host: s.slice(0, idx), port: s.slice(idx + 1) };
}

function matchesFilter(text, search) {
  if (!search) return true;
  return String(text || "").toLowerCase().includes(String(search).toLowerCase());
}

function ContextMenu({ open, x, y, items, onClose, theme }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    function onClick(e) {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open, onClose]);

  useEffect(() => {
    if (!open || !ref.current) return;
    const el = ref.current;
    el.style.left = `${x}px`;
    el.style.top = `${y}px`;
    const rect = el.getBoundingClientRect();
    let left = x;
    let top = y;
    if (rect.right > window.innerWidth - 8) left = Math.max(8, window.innerWidth - rect.width - 8);
    if (rect.bottom > window.innerHeight - 8) top = Math.max(8, window.innerHeight - rect.height - 8);
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
  }, [open, x, y, items]);

  if (!open) return null;

  return React.createElement("div", {
    ref,
    className: cx("context-menu", theme === "light" ? "context-menu-light" : "context-menu-dark"),
    style: { position: "fixed", left: x, top: y, zIndex: 9999 },
    role: "menu"
  },
    (items || []).map((item, i) => {
      if (item.sep) return React.createElement("div", { key: `sep-${i}`, className: "context-menu-sep" });
      return React.createElement("button", {
        key: item.label || i,
        className: "context-menu-item",
        disabled: !!item.disabled,
        title: item.title || "",
        onClick: () => {
          if (!item.disabled && item.action) item.action();
          onClose();
        }
      }, item.label);
    })
  );
}

function DetailsDrawer({ open, onClose, title, data, protocol, validation, theme }) {
  const [tab, setTab] = useState("raw");

  useEffect(() => {
    if (open) setTab("raw");
  }, [open, title]);

  if (!open) return null;

  const warnings = validation?.warnings || [];
  const errors = validation?.errors || [];
  const rawText = data == null ? "" : JSON.stringify(data, null, 2);
  const protocolText = protocol == null ? "" : JSON.stringify(protocol, null, 2);

  return React.createElement(React.Fragment, null,
    React.createElement("div", { className: "details-backdrop", onClick: onClose }),
    React.createElement("aside", { className: cx("details-drawer", theme === "light" ? "details-drawer-light" : "details-drawer-dark") },
      React.createElement("div", { className: "details-header" },
        React.createElement("h2", null, title || "Details"),
        React.createElement("button", { onClick: onClose, title: "Close" }, "✕")
      ),
      (warnings.length > 0 || errors.length > 0) && React.createElement("div", { className: "details-validation" },
        errors.map((e, i) => React.createElement("div", { key: `e-${i}`, className: "badge badge-error" }, e)),
        warnings.map((w, i) => React.createElement("div", { key: `w-${i}`, className: "badge badge-warn" }, w))
      ),
      React.createElement("nav", { className: "details-tabs" },
        React.createElement("button", { className: cx(tab === "raw" && "active"), onClick: () => setTab("raw") }, "Raw JSON"),
        React.createElement("button", { className: cx(tab === "protocol" && "active"), onClick: () => setTab("protocol") }, "Protocol")
      ),
      React.createElement("button", {
        className: "primary full",
        onClick: () => copyText(tab === "protocol" ? protocolText : rawText)
      }, "Copy"),
      React.createElement("pre", { className: "drawer-pre" }, tab === "protocol" ? protocolText : rawText)
    )
  );
}

function StatusBadges({ health, tree, driverHealth, commission, overrides, workspaceHealth }) {
  const prov = tree?.provenance || {};
  const cfg = tree?.bacnet_config || commission?.config || driverHealth?.config || {};
  const bacnetMode = prov.bacnet_mode || cfg.mode || driverHealth?.status || "unknown";
  const bacnetSource = tree?.source || prov.source || "unknown";
  const apiOk = health?.ok !== false;
  const lastScan = overrides?.scanned_at || overrides?.timestamp || overrides?.last_scan_at || "";
  const simulated = String(bacnetMode).toLowerCase() === "simulated";
  const liveDegraded = String(bacnetMode).toLowerCase() === "live" && (
    !tree?.validation?.ok ||
    (tree?.drivers || []).some(d => d.id === "bacnet-ip" && d.status === "degraded") ||
    workspaceHealth?.ok === false
  );

  return React.createElement("div", { className: "status-badges" },
    React.createElement("span", { className: cx("badge", apiOk ? "badge-live" : "badge-error") }, apiOk ? "API online" : "API offline"),
    React.createElement("span", { className: "badge" }, `BACnet ${bacnetMode}`),
    React.createElement("span", { className: "badge" }, `Source ${bacnetSource}`),
    cfg.iface && React.createElement("span", { className: "badge" }, `iface ${cfg.iface}`),
    cfg.bind && React.createElement("span", { className: "badge" }, `bind ${cfg.bind}`),
    cfg.router_ip && React.createElement("span", { className: "badge" }, `router ${cfg.router_ip}`),
    cfg.mstp_network && React.createElement("span", { className: "badge" }, `mstp ${cfg.mstp_network}`),
    lastScan && React.createElement("span", { className: "badge" }, `last scan ${lastScan}`),
    simulated && React.createElement("span", { className: "badge badge-sim" }, "Simulated data"),
    liveDegraded && React.createElement("span", { className: "badge badge-error" }, "Live degraded")
  );
}

function Kebab({ onOpen }) {
  return React.createElement("button", {
    className: "kebab",
    title: "Actions",
    onClick: (e) => {
      e.stopPropagation();
      const rect = e.currentTarget.getBoundingClientRect();
      onOpen(rect.left, rect.bottom + 4);
    }
  }, "⋮");
}

function Metric({ label, value, tone }) {
  return React.createElement("div", { className: cx("metric", tone) },
    React.createElement("div", { className: "metric-value" }, value),
    React.createElement("div", { className: "metric-label" }, label)
  );
}

function OverrideRow({ row, index, onContext, onKebab }) {
  const label = `P${row.priority} ${row.point || row.point_id} = ${row.value}`;
  return React.createElement("div", {
    className: cx("list-row", row.priority === 8 ? "danger" : "warn", "override-row"),
    onContextMenu: (e) => onContext(e, row),
    key: `ov-${index}`
  },
    React.createElement("span", null, label),
    React.createElement("span", { className: "tiny" }, `${row.age_minutes != null ? row.age_minutes + " min" : ""}`),
    React.createElement(Kebab, { onOpen: (x, y) => onKebab(x, y, row) })
  );
}

function DriverNode({
  driver, filters, onContext, onKebab, onDeviceContext, onDeviceKebab,
  onPointContext, onPointKebab, onSourceContext, onSourceKebab, onSiteContext, onSiteKebab
}) {
  const [open, setOpen] = useState(true);
  const isModbus = String(driver.id || "").includes("modbus");
  const devices = driver.devices || [];
  const sources = driver.sources || [];
  const sites = driver.sites || [];

  function deviceVisible(dev) {
    if (filters.deviceInstance != null && dev.device_instance !== filters.deviceInstance) return false;
    const name = dev.name || dev.address || "";
    if (!matchesFilter(name, filters.search) && !matchesFilter(String(dev.device_instance || ""), filters.search)) return false;
    if (filters.writableOnly) {
      return (dev.points || []).some(p => p.writable);
    }
    return true;
  }

  function pointVisible(p, dev) {
    if (filters.deviceInstance != null && (p.device_instance || dev.device_instance) !== filters.deviceInstance) return false;
    if (filters.writableOnly && !p.writable) return false;
    const hay = [p.name, p.id, p.haystack_id, p.fdd_input].filter(Boolean).join(" ");
    return matchesFilter(hay, filters.search);
  }

  const driverMatch = matchesFilter([driver.label, driver.id].join(" "), filters.search);
  const hasVisibleChild = devices.some(deviceVisible) || sources.some(s => matchesFilter([s.id, s.maps_to, s.url].join(" "), filters.search))
    || sites.some(s => matchesFilter([s.id, s.dis].join(" "), filters.search));
  if (!driverMatch && !hasVisibleChild && filters.search) return null;

  return React.createElement("div", { className: cx("tree-node", driver.enabled !== false ? "enabled" : "disabled") },
    React.createElement("div", {
      className: "tree-row driver-row",
      onContextMenu: (e) => onContext(e, driver)
    },
      React.createElement("button", { className: "twisty", onClick: () => setOpen(!open) }, open ? "▾" : "▸"),
      React.createElement("span", { className: "driver-dot" }),
      React.createElement("strong", null, driver.label || driver.id),
      React.createElement("span", { className: "tiny" }, driver.status || ""),
      React.createElement(Kebab, { onOpen: (x, y) => onKebab(x, y, driver) })
    ),
    open && devices.filter(deviceVisible).map((dev, i) =>
      React.createElement("div", { className: "device-block", key: `${driver.id}-dev-${i}` },
        React.createElement("div", {
          className: "tree-row device-row",
          onContextMenu: (e) => onDeviceContext(e, driver, dev)
        },
          React.createElement("span", null, "▣"),
          React.createElement("span", null, dev.name || dev.address || `Device ${dev.device_instance || dev.unit_id || i + 1}`),
          dev.polling_enabled !== undefined && React.createElement("span", { className: "tiny" }, dev.polling_enabled ? "polling" : "off"),
          React.createElement(Kebab, { onOpen: (x, y) => onDeviceKebab(x, y, driver, dev) })
        ),
        (dev.points || []).filter(p => pointVisible(p, dev)).map((p, n) =>
          React.createElement("div", {
            key: `${p.id || p.name}-${n}`,
            className: cx("point-row", p.writable && "writable"),
            onContextMenu: (e) => onPointContext(e, driver, dev, p)
          },
            React.createElement("span", null, p.writable ? "◆" : "◇"),
            React.createElement("span", null, p.name || p.id),
            React.createElement("span", { className: "tiny" }, p.haystack_id || ""),
            React.createElement(Kebab, { onOpen: (x, y) => onPointKebab(x, y, driver, dev, p) })
          )
        )
      )
    ),
    open && isModbus && devices.length === 0 && React.createElement("div", { className: "tree-note" }, "No Modbus devices"),
    open && sources.filter(s => matchesFilter([s.id, s.maps_to, s.url].join(" "), filters.search)).map((src, i) =>
      React.createElement("div", {
        className: "point-row",
        key: `${src.id}-${i}`,
        onContextMenu: (e) => onSourceContext(e, driver, src)
      },
        React.createElement("span", null, "◎"),
        React.createElement("span", null, src.id),
        React.createElement("span", { className: "tiny" }, src.maps_to || src.url || ""),
        React.createElement(Kebab, { onOpen: (x, y) => onSourceKebab(x, y, driver, src) })
      )
    ),
    open && sites.filter(s => matchesFilter([s.id, s.dis].join(" "), filters.search)).map((site, i) =>
      React.createElement("div", {
        className: "point-row",
        key: `${site.id}-${i}`,
        onContextMenu: (e) => onSiteContext(e, driver, site)
      },
        React.createElement("span", null, "⌂"),
        React.createElement("span", null, site.dis || site.id),
        React.createElement("span", { className: "tiny" }, site.siteRef || site.equipRef || ""),
        React.createElement(Kebab, { onOpen: (x, y) => onSiteKebab(x, y, driver, site) })
      )
    ),
    open && driver.note && React.createElement("div", { className: "tree-note" }, driver.note)
  );
}

function DriverTree({
  tree, overrides, filters, setFilters, refresh, theme,
  openMenu, openDrawer, driverHealth
}) {
  const drivers = tree?.drivers || [];
  const overrideRows = overrides?.overrides || [];

  const runRefresh = useCallback(async () => {
    try { await refresh(); } catch (err) { openDrawer("Error", { error: String(err) }, null, null); }
  }, [refresh, openDrawer]);

  function menuAtEvent(e, items) {
    e.preventDefault();
    e.stopPropagation();
    openMenu(e.clientX, e.clientY, items);
  }

  function driverMenuItems(driver) {
    const isBacnet = String(driver.id || "").includes("bacnet");
    const items = [
      { label: "Refresh tree", action: runRefresh },
      { label: "Copy driver JSON", action: () => copyText(driver) },
      { label: "View driver health", action: () => openDrawer("Driver health", driverHealth, driverHealth?.protocol_proof, tree?.validation) },
      { label: "View raw config summary", action: () => openDrawer(driver.label || driver.id, driver, tree?.provenance, tree?.validation) }
    ];
    if (isBacnet) {
      items.push({ sep: true });
      items.push({
        label: "Scan overrides once",
        action: async () => {
          await api.post("/api/bacnet/overrides/scan-once", {});
          await runRefresh();
        }
      });
      items.push({
        label: "Open override status",
        action: () => openDrawer("Override status", overrides, overrides, null)
      });
      items.push({ sep: true });
      items.push({
        label: "Export all overrides CSV",
        action: () => downloadAuthenticated("/api/bacnet/overrides/export", "bacnet_overrides.csv")
      });
      items.push({
        label: "Export priority 8 CSV",
        action: () => downloadAuthenticated("/api/bacnet/overrides/export/p8", "bacnet_priority8_overrides.csv")
      });
      items.push({
        label: "Export non-P8 CSV",
        action: () => downloadAuthenticated("/api/bacnet/overrides/export/non-p8", "bacnet_non_priority8_overrides.csv")
      });
    }
    return items;
  }

  function bacnetDeviceMenuItems(driver, dev) {
    return [
      { label: "Copy device JSON", action: () => copyText(dev) },
      { label: "Copy BACnet address", action: () => copyText(dev.address || "") },
      { label: "Copy device instance", action: () => copyText(String(dev.device_instance || "")) },
      { label: "Copy router IP", action: () => copyText(dev.router_ip || tree?.bacnet_config?.router_ip || "") },
      { label: "Copy MSTP network", action: () => copyText(String(dev.mstp_network || tree?.bacnet_config?.mstp_network || "")) },
      { sep: true },
      {
        label: "Filter tree to this device",
        action: () => setFilters(f => ({ ...f, deviceInstance: dev.device_instance ?? null }))
      }
    ];
  }

  function bacnetPointMenuItems(driver, dev, point) {
    const items = [
      { label: "Copy point id", action: () => copyText(point.id || "") },
      { label: "Copy object id", action: () => copyText(JSON.stringify(point.object_id || [])) },
      { label: "Copy Haystack id", action: () => copyText(point.haystack_id || "") },
      { label: "Copy FDD input mapping", action: () => copyText(point.fdd_input || "") },
      { label: "View raw point JSON", action: () => openDrawer(point.name || point.id, point, point, null) }
    ];
    if (point.writable) {
      items.push({ sep: true });
      items.push({
        label: "Read priority array now",
        action: async () => {
          const resp = await api.post("/api/bacnet/read-priority-array", { point_id: point.id, ...point });
          openDrawer("Priority array", resp, resp?.protocol_proof, null);
        }
      });
      items.push({
        label: "View in drawer",
        action: () => openDrawer(point.name || point.id, point, null, null)
      });
      items.push({ sep: true });
      items.push({
        label: "Write…",
        disabled: true,
        title: "Write safety API requires integrator approval and audit logging"
      });
      items.push({
        label: "Release…",
        disabled: true,
        title: "Release requires integrator approval and audit logging"
      });
    }
    return items;
  }

  function modbusDeviceMenuItems(driver, dev) {
    const { host, port } = parseHostPort(dev.address);
    return [
      { label: "Copy device JSON", action: () => copyText(dev) },
      { label: "Copy host", action: () => copyText(host) },
      { label: "Copy port", action: () => copyText(port) },
      { label: "Copy unit id", action: () => copyText(String(dev.unit_id || "")) }
    ];
  }

  function modbusPointMenuItems(driver, dev, point) {
    const { host, port } = parseHostPort(point.address || dev.address);
    return [
      { label: "Copy point JSON", action: () => copyText(point) },
      { label: "Copy host", action: () => copyText(host) },
      { label: "Copy port", action: () => copyText(port) },
      { label: "Copy unit id", action: () => copyText(String(point.unit_id || dev.unit_id || "")) },
      { label: "Copy register", action: () => copyText(String(point.register || "")) },
      { label: "Copy function code", action: () => copyText(point.function || "holding_register") },
      { sep: true },
      {
        label: "Read register now",
        action: async () => {
          const resp = await api.post("/api/modbus/read", {
            point_id: point.id,
            register: point.register,
            function: point.function,
            scale: point.scale,
            unit: point.unit
          });
          openDrawer("Modbus read", resp, resp, null);
        }
      }
    ];
  }

  function jsonSourceMenuItems(driver, src) {
    return [
      { label: "Copy source JSON", action: () => copyText(src) },
      { label: "Copy URL", action: () => copyText(src.url || "") },
      { label: "View mapping", action: () => openDrawer(src.id, src, { maps_to: src.maps_to }, null) }
    ];
  }

  function haystackMenuItems(driver, site) {
    return [
      { label: "Copy entity JSON", action: () => copyText(site) },
      { label: "Copy id", action: () => copyText(site.id || "") },
      { label: "Copy dis/name", action: () => copyText(site.dis || "") },
      { label: "Copy siteRef", action: () => copyText(site.siteRef || site.equipRef || site.pointRef || "") },
      { label: "View raw tags", action: () => openDrawer(site.dis || site.id, site, site, null) }
    ];
  }

  function overrideMenuItems(row) {
    return [
      { label: "Copy row JSON", action: () => copyText(row) },
      { label: "Copy point id", action: () => copyText(row.point_id || row.point || "") },
      { label: "Copy priority", action: () => copyText(String(row.priority || "")) },
      {
        label: "Filter to device",
        action: () => setFilters(f => ({ ...f, deviceInstance: row.device_instance ?? null }))
      },
      { sep: true },
      {
        label: "Export all overrides CSV",
        action: () => downloadAuthenticated("/api/bacnet/overrides/export", "bacnet_overrides.csv")
      },
      {
        label: "View raw priority array",
        action: async () => {
          if (!row.point_id) {
            openDrawer("Override", row, null, null);
            return;
          }
          const resp = await api.post("/api/bacnet/read-priority-array", { point_id: row.point_id });
          openDrawer("Priority array", resp, resp?.protocol_proof, null);
        }
      }
    ];
  }

  function onDriverContext(e, driver) { menuAtEvent(e, driverMenuItems(driver)); }
  function onDriverKebab(x, y, driver) { openMenu(x, y, driverMenuItems(driver)); }

  function onDeviceContext(e, driver, dev) {
    e.preventDefault();
    e.stopPropagation();
    const items = String(driver.id || "").includes("bacnet")
      ? bacnetDeviceMenuItems(driver, dev)
      : modbusDeviceMenuItems(driver, dev);
    openMenu(e.clientX, e.clientY, items);
  }

  function onDeviceKebab(x, y, driver, dev) {
    const items = String(driver.id || "").includes("bacnet")
      ? bacnetDeviceMenuItems(driver, dev)
      : modbusDeviceMenuItems(driver, dev);
    openMenu(x, y, items);
  }

  function onPointContext(e, driver, dev, point) {
    e.preventDefault();
    e.stopPropagation();
    const items = String(driver.id || "").includes("modbus")
      ? modbusPointMenuItems(driver, dev, point)
      : bacnetPointMenuItems(driver, dev, point);
    openMenu(e.clientX, e.clientY, items);
  }

  function onPointKebab(x, y, driver, dev, point) {
    const items = String(driver.id || "").includes("modbus")
      ? modbusPointMenuItems(driver, dev, point)
      : bacnetPointMenuItems(driver, dev, point);
    openMenu(x, y, items);
  }

  function onSourceContext(e, driver, src) { menuAtEvent(e, jsonSourceMenuItems(driver, src)); }
  function onSourceKebab(x, y, driver, src) { openMenu(x, y, jsonSourceMenuItems(driver, src)); }

  function onSiteContext(e, driver, site) { menuAtEvent(e, haystackMenuItems(driver, site)); }
  function onSiteKebab(x, y, driver, site) { openMenu(x, y, haystackMenuItems(driver, site)); }

  function onOverrideContext(e, row) { menuAtEvent(e, overrideMenuItems(row)); }
  function onOverrideKebab(x, y, row) { openMenu(x, y, overrideMenuItems(row)); }

  return React.createElement("aside", { className: "sidebar" },
    React.createElement("div", { className: "sidebar-title" }, "Driver Tree"),
    React.createElement("div", { className: "tree-filter" },
      React.createElement("input", {
        placeholder: "Search drivers, devices, points…",
        value: filters.search,
        onChange: e => setFilters(f => ({ ...f, search: e.target.value }))
      }),
      React.createElement("label", null,
        React.createElement("input", {
          type: "checkbox",
          checked: filters.writableOnly,
          onChange: e => setFilters(f => ({ ...f, writableOnly: e.target.checked }))
        }),
        " Writable only"
      ),
      filters.deviceInstance != null && React.createElement("button", {
        className: "chip",
        onClick: () => setFilters(f => ({ ...f, deviceInstance: null }))
      }, `Device ${filters.deviceInstance} ✕`)
    ),
    React.createElement("button", { className: "primary full", onClick: runRefresh }, "Refresh Tree"),
    drivers.map(d => React.createElement(DriverNode, {
      key: d.id,
      driver: d,
      filters,
      onContext: onDriverContext,
      onKebab: onDriverKebab,
      onDeviceContext,
      onDeviceKebab,
      onPointContext,
      onPointKebab,
      onSourceContext,
      onSourceKebab,
      onSiteContext,
      onSiteKebab
    })),
    overrideRows.length > 0 && React.createElement("div", { className: "override-sidebar" },
      React.createElement("h3", null, "Overrides"),
      overrideRows.slice(0, 40).map((row, i) =>
        React.createElement(OverrideRow, {
          key: `sidebar-ov-${i}`,
          row,
          index: i,
          onContext: onOverrideContext,
          onKebab: onOverrideKebab
        })
      )
    ),
    React.createElement("div", { className: "sidebar-footer" }, "Right-click or ⋮ for actions.")
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
          React.createElement("div", { className: "list" }, o.filter(x => x.priority === 8).map((x, i) =>
            React.createElement("div", { className: "list-row danger", key: i }, `${x.point} = ${x.value} (${x.age_minutes} min)`)
          ))
        ),
        React.createElement("div", null,
          React.createElement("h3", null, "Non-P8"),
          React.createElement("div", { className: "list" }, o.filter(x => x.priority !== 8).map((x, i) =>
            React.createElement("div", { className: "list-row warn", key: i }, `P${x.priority} ${x.point} = ${x.value} (${x.age_minutes} min)`)
          ))
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
    if (window.Plotly) Plotly.relayout("trend", update);
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

function HaystackTab({ model }) {
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

async function fetchDriverTree() {
  try {
    return await api.get("/api/drivers/tree");
  } catch (_) {
    return api.get("/api/bacnet/driver/tree");
  }
}

function App() {
  const [tab, setTab] = useState("dashboard");
  const [theme, setTheme] = useState(localStorage.getItem("openfdd_theme") || "dark");
  const [loginRequired, setLoginRequired] = useState(api.loginRequired);
  const [filters, setFilters] = useState({ search: "", writableOnly: false, deviceInstance: null });
  const [menu, setMenu] = useState({ open: false, x: 0, y: 0, items: [] });
  const [drawer, setDrawer] = useState({ open: false, title: "", data: null, protocol: null, validation: null });
  const [state, setState] = useState({
    health: {}, tree: {}, overrides: {}, driverHealth: {}, workspaceHealth: {}, commission: {},
    fdd: {}, rows: [], model: {}, assignments: {}, bindings: {}
  });
  const [error, setError] = useState("");

  const openMenu = useCallback((x, y, items) => {
    setMenu({ open: true, x, y, items: items || [] });
  }, []);

  const closeMenu = useCallback(() => {
    setMenu(m => ({ ...m, open: false }));
  }, []);

  const openDrawer = useCallback((title, data, protocol, validation) => {
    setDrawer({ open: true, title, data, protocol, validation });
  }, []);

  const closeDrawer = useCallback(() => {
    setDrawer(d => ({ ...d, open: false }));
  }, []);

  useEffect(() => {
    onAuthRequired = () => setLoginRequired(true);
    return () => { onAuthRequired = () => {}; };
  }, []);

  useEffect(() => {
    document.body.dataset.theme = theme;
    localStorage.setItem("openfdd_theme", theme);
  }, [theme]);

  async function load() {
    try {
      if (!api.token) await api.login("agent");
      setLoginRequired(false);
      const [health, tree, overrides, driverHealth, workspaceHealth, commission, fdd, rows, model, assignments, bindings] = await Promise.all([
        api.get("/api/health"),
        fetchDriverTree(),
        api.get("/api/bacnet/overrides/status"),
        api.get("/api/bacnet/driver/health"),
        api.get("/api/health/workspace"),
        api.get("/api/bacnet/commission/status"),
        api.get("/api/fdd/datafusion/demo"),
        api.get("/api/arrow/demo"),
        api.get("/api/model/haystack"),
        api.get("/api/model/assignments"),
        api.get("/api/control/cdl/bindings")
      ]);
      setState({ health, tree, overrides, driverHealth, workspaceHealth, commission, fdd, rows, model, assignments, bindings });
      setError("");
    } catch (err) {
      if (api.loginRequired || String(err).includes("login required")) {
        setLoginRequired(true);
      } else {
        setError(String(err));
      }
    }
  }

  async function handleLogin() {
    try {
      await api.login("agent");
      setLoginRequired(false);
      await load();
    } catch (err) {
      setError(String(err));
    }
  }

  useEffect(() => { load(); }, []);

  let body = null;
  if (tab === "dashboard") body = React.createElement(Dashboard, { health: state.health, overrides: state.overrides, tree: state.tree });
  if (tab === "fdd") body = React.createElement(SqlFdd, { fdd: state.fdd });
  if (tab === "plots") body = React.createElement(Plots, { rows: state.rows, fdd: state.fdd });
  if (tab === "haystack") body = React.createElement(HaystackTab, { model: state.model });
  if (tab === "algorithms") body = React.createElement(Algorithms, { bindings: state.bindings });
  if (tab === "assignments") body = React.createElement(WireSheet, { assignments: state.assignments });

  return React.createElement("div", { className: "shell" },
    React.createElement("header", { className: "topbar" },
      React.createElement("div", null,
        React.createElement("div", { className: "eyebrow" }, "Rust Edge"),
        React.createElement("h1", null, "Open-FDD")
      ),
      React.createElement("div", { className: "top-actions" },
        React.createElement("button", { onClick: load }, "Refresh"),
        React.createElement("button", { onClick: () => setTheme(theme === "dark" ? "light" : "dark") }, theme === "dark" ? "Light" : "Dark")
      )
    ),
    loginRequired && React.createElement("div", { className: "error login-banner" },
      React.createElement("span", null, "Session expired — login required."),
      React.createElement("button", { className: "primary", onClick: handleLogin }, "Login")
    ),
    React.createElement("main", { className: "workspace" },
      React.createElement(DriverTree, {
        tree: state.tree,
        overrides: state.overrides,
        filters,
        setFilters,
        refresh: load,
        theme,
        openMenu,
        openDrawer,
        driverHealth: state.driverHealth
      }),
      React.createElement("section", { className: "mainpane" },
        React.createElement(StatusBadges, {
          health: state.health,
          tree: state.tree,
          driverHealth: state.driverHealth,
          commission: state.commission,
          overrides: state.overrides,
          workspaceHealth: state.workspaceHealth
        }),
        error && React.createElement("div", { className: "error" }, error),
        React.createElement("nav", { className: "tabs" }, TABS.map(([id, label]) =>
          React.createElement("button", { key: id, className: cx(tab === id && "active"), onClick: () => setTab(id) }, label)
        )),
        body
      )
    ),
    React.createElement(ContextMenu, {
      open: menu.open,
      x: menu.x,
      y: menu.y,
      items: menu.items,
      onClose: closeMenu,
      theme
    }),
    React.createElement(DetailsDrawer, {
      open: drawer.open,
      onClose: closeDrawer,
      title: drawer.title,
      data: drawer.data,
      protocol: drawer.protocol,
      validation: drawer.validation,
      theme
    })
  );
}

ReactDOM.render(React.createElement(App), document.getElementById("root"));
