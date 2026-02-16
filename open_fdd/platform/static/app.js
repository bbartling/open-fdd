/**
 * Open-FDD config UI — Data model tree (Site → Equipment → Points), CRUD, Run FDD, BACnet test.
 * Uses existing CRUD API; JS only, no framework. Separate from index.html and styles.css.
 */

(function () {
  "use strict";

  const API_BASE = window.location.origin;

  function setVersionInUI(version) {
    if (version) {
      document.title = "Open-FDD " + version + " — Configuration";
      const el = document.getElementById("header-version");
      if (el) el.textContent = "v" + version;
    }
  }

  function api(path, options = {}) {
    const url = path.startsWith("http") ? path : API_BASE + path;
    return fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });
  }

  function showToast(message, type = "success") {
    const el = document.getElementById("toast");
    el.textContent = message;
    el.className = "toast " + type;
    el.classList.remove("hidden");
    setTimeout(() => el.classList.add("hidden"), 3500);
  }

  function hideContextMenu() {
    document.getElementById("context-menu").classList.add("hidden");
  }

  function showContextMenu(x, y, node) {
    const menu = document.getElementById("context-menu");
    menu.classList.remove("hidden");
    menu.style.left = x + "px";
    menu.style.top = y + "px";
    menu.dataset.kind = node.kind;
    menu.dataset.id = node.id;
    menu.dataset.label = node.label || node.name || node.external_id || node.id;
  }

  function buildTree() {
    const treeEl = document.getElementById("tree");
    if (!treeEl) {
      console.warn("[tree] #tree element not found");
      return;
    }
    console.log("[tree] buildTree start");
    treeEl.innerHTML = "<li class=\"tree-loading\">Loading…</li>";

    api("/sites")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.statusText))))
      .then((sites) => {
        console.log("[tree] sites loaded", sites.length, sites);
        if (sites.length === 0) {
          treeEl.innerHTML = "<li class=\"tree-empty\">No sites yet. Click <strong>+ Site</strong> to add one (or use the API). The data model here is the source for <code>brick_model.ttl</code>.</li>";
          return;
        }
        treeEl.innerHTML = "";
        return Promise.all(
          sites.map((site) =>
            api("/equipment?site_id=" + encodeURIComponent(site.id))
              .then((r) => r.json())
              .then((equipmentList) => ({ site, equipmentList }))
          )
        );
      })
      .then((siteData) => {
        if (!siteData) return;
        console.log("[tree] siteData", siteData);
        siteData.forEach(({ site, equipmentList }) => {
          const siteLi = document.createElement("li");
          const siteNode = document.createElement("div");
          siteNode.className = "tree-node";
          siteNode.dataset.kind = "site";
          siteNode.dataset.id = site.id;
          const hasChildren = equipmentList.length > 0;
          console.log("[tree] add site node", site.name, "equipmentCount", equipmentList.length);

          const eqUl = document.createElement("ul");
          eqUl.className = "tree-children" + (hasChildren ? "" : " tree-collapsed");
          if (hasChildren) siteNode.classList.add("tree-expanded");

          siteNode.innerHTML =
            '<span class="tree-twisty" aria-label="Expand/collapse"></span>' +
            '<span class="icon"></span><span class="label">' +
            escapeHtml(site.name) +
            "</span>";
          siteNode.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            showContextMenu(e.clientX, e.clientY, { kind: "site", id: site.id, label: site.name });
          });
          siteNode.addEventListener("click", (e) => {
            if (e.target.closest(".tree-twisty.tree-no-children")) return;
            console.log("[tree] site expand click", site.name);
            siteNode.classList.toggle("tree-expanded");
            eqUl.classList.toggle("tree-collapsed");
          });
          siteLi.appendChild(siteNode);

          if (!hasChildren) {
            const emptyLi = document.createElement("li");
            emptyLi.className = "tree-empty-inline";
            emptyLi.textContent = "No equipment. Add via API or create equipment under this site.";
            eqUl.appendChild(emptyLi);
          }
          equipmentList.forEach((eq) => {
            const eqLi = document.createElement("li");
            const eqNode = document.createElement("div");
            eqNode.className = "tree-node";
            eqNode.dataset.kind = "equipment";
            eqNode.dataset.id = eq.id;
            eqNode.innerHTML =
              '<span class="tree-twisty" aria-label="Expand/collapse"></span>' +
              '<span class="icon"></span><span class="label">' +
              escapeHtml(eq.name) +
              "</span>";
            eqNode.addEventListener("contextmenu", (e) => {
              e.preventDefault();
              showContextMenu(e.clientX, e.clientY, {
                kind: "equipment",
                id: eq.id,
                label: eq.name,
              });
            });
            const pointsUl = document.createElement("ul");
            pointsUl.className = "tree-children tree-collapsed";
            eqNode.addEventListener("click", (e) => {
              if (e.target.closest(".tree-twisty.tree-no-children")) return;
              console.log("[tree] equipment expand click", eq.name);
              eqNode.classList.toggle("tree-expanded");
              pointsUl.classList.toggle("tree-collapsed");
            });
            eqLi.appendChild(eqNode);
            api("/points?equipment_id=" + encodeURIComponent(eq.id))
              .then((r) => r.json())
              .then((pointsList) => {
                if (pointsList.length === 0) {
                  eqNode.querySelector(".tree-twisty").classList.add("tree-no-children");
                }
                pointsList.forEach((pt) => {
                  const ptLi = document.createElement("li");
                  const ptNode = document.createElement("div");
                  ptNode.className = "tree-node";
                  ptNode.dataset.kind = "point";
                  ptNode.dataset.id = pt.id;
                  ptNode.innerHTML =
                    '<span class="tree-twisty tree-no-children"></span>' +
                    '<span class="icon"></span><span class="label">' +
                    escapeHtml(pt.external_id) +
                    "</span>" +
                    (pt.brick_type
                      ? '<span class="meta">' + escapeHtml(pt.brick_type) + "</span>"
                      : "");
                  ptNode.addEventListener("contextmenu", (e) => {
                    e.preventDefault();
                    showContextMenu(e.clientX, e.clientY, {
                      kind: "point",
                      id: pt.id,
                      label: pt.external_id,
                    });
                  });
                  ptLi.appendChild(ptNode);
                  pointsUl.appendChild(ptLi);
                });
              })
              .catch(() => {
                eqNode.querySelector(".tree-twisty").classList.add("tree-no-children");
              });
            eqLi.appendChild(pointsUl);
            eqUl.appendChild(eqLi);
          });
          siteLi.appendChild(eqUl);
          treeEl.appendChild(siteLi);
        });
      })
      .catch((err) => {
        console.error("[tree] buildTree failed", err);
        treeEl.innerHTML = "<li class=\"tree-error\">Failed to load. Check API and CORS.</li>";
      });
  }

  function deleteNode(kind, id) {
    const path =
      kind === "site"
        ? "/sites/" + id
        : kind === "equipment"
          ? "/equipment/" + id
          : "/points/" + id;
    api(path, { method: "DELETE" })
      .then((r) => {
        if (r.ok) {
          showToast("Deleted.", "success");
          buildTree();
        } else {
          return r.json().then((body) => Promise.reject(new Error(body.detail || r.statusText)));
        }
      })
      .catch((err) => showToast(err.message || "Delete failed", "error"));
  }

  function escapeHtml(s) {
    if (s == null) return "";
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  function addSite() {
    const name = window.prompt("Site name:");
    if (!name || !name.trim()) return;
    api("/sites", {
      method: "POST",
      body: JSON.stringify({ name: name.trim() }),
    })
      .then((r) => {
        if (r.ok) {
          showToast("Site created.");
          buildTree();
        } else {
          return r.json().then((body) => Promise.reject(new Error(body.detail || r.statusText)));
        }
      })
      .catch((err) => showToast(err.message || "Create failed", "error"));
  }

  function runFdd() {
    api("/run-fdd", { method: "POST" })
      .then((r) => {
        if (r.ok) return r.json();
        return Promise.reject(new Error(r.statusText));
      })
      .then(() => {
        showToast("FDD run triggered.");
        refreshLastFddRun();
      })
      .catch((err) => showToast(err.message || "Trigger failed", "error"));
  }

  function testBacnet() {
    const urlInput = document.getElementById("bacnet-url");
    const resultEl = document.getElementById("bacnet-result");
    const statusEl = document.getElementById("bacnet-status");
    const base = (urlInput.value || "").trim().replace(/\/$/, "");
    if (!base) {
      resultEl.textContent = "Enter a URL.";
      resultEl.className = "alert alert-warning mt-3";
      statusEl.className = "bacnet-badge bacnet-offline";
      return;
    }
    resultEl.textContent = "Testing… (backend is calling " + base + ")";
    resultEl.className = "alert alert-secondary mt-3";

    api("/bacnet/server_hello", {
      method: "POST",
      body: JSON.stringify({ url: base }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.ok) {
          statusEl.className = "bacnet-badge bacnet-online";
          resultEl.textContent = "Connected. BACnet server is online.";
          resultEl.className = "alert alert-success mt-3";
        } else {
          statusEl.className = "bacnet-badge bacnet-offline";
          resultEl.textContent = "Connection failed: " + (data.error || "HTTP " + (data.status_code || ""));
          resultEl.className = "alert alert-danger mt-3";
        }
      })
      .catch((err) => {
        statusEl.className = "bacnet-badge bacnet-offline";
        resultEl.textContent = "Offline or unreachable: " + (err.message || "network error");
        resultEl.className = "alert alert-danger mt-3";
      });
  }

  function getBacnetUrl() {
    const urlInput = document.getElementById("bacnet-url");
    return (urlInput && urlInput.value ? urlInput.value : "").trim().replace(/\/$/, "") || "http://localhost:8080";
  }

  function addRawCollapse(container, body) {
    const rawId = "bacnet-raw-" + Date.now();
    const summary = document.createElement("details");
    summary.className = "bacnet-raw-details mt-2";
    summary.innerHTML = "<summary class=\"small text-muted cursor-pointer\">Raw response (expand for logs)</summary>";
    const pre = document.createElement("pre");
    pre.className = "bacnet-raw-pre";
    pre.textContent = typeof body === "string" ? body : JSON.stringify(body, null, 2);
    summary.appendChild(pre);
    container.appendChild(summary);
  }

  function renderBacnetWhoisResult(el, body) {
    const res = body && body.result && body.result.data;
    const devices = res && res.devices;
    el.className = "bacnet-result-card mt-3";
    el.innerHTML = "";
    const heading = document.createElement("div");
    heading.className = "bacnet-result-heading";
    heading.innerHTML = "<span class=\"bacnet-status-dot success\"></span><strong>Who-Is scan complete</strong>";
    if (devices && devices.length) {
      const badge = document.createElement("span");
      badge.className = "badge bg-secondary";
      badge.textContent = devices.length + " device(s)";
      heading.appendChild(badge);
    }
    el.appendChild(heading);
    const bodyWrap = document.createElement("div");
    bodyWrap.className = "bacnet-result-body";
    if (devices && devices.length > 0) {
      const table = document.createElement("div");
      table.className = "table-responsive";
      table.innerHTML = "<table class=\"table table-sm table-hover bacnet-devices-table\"><thead><tr><th>Device</th><th>Address</th><th>Description</th><th>Max APDU</th><th>Vendor</th></tr></thead><tbody></tbody></table>";
      const tbody = table.querySelector("tbody");
      devices.forEach(function (d) {
        const tr = document.createElement("tr");
        tr.innerHTML = "<td><code>" + escapeHtml(d["i-am-device-identifier"] || "") + "</code></td>" +
          "<td>" + escapeHtml(d["device-address"] || "") + "</td>" +
          "<td class=\"text-muted small\">" + escapeHtml((d["device-description"] || "").slice(0, 60)) + "</td>" +
          "<td>" + escapeHtml(String(d["max-apdu-length-accepted"] != null ? d["max-apdu-length-accepted"] : "")) + "</td>" +
          "<td>" + escapeHtml(String(d["vendor-id"] != null ? d["vendor-id"] : "")) + "</td>";
        tbody.appendChild(tr);
      });
      bodyWrap.appendChild(table);
    } else {
      const p = document.createElement("p");
      p.className = "text-muted small mb-0";
      p.textContent = devices ? "No devices in range." : "No device list in response.";
      bodyWrap.appendChild(p);
    }
    el.appendChild(bodyWrap);
    addRawCollapse(el, body);
  }

  function renderBacnetPointDiscoveryResult(el, body) {
    const res = body && body.result && body.result.data;
    const deviceAddress = res && res.device_address;
    const objects = res && res.objects;
    el.className = "bacnet-result-card mt-3";
    el.innerHTML = "";
    const heading = document.createElement("div");
    heading.className = "bacnet-result-heading";
    heading.innerHTML = "<span class=\"bacnet-status-dot success\"></span><strong>Point discovery</strong>";
    if (deviceAddress) {
      const addr = document.createElement("span");
      addr.className = "text-muted small";
      addr.textContent = deviceAddress;
      heading.appendChild(addr);
    }
    if (objects && objects.length) {
      const badge = document.createElement("span");
      badge.className = "badge bg-secondary";
      badge.textContent = objects.length + " object(s)";
      heading.appendChild(badge);
    }
    el.appendChild(heading);
    const bodyWrap = document.createElement("div");
    bodyWrap.className = "bacnet-result-body";
    if (objects && objects.length > 0) {
      const tree = document.createElement("ul");
      tree.className = "list-unstyled bacnet-objects-tree mb-0";
      objects.forEach(function (ob) {
        const li = document.createElement("li");
        li.className = "bacnet-object-item";
        li.innerHTML = "<code class=\"bacnet-oid\">" + escapeHtml(ob.object_identifier || "") + "</code> <span class=\"bacnet-obj-name\">" + escapeHtml(ob.name || "") + "</span>";
        tree.appendChild(li);
      });
      bodyWrap.appendChild(tree);
    } else {
      const p = document.createElement("p");
      p.className = "text-muted small mb-0";
      p.textContent = objects ? "No objects." : "No object list in response.";
      bodyWrap.appendChild(p);
    }
    el.appendChild(bodyWrap);
    addRawCollapse(el, body);
  }

  function renderBacnetError(el, errorMsg, body) {
    el.className = "bacnet-result-card bacnet-result-error mt-3";
    el.innerHTML = "";
    const heading = document.createElement("div");
    heading.className = "d-flex align-items-center gap-2 mb-1";
    heading.innerHTML = "<span class=\"bacnet-status-dot danger\"></span><strong>Error</strong>";
    el.appendChild(heading);
    const p = document.createElement("p");
    p.className = "mb-0 small";
    p.textContent = errorMsg || "Unknown error";
    el.appendChild(p);
    if (body) addRawCollapse(el, body);
  }

  function bacnetWhoisRange() {
    const resultEl = document.getElementById("bacnet-result");
    const url = getBacnetUrl();
    const start = parseInt(document.getElementById("whois-start").value, 10) || 1;
    const end = parseInt(document.getElementById("whois-end").value, 10) || 3456799;
    resultEl.innerHTML = "<span class=\"text-muted\">Who-Is " + start + "–" + end + "…</span>";
    resultEl.className = "bacnet-result-loading mt-3";
    api("/bacnet/whois_range", {
      method: "POST",
      body: JSON.stringify({ url: url, request: { start_instance: start, end_instance: end } }),
    })
      .then((r) => r.json())
      .then((data) => {
        console.log("[bacnet] whois_range", data);
        if (data.ok && data.body) renderBacnetWhoisResult(resultEl, data.body);
        else renderBacnetError(resultEl, data.error || "No body", data.body);
      })
      .catch((err) => renderBacnetError(resultEl, err.message || "network error"));
  }

  function bacnetPointDiscovery() {
    const resultEl = document.getElementById("bacnet-result");
    const url = getBacnetUrl();
    const deviceInstance = parseInt(document.getElementById("discovery-instance").value, 10) || 3456789;
    resultEl.innerHTML = "<span class=\"text-muted\">Point discovery (device " + deviceInstance + ")…</span>";
    resultEl.className = "bacnet-result-loading mt-3";
    api("/bacnet/point_discovery", {
      method: "POST",
      body: JSON.stringify({ url: url, instance: { device_instance: deviceInstance } }),
    })
      .then((r) => r.json())
      .then((data) => {
        console.log("[bacnet] point_discovery", data);
        if (data.ok && data.body) renderBacnetPointDiscoveryResult(resultEl, data.body);
        else renderBacnetError(resultEl, data.error || "No body", data.body);
      })
      .catch((err) => renderBacnetError(resultEl, err.message || "network error"));
  }

  function initPanels() {
    document.querySelectorAll("a[data-panel]").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        document.querySelectorAll(".ofdd-nav-link").forEach((x) => x.classList.remove("nav-active"));
        a.classList.add("nav-active");
        const panelId = "panel-" + a.dataset.panel;
        document.querySelectorAll(".panel").forEach((p) => p.classList.add("hidden"));
        const panel = document.getElementById(panelId);
        if (panel) panel.classList.remove("hidden");
      });
    });
  }

  function initContextMenu() {
    document.getElementById("ctx-delete").addEventListener("click", () => {
      const menu = document.getElementById("context-menu");
      const kind = menu.dataset.kind;
      const id = menu.dataset.id;
      if (!kind || !id) return;
      if (!window.confirm("Delete " + (menu.dataset.label || kind) + "? This may cascade.")) return;
      hideContextMenu();
      deleteNode(kind, id);
    });
    document.addEventListener("click", hideContextMenu);
  }

  function refreshLastFddRun() {
    api("/run-fdd/status")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        const el = document.getElementById("last-fdd-run");
        if (!el) return;
        if (data && data.last_run) {
          const d = new Date(data.last_run.run_ts);
          el.textContent = "Last run: " + d.toLocaleString() + (data.last_run.status !== "ok" ? " (" + data.last_run.status + ")" : "");
        } else el.textContent = "Last run: never";
      })
      .catch(() => {});
  }

  api("/")
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (data && data.version) setVersionInUI(data.version);
      const urlInput = document.getElementById("bacnet-url");
      if (data && data.bacnet_server_url && urlInput) urlInput.value = data.bacnet_server_url;
      else if (urlInput && !urlInput.value) urlInput.value = "http://localhost:8080";
    })
    .catch(() => {});

  refreshLastFddRun();
  setInterval(refreshLastFddRun, 5000);

  document.getElementById("refresh-tree-btn").addEventListener("click", buildTree);
  document.getElementById("add-site-btn").addEventListener("click", addSite);
  document.getElementById("run-fdd-btn").addEventListener("click", runFdd);
  document.getElementById("bacnet-test-btn").addEventListener("click", testBacnet);
  const whoisBtn = document.getElementById("bacnet-whois-btn");
  if (whoisBtn) whoisBtn.addEventListener("click", bacnetWhoisRange);
  const discoveryBtn = document.getElementById("bacnet-discovery-btn");
  if (discoveryBtn) discoveryBtn.addEventListener("click", bacnetPointDiscovery);

  initPanels();
  initContextMenu();
  buildTree();
})();
