import { useEffect, useState } from "react";
import { getBridgeBase } from "../lib/api";

type HealthPayload = {
  openfdd_version?: string;
};

export default function OpenFddVersion() {
  const [rev, setRev] = useState<string | null>(null);

  useEffect(() => {
    const base = getBridgeBase();
    fetch(`${base}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: HealthPayload | null) => {
        if (!data?.openfdd_version) return;
        setRev(`v${data.openfdd_version}`);
      })
      .catch(() => {});
  }, []);

  if (!rev) return null;

  return (
    <div className="openfdd-rev muted" title="Open-FDD package version from bridge /health">
      {rev}
    </div>
  );
}
