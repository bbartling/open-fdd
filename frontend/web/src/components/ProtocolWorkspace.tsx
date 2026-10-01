import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api/client";
import type { CapabilitiesAggregate, CapabilitiesResponse } from "../api/contract";
import { Button } from "./widgets";
import {
  capabilityResponseAggregate,
  PROTOCOL_WORKSPACE_TABS,
  summarizeAggregateUpstream,
  summarizeProtocolCapabilities,
  type ProtocolCapabilityStatus,
  type ProtocolWorkspaceId,
} from "../lib/protocolCapabilities";

interface ProtocolWorkspaceProps {
  protocol: ProtocolWorkspaceId;
  onProtocolChange: (protocol: ProtocolWorkspaceId) => void;
}

function statusClass(state: ProtocolCapabilityStatus["state"]): string {
  return `protocol-status-card__state protocol-status-card__state--${state}`;
}

function evidenceLabels(states: ProtocolCapabilityStatus["connectionStates"]): string {
  const labels = [...new Set(states)].map((state) => state.replaceAll("_", " "));
  return labels.length > 0 ? labels.join(", ") : "Not reported";
}

function ProtocolStatusCard({ status }: { status: ProtocolCapabilityStatus }) {
  return (
    <article
      className="protocol-status-card"
      data-testid={`protocol-status-${status.protocol}`}
      aria-label={`${status.label} capability status`}
    >
      <h3>{status.label}</h3>
      <p className={statusClass(status.state)} data-testid={`protocol-state-${status.protocol}`}>
        {status.stateLabel}
      </p>
      <p className="muted">{status.reason}</p>
      {status.evidenceCount > 0 ? (
        <dl className="protocol-status-card__facts">
          <div>
            <dt>Configured sources</dt>
            <dd>{status.configuredCount}</dd>
          </div>
          <div>
            <dt>Ready sources</dt>
            <dd>{status.readyCount}</dd>
          </div>
          {status.protocol === "mqtt" ? (
            <>
              <div>
                <dt>MQTT connection</dt>
                <dd>{evidenceLabels(status.connectionStates)}</dd>
              </div>
              <div>
                <dt>Durable delivery</dt>
                <dd>{evidenceLabels(status.durableStates)}</dd>
              </div>
            </>
          ) : null}
        </dl>
      ) : null}
    </article>
  );
}

function ActiveProtocolStatus({
  protocol,
  loading,
  error,
  status,
}: {
  protocol: ProtocolWorkspaceId;
  loading: boolean;
  error: string | null;
  status: ProtocolCapabilityStatus | undefined;
}) {
  const label = PROTOCOL_WORKSPACE_TABS.find((tab) => tab.id === protocol)?.label ?? protocol;
  return (
    <section
      className="protocol-workspace__active"
      aria-labelledby="protocol-workspace-active-heading"
      data-testid="protocol-workspace-active"
    >
      <h2 id="protocol-workspace-active-heading">{label}</h2>
      {loading ? (
        <p role="status" data-testid="protocol-active-loading">Loading capability status…</p>
      ) : error ? (
        <p className="muted">Capability status is unavailable until the status request succeeds.</p>
      ) : status ? (
        <>
          <p className={statusClass(status.state)}>{status.stateLabel}</p>
          <p className="muted">{status.reason}</p>
        </>
      ) : (
        <p className="muted">No capability evidence was returned.</p>
      )}
    </section>
  );
}

export function ProtocolWorkspace({ protocol, onProtocolChange }: ProtocolWorkspaceProps) {
  const [aggregate, setAggregate] = useState<CapabilitiesAggregate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiFetch<CapabilitiesResponse>("/api/capabilities");
      setAggregate(capabilityResponseAggregate(response));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const statuses = useMemo(
    () => summarizeProtocolCapabilities(aggregate),
    [aggregate],
  );
  const upstreamStatus = useMemo(
    () => summarizeAggregateUpstream(aggregate),
    [aggregate],
  );
  const activeStatus = statuses.find((status) => status.protocol === protocol);

  return (
    <section
      className="protocol-workspace"
      aria-labelledby="protocol-workspace-heading"
      data-testid="protocol-workspace"
    >
      <div className="section-heading-row">
        <div>
          <h2 id="protocol-workspace-heading">Protocol workspace</h2>
        </div>
        <Button
          id="protocol-status-refresh"
          label={loading ? "Refreshing…" : "Refresh status"}
          variant="secondary"
          loading={loading}
          testId="protocol-status-refresh"
          onClick={() => void refresh()}
        />
      </div>

      <fieldset className="protocol-tabs" aria-label="Protocol troubleshooting views">
        <legend className="sr-only">Protocol troubleshooting views</legend>
        {PROTOCOL_WORKSPACE_TABS.map((tab) => (
          <label
            key={tab.id}
            className={`protocol-tab${protocol === tab.id ? " protocol-tab--active" : ""}`}
            data-testid={`protocol-tab-${tab.id}`}
          >
            <input
              type="radio"
              name="operations-protocol"
              value={tab.id}
              checked={protocol === tab.id}
              aria-label={tab.label}
              onChange={() => onProtocolChange(tab.id)}
            />
            <span>{tab.label}</span>
          </label>
        ))}
      </fieldset>

      {loading ? (
        <p role="status" className="inline-alert" data-testid="protocol-status-loading">
          Loading protocol capability status…
        </p>
      ) : error ? (
        <div className="inline-alert inline-alert--error" role="alert" data-testid="protocol-status-error">
          Unable to load protocol capability status: {error}
          <Button
            id="protocol-status-retry"
            label="Retry"
            variant="secondary"
            testId="protocol-status-retry"
            onClick={() => void refresh()}
          />
        </div>
      ) : (
        <>
          {upstreamStatus ? (
            <div
              className="inline-alert inline-alert--error"
              role="alert"
              data-testid="protocol-upstream-status"
            >
              {upstreamStatus.reason}
            </div>
          ) : null}
          <div className="protocol-status-grid" data-testid="protocol-status-grid">
            {statuses.map((status) => <ProtocolStatusCard key={status.protocol} status={status} />)}
          </div>
        </>
      )}

      <ActiveProtocolStatus
        protocol={protocol}
        loading={loading}
        error={error}
        status={activeStatus}
      />
    </section>
  );
}
