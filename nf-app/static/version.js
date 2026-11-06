// App version in the header: "v5.0.0 · abc1234", linked to that exact commit on GitHub.
// version.json is generated at deploy time by scripts/nf/hooks/nf_app_sync.py from the repo's
// VERSION file + `git rev-parse HEAD` (never committed, never edited by hand), so what a box
// shows always maps to the open-fdd revision that was pushed to it. Dev mock serves the same.
(function () {
  const REPO = "https://github.com/bbartling/open-fdd";
  async function mount() {
    const h1 = document.querySelector("header h1");
    if (!h1) return;
    let v;
    try {
      const r = await fetch("version.json", { cache: "no-store", credentials: "same-origin" });
      if (!r.ok) return;
      v = await r.json();
    } catch (e) {
      return;
    }
    if (!v || !v.version) return;
    const a = document.createElement("a");
    a.className = "app-version";
    const sha = (v.commit || "").slice(0, 7);
    a.textContent = `v${v.version}${sha ? ` · ${sha}` : ""}${v.dirty ? "+" : ""}`;
    a.href = v.commit ? `${REPO}/tree/${v.commit}` : `${REPO}/releases`;
    a.target = "_blank";
    a.rel = "noopener";
    a.title = `Open-FDD ${v.version}${v.commit ? `, commit ${v.commit}` : ""}${v.dirty ? " (local changes)" : ""}`
      + (v.deployed ? `, deployed ${v.deployed}` : "");
    h1.insertAdjacentElement("afterend", a);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
