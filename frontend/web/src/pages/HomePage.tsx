import { useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { apiFetch } from "../api/client";
import type { CapabilitiesResponse } from "../api/contract";

export function HomePage() {
  const [contractVersion, setContractVersion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiFetch<CapabilitiesResponse>("/api/capabilities")
      .then((body) => {
        if (!cancelled) {
          setContractVersion(body.contract.contract_version);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AppShell
      title="Home"
      caption="React shell — Streamlit frame parity (P1-M3-01)"
      activeSectionId="overview"
    >
      <div className="page-placeholder">
        <h2>Welcome to Open-FDD</h2>
        <p>React UI shell — Phase 1 parity scaffold.</p>
        {loading && (
          <div data-testid="home-loading">
            <span className="spinner" aria-hidden />{" "}
            <span className="loading">Loading capabilities…</span>
            <div className="skeleton skeleton--title" />
            <div className="skeleton skeleton--line" />
          </div>
        )}
        {error && (
          <div className="alert alert--danger" role="alert">
            {error}
          </div>
        )}
        {contractVersion && (
          <p>
            Contract version:{" "}
            <span className="contract-badge" data-testid="contract-version">
              {contractVersion}
            </span>
          </p>
        )}
      </div>
    </AppShell>
  );
}
