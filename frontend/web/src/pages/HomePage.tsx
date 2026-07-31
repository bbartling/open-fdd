import { useEffect, useState } from "react";
import { AppShell } from "../components/AppShell";
import { apiFetch } from "../api/client";
import type { CapabilitiesResponse } from "../api/contract";
import {
  Select,
  Slider,
  Checkbox,
  Metric,
  Expander,
  InlineAlert,
  StatusBadge,
  PlotlyHost,
  ConfirmModal,
  ToastRegion,
} from "../components/widgets";

export function HomePage() {
  const [contractVersion, setContractVersion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [demoSelect, setDemoSelect] = useState("a");
  const [demoSlider, setDemoSlider] = useState(50);
  const [demoChecked, setDemoChecked] = useState(false);
  const [demoExpanded, setDemoExpanded] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [toasts, setToasts] = useState<{ id: string; message: string }[]>([]);

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

        <section className="widget-gallery" data-testid="widget-gallery">
          <h2>Widget primitives (P1-M3-02)</h2>
          <InlineAlert id="gallery-hint" variant="info">
            Controlled parity widgets — keyboard and a11y baseline for M3 gate.
          </InlineAlert>

          <div className="widget-gallery__section">
            <h3>Form controls</h3>
            <div className="widget-gallery__grid">
              <Select
                id="demo-select"
                label="Sample select"
                value={demoSelect}
                options={[
                  { value: "a", label: "Option A" },
                  { value: "b", label: "Option B" },
                ]}
                onChange={setDemoSelect}
              />
              <Slider
                id="demo-slider"
                label="Sample slider"
                value={demoSlider}
                min={0}
                max={100}
                step={5}
                onChange={setDemoSlider}
              />
              <Checkbox
                id="demo-checkbox"
                label="Enable feature"
                checked={demoChecked}
                onChange={setDemoChecked}
              />
            </div>
          </div>

          <div className="widget-gallery__section">
            <h3>Display &amp; feedback</h3>
            <div className="widget-gallery__grid">
              <Metric
                id="demo-metric"
                label="Energy savings"
                value="12.4%"
                delta={{ value: "+2.1%", direction: "up" }}
              />
              <StatusBadge
                id="demo-badge"
                label="Running"
                variant="success"
              />
              <PlotlyHost id="demo-plot" label="Trend chart" />
            </div>
          </div>

          <div className="widget-gallery__section">
            <Expander
              id="demo-expander"
              label="Advanced options"
              expanded={demoExpanded}
              onChange={setDemoExpanded}
            >
              <p>Expander content for parity demos and future form drafts.</p>
            </Expander>
          </div>
        </section>
      </div>

      <ConfirmModal
        id="demo-confirm"
        open={modalOpen}
        title="Confirm action"
        message="This is a parity confirm modal."
        onConfirm={() => {
          setModalOpen(false);
          setToasts((t) => [
            ...t,
            { id: String(Date.now()), message: "Confirmed" },
          ]);
        }}
        onCancel={() => setModalOpen(false)}
      />
      <ToastRegion
        toasts={toasts}
        onDismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))}
      />
    </AppShell>
  );
}
