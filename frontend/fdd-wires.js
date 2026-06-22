// Open-FDD FDD Wires — Rule Assignment Workspace + SQL Rule Builder
// Open-FDD-native naming only (no third-party product branding in UI).

(function (global) {
  const { useEffect, useMemo, useRef, useState } = React;

  const NODE_PALETTE = [
    { group: "Model", items: ["model_site", "model_equipment", "model_point"] },
    { group: "Drivers", items: ["driver_point"] },
    { group: "FDD", items: ["fdd_input", "unit_conversion", "quality_check", "sql_rule", "confirmation_timer", "fault_output"] },
    { group: "Reporting", items: ["recommendation", "report_section"] },
    { group: "Utility", items: ["comment", "group"] }
  ];

  const BADGE_CLASS = {
    simulated: "badge-sim",
    fixture: "badge-fix",
    real: "badge-real",
    ai_suggested: "badge-ai",
    approved: "badge-ok",
    active: "badge-ok",
    failing: "badge-bad"
  };

  function badge(label, kind) {
    return React.createElement("span", { className: cx("badge", BADGE_CLASS[kind] || "") }, label);
  }

  function cx(...parts) { return parts.filter(Boolean).join(" "); }

  function ContextMenu({ x, y, items, onClose }) {
    useEffect(() => {
      function close() { onClose(); }
      window.addEventListener("click", close);
      return () => window.removeEventListener("click", close);
    }, [onClose]);
    return React.createElement("div", { className: "ctx-menu", style: { top: y, left: x }, onClick: e => e.stopPropagation() },
      items.map((item, i) => React.createElement("button", {
        key: i,
        className: "ctx-item",
        onClick: () => { item.action(); onClose(); }
      }, item.label))
    );
  }

  function SqlRuleBuilder({ apiClient }) {
    const [mode, setMode] = useState("builder");
    const [builder, setBuilder] = useState({ name: "OA Temperature Out Of Range", input: "oa_t", operator: ">", value: 110, equipment_id: "AHU-1", confirmation_seconds: 300, severity: "medium", fault_code: "OA_TEMP_OUT_OF_RANGE" });
    const [sql, setSql] = useState("");
    const [rawCustom, setRawCustom] = useState(false);
    const [result, setResult] = useState(null);
    const [validation, setValidation] = useState(null);
    const [schema, setSchema] = useState({ tables: [], fdd_inputs: [] });

    useEffect(() => {
      Promise.all([
        apiClient.get("/api/fdd-schema/tables"),
        apiClient.get("/api/fdd-schema/fdd-inputs")
      ]).then(([t, f]) => setSchema({ tables: t.tables || [], fdd_inputs: f.fdd_inputs || [] })).catch(() => {});
    }, []);

    async function previewBuilder() {
      const out = await apiClient.post("/api/fdd-rules/builder-sql", builder);
      setSql(out.sql || "");
      setValidation(out.validation || null);
      setRawCustom(false);
    }

    async function runSql() {
      const out = await apiClient.post("/api/fdd-rules/oa_temp_out_of_range/test-sql", {
        sql,
        confirmation_seconds: builder.confirmation_seconds,
        params: { equipment_id: builder.equipment_id }
      });
      setResult(out);
    }

    async function validateSql() {
      const out = await apiClient.post("/api/fdd-rules/oa_temp_out_of_range/validate-sql", { sql });
      setValidation(out);
    }

    function onRawChange(v) {
      setSql(v);
      setRawCustom(true);
    }

    useEffect(() => { if (mode === "builder") previewBuilder(); }, [mode, builder.input, builder.operator, builder.value, builder.equipment_id]);

    useEffect(() => {
      function onKey(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runSql();
      }
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [sql, builder.confirmation_seconds]);

    return React.createElement("div", { className: "fdd-rules-panel panel" },
      React.createElement("div", { className: "toolbar" },
        React.createElement("h2", null, "SQL Rule Builder"),
        React.createElement("button", { className: cx(mode === "builder" && "active"), onClick: () => setMode("builder") }, "Builder mode"),
        React.createElement("button", { className: cx(mode === "raw" && "active"), onClick: () => setMode("raw") }, "Raw DataFusion SQL"),
        React.createElement("button", { onClick: validateSql }, "Validate safe SQL"),
        React.createElement("button", { className: "primary", onClick: runSql }, "Run (Ctrl/Cmd+Enter)")
      ),
      mode === "builder" && React.createElement("div", { className: "builder-grid" },
        React.createElement("label", null, "Rule name", React.createElement("input", { value: builder.name, onChange: e => setBuilder({ ...builder, name: e.target.value }) })),
        React.createElement("label", null, "FDD input", React.createElement("select", { value: builder.input, onChange: e => setBuilder({ ...builder, input: e.target.value }) },
          (schema.fdd_inputs || []).map(i => React.createElement("option", { key: i.id, value: i.id }, i.label)))),
        React.createElement("label", null, "Operator", React.createElement("select", { value: builder.operator, onChange: e => setBuilder({ ...builder, operator: e.target.value }) },
          [">", "<", ">=", "<="].map(op => React.createElement("option", { key: op, value: op }, op)))),
        React.createElement("label", null, "Threshold", React.createElement("input", { type: "number", value: builder.value, onChange: e => setBuilder({ ...builder, value: Number(e.target.value) }) })),
        React.createElement("label", null, "Confirmation (sec)", React.createElement("input", { type: "number", value: builder.confirmation_seconds, onChange: e => setBuilder({ ...builder, confirmation_seconds: Number(e.target.value) }) })),
        React.createElement("label", null, "Fault code", React.createElement("input", { value: builder.fault_code, onChange: e => setBuilder({ ...builder, fault_code: e.target.value }) }))
      ),
      rawCustom && React.createElement("div", { className: "warn-banner" }, "Raw SQL is custom — Builder mode may not round-trip these edits."),
      React.createElement("label", null, "Generated / Raw SQL preview"),
      React.createElement("textarea", {
        className: "sql-editor",
        value: sql,
        onChange: e => onRawChange(e.target.value),
        spellCheck: false
      }),
      validation && React.createElement("pre", { className: "validation-box" }, JSON.stringify(validation, null, 2)),
      result && React.createElement("div", { className: "results-box" },
        React.createElement("strong", null, "Query results"),
        React.createElement("div", null, `Rows: ${result.row_count || 0} | Raw faults: ${result.confirmation?.raw_fault_count ?? "?"}`),
        React.createElement("pre", null, JSON.stringify((result.rows || []).slice(0, 8), null, 2))
      )
    );
  }

  function FddWiresWorkspace({ apiClient, driverTree, onRefresh }) {
    const [graphs, setGraphs] = useState([]);
    const [graph, setGraph] = useState(null);
    const [selectedId, setSelectedId] = useState(null);
    const [proposals, setProposals] = useState(null);
    const [validation, setValidation] = useState(null);
    const [testResult, setTestResult] = useState(null);
    const [search, setSearch] = useState("");
    const [ctx, setCtx] = useState(null);
    const [message, setMessage] = useState("");
    const canvasRef = useRef(null);

    const graphId = "graph:bench-5007-fdd";
    const siteId = "site:demo";

    async function loadGraphs() {
      const list = await apiClient.get("/api/fdd-wires/graphs?site_id=" + encodeURIComponent(siteId));
      setGraphs(list.graphs || []);
      const detail = await apiClient.get(`/api/fdd-wires/graphs/${encodeURIComponent(graphId)}?site_id=${encodeURIComponent(siteId)}`);
      setGraph(detail.graph || null);
    }

    useEffect(() => { loadGraphs().catch(e => setMessage(String(e))); }, []);

    const nodes = (graph && graph.nodes) || [];
    const edges = (graph && graph.edges) || [];
    const selected = nodes.find(n => n.id === selectedId) || null;

    const filteredNodes = useMemo(() => {
      if (!search) return nodes;
      const q = search.toLowerCase();
      return nodes.filter(n => JSON.stringify(n).toLowerCase().includes(q));
    }, [nodes, search]);

    async function propose() {
      const out = await apiClient.post("/api/fdd-wires/propose-assignments", {
        site_id: siteId,
        equipment_type: "ahu",
        drivers: (driverTree && driverTree.drivers) || []
      });
      setProposals(out);
      setMessage("AI assignment proposals loaded — review required before activation.");
    }

    async function validateGraph() {
      const out = await apiClient.post(`/api/fdd-wires/graphs/${encodeURIComponent(graphId)}/validate?site_id=${encodeURIComponent(siteId)}`, {});
      setValidation(out.validation || out);
    }

    async function testGraph() {
      const out = await apiClient.post(`/api/fdd-wires/graphs/${encodeURIComponent(graphId)}/test?site_id=${encodeURIComponent(siteId)}`, {});
      setTestResult(out);
    }

    async function approveGraph() {
      const out = await apiClient.post(`/api/fdd-wires/graphs/${encodeURIComponent(graphId)}/approve?site_id=${encodeURIComponent(siteId)}`, {});
      setMessage(out.ok ? "Graph approved" : (out.error || "approve failed"));
      await loadGraphs();
    }

    async function activateGraph() {
      const out = await apiClient.post(`/api/fdd-wires/graphs/${encodeURIComponent(graphId)}/activate?site_id=${encodeURIComponent(siteId)}`, {});
      setMessage(out.ok ? "Graph activated" : (out.error || "activation failed"));
      await loadGraphs();
    }

    function exportJson() {
      const blob = new Blob([JSON.stringify(graph, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${graphId}.json`;
      a.click();
    }

    function importJson(file) {
      const reader = new FileReader();
      reader.onload = async () => {
        try {
          const payload = JSON.parse(reader.result);
          await apiClient.put(`/api/fdd-wires/graphs/${encodeURIComponent(graphId)}?site_id=${encodeURIComponent(siteId)}`, payload);
          await loadGraphs();
          setMessage("Graph imported");
        } catch (e) { setMessage(String(e)); }
      };
      reader.readAsText(file);
    }

    function onCanvasContextMenu(e) {
      e.preventDefault();
      setCtx({
        x: e.clientX, y: e.clientY,
        items: [
          { label: "Validate graph", action: validateGraph },
          { label: "Test graph", action: testGraph },
          { label: "Export graph JSON", action: exportJson },
          { label: "Propose assignments (AI draft)", action: propose }
        ]
      });
    }

    function onNodeContextMenu(e, node) {
      e.preventDefault();
      e.stopPropagation();
      setSelectedId(node.id);
      setCtx({
        x: e.clientX, y: e.clientY,
        items: [
          { label: "Open settings", action: () => setSelectedId(node.id) },
          { label: "Copy ID", action: () => navigator.clipboard.writeText(node.id) },
          { label: "Copy JSON", action: () => navigator.clipboard.writeText(JSON.stringify(node, null, 2)) },
          { label: "Validate", action: validateGraph },
          { label: "Run test from here", action: testGraph }
        ]
      });
    }

    return React.createElement("div", { className: "fdd-wires-shell" },
      ctx && React.createElement(ContextMenu, { ...ctx, onClose: () => setCtx(null) }),
      React.createElement("aside", { className: "fdd-left panel" },
        React.createElement("h3", null, "Rule Assignment Workspace"),
        React.createElement("input", { placeholder: "Search nodes…", value: search, onChange: e => setSearch(e.target.value) }),
        React.createElement("button", { className: "primary full", onClick: propose }, "Propose assignments"),
        React.createElement("div", { className: "palette" },
          NODE_PALETTE.map(g => React.createElement("div", { key: g.group, className: "palette-group" },
            React.createElement("strong", null, g.group),
            g.items.map(t => React.createElement("button", { key: t, className: "chip", draggable: true }, t.replace(/_/g, " ")))
          ))
        ),
        React.createElement("div", { className: "graph-list" },
          graphs.map(g => React.createElement("div", { key: g.graph_id, className: "list-row" },
            g.graph_id, " ", badge(g.review_status || "draft", g.review_status === "active" ? "active" : "ai_suggested")
          ))
        )
      ),
      React.createElement("section", { className: "fdd-center" },
        React.createElement("div", { className: "toolbar" },
          React.createElement("strong", null, "FDD Wires — Rule Graph"),
          badge(graph && graph.review_status, graph && graph.review_status === "active" ? "active" : "ai_suggested"),
          graph && graph.source === "ai_generated" && badge("AI suggested", "ai_suggested"),
          React.createElement("button", { onClick: validateGraph }, "Validate"),
          React.createElement("button", { onClick: testGraph }, "Test"),
          React.createElement("button", { onClick: approveGraph }, "Approve"),
          React.createElement("button", { className: "primary", onClick: activateGraph }, "Activate"),
          React.createElement("label", { className: "file-btn" }, "Import JSON",
            React.createElement("input", { type: "file", accept: "application/json", hidden: true, onChange: e => e.target.files[0] && importJson(e.target.files[0]) }))
        ),
        message && React.createElement("div", { className: "info-banner" }, message),
        React.createElement("div", { className: "wire-canvas", ref: canvasRef, onContextMenu: onCanvasContextMenu },
          filteredNodes.map((node, idx) => React.createElement("div", {
            key: node.id,
            className: cx("wire-node-card", selectedId === node.id && "selected", node.type),
            style: { left: (node.position && node.position.x) || (40 + idx * 140), top: (node.position && node.position.y) || 80 },
            onClick: () => setSelectedId(node.id),
            onContextMenu: e => onNodeContextMenu(e, node)
          },
            React.createElement("div", { className: "wire-node-title" }, node.label || node.id),
            React.createElement("div", { className: "wire-node-meta" }, node.type),
            node.config && node.config.source_label && badge(node.config.source_label, node.config.source_label === "simulated" ? "simulated" : "real"),
            node.source === "ai_generated" && badge("AI", "ai_suggested")
          )),
          edges.map(e => React.createElement("div", { key: e.id, className: "wire-edge-label" }, `${e.from} → ${e.to} (${e.type})`))
        )
      ),
      React.createElement("aside", { className: "fdd-right panel" },
        React.createElement("h3", null, "Details / Settings"),
        selected ? React.createElement("div", null,
          React.createElement("div", { className: "tabs-mini" },
            ["config", "validation", "json"].map(t => React.createElement("button", { key: t }, t))
          ),
          React.createElement("pre", null, JSON.stringify(selected, null, 2))
        ) : React.createElement("p", { className: "muted" }, "Select a node to inspect configuration."),
        proposals && React.createElement("div", { className: "proposal-box" },
          React.createElement("h4", null, "Assignment Review"),
          React.createElement("pre", null, JSON.stringify(proposals.proposals || [], null, 2))
        ),
        validation && React.createElement("pre", { className: "validation-box" }, JSON.stringify(validation, null, 2)),
        testResult && React.createElement("pre", { className: "validation-box" }, JSON.stringify(testResult.execution || testResult, null, 2))
      ),
      React.createElement("footer", { className: "fdd-bottom panel" },
        React.createElement("strong", null, "SQL preview / test output"),
        React.createElement("span", { className: "muted" }, "DataFusion SQL executes in Rust against Apache Arrow telemetry.")
      )
    );
  }

  global.OpenFddFddWires = { FddWiresWorkspace, SqlRuleBuilder };
})(window);
