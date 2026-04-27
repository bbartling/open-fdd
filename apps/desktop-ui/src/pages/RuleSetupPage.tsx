import { useEffect, useState } from "react";
import { desktopFetch } from "../lib/api";

type RuleDefaults = {
  rule_pack: string;
  source_dir: string;
  files: string[];
};

type RuleInstall = {
  rule_pack: string;
  rules_path: string;
  copied: string[];
};

type Site = { id: string; name: string };

export function RuleSetupPage() {
  const [defaults, setDefaults] = useState<RuleDefaults | null>(null);
  const [sites, setSites] = useState<Site[]>([]);
  const [siteId, setSiteId] = useState("");
  const [installedPath, setInstalledPath] = useState("");
  const [status, setStatus] = useState("Install default AHU/VAV YAML rules and attach rule pack to a site.");

  useEffect(() => {
    desktopFetch<RuleDefaults>("/rules/defaults")
      .then(setDefaults)
      .catch((e) => setStatus(e instanceof Error ? e.message : String(e)));
    desktopFetch<Site[]>("/sites")
      .then((s) => {
        setSites(s);
        if (s.length > 0) setSiteId(s[0].id);
      })
      .catch((e) => setStatus(e instanceof Error ? e.message : String(e)));
  }, []);

  async function installDefaults() {
    try {
      const out = await desktopFetch<RuleInstall>("/rules/defaults/install", { method: "POST" });
      setInstalledPath(out.rules_path);
      setStatus(`Installed ${out.copied.length} default rules to ${out.rules_path}`);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  async function attachPackToSite() {
    if (!siteId) return;
    try {
      const pack = defaults?.rule_pack ?? "ahu_vav";
      await desktopFetch(`/sites/${siteId}/rule-pack`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rule_pack: pack }),
      });
      setStatus(`Attached rule pack '${pack}' to site ${siteId.slice(0, 8)} and synced TTL.`);
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="card">
      <h2 className="title">FDD Rule Setup</h2>
      <p style={{ color: "var(--muted)" }}>
        Step 1 after CSV import: install default AHU/VAV rules, then attach the rule pack to the site so TTL carries the rule-pack metadata for AI context.
      </p>
      <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
        <button onClick={() => void installDefaults()}>Install default AHU/VAV YAML rules</button>
        <button onClick={() => void attachPackToSite()}>Attach rule pack to selected site</button>
      </div>
      <div className="grid-two">
        <div>
          <label>Site</label>
          <select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({s.id.slice(0, 8)})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label>Installed rules path</label>
          <input readOnly value={installedPath} placeholder="Not installed yet" />
        </div>
      </div>
      <textarea readOnly value={status} style={{ marginTop: 10, minHeight: 80 }} />
      <textarea
        readOnly
        value={
          defaults
            ? `Default rule pack: ${defaults.rule_pack}\nSource: ${defaults.source_dir}\nFiles:\n${defaults.files.join("\n")}`
            : "Loading default rules..."
        }
        style={{ marginTop: 10, minHeight: 180 }}
      />
    </div>
  );
}
