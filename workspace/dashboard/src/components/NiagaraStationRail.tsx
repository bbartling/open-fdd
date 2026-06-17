import type { NiagaraStation } from "../lib/niagara-api";

export type StationRailMeta = {
  pointCount: number;
  pollRunning: boolean;
  connected: boolean | null;
  connectionTested: boolean | null;
};

type Props = {
  stations: NiagaraStation[];
  selectedStationId: string;
  isNewDraft: boolean;
  metaById: Record<string, StationRailMeta>;
  onSelect: (station: NiagaraStation) => void;
  onNew: () => void;
  onDelete: (stationId: string) => void;
  pending: boolean;
};

function statusGlyph(meta: StationRailMeta | undefined, enabled: boolean): { mark: string; title: string; className: string } {
  if (!enabled) {
    return { mark: "−", title: "Disabled", className: "niagara-rail-mark off" };
  }
  if (meta?.pollRunning) {
    return { mark: "+", title: "Polling", className: "niagara-rail-mark live" };
  }
  if (meta?.connected === true || meta?.connectionTested === true) {
    return { mark: "+", title: "Connected", className: "niagara-rail-mark ok" };
  }
  if (meta?.connected === false || meta?.connectionTested === false) {
    return { mark: "−", title: "Connection failed", className: "niagara-rail-mark err" };
  }
  return { mark: "○", title: "Not tested", className: "niagara-rail-mark idle" };
}

export default function NiagaraStationRail({
  stations,
  selectedStationId,
  isNewDraft,
  metaById,
  onSelect,
  onNew,
  onDelete,
  pending,
}: Props) {
  const index = isNewDraft
    ? -1
    : Math.max(
        0,
        stations.findIndex((s) => s.id === selectedStationId),
      );

  function go(delta: number) {
    if (!stations.length) return;
    const next = (index + delta + stations.length) % stations.length;
    onSelect(stations[next]);
  }

  const selected = stations.find((s) => s.id === selectedStationId);

  return (
    <div className="panel niagara-station-rail-top">
      <div className="niagara-rail-toolbar">
        <div className="niagara-rail-head">
          <h3 className="panel-title">Stations</h3>
          <span className="muted niagara-rail-count">{stations.length} saved</span>
        </div>
        <p className="muted niagara-rail-hint">
          <span className="niagara-rail-mark live">+</span> polling/OK ·{" "}
          <span className="niagara-rail-mark err">−</span> off/failed ·{" "}
          <span className="niagara-rail-mark idle">○</span> not tested
        </p>
        <button type="button" className="primary-btn niagara-rail-new" onClick={onNew}>
          + New station
        </button>
      </div>

      <div className="niagara-rail-body">
        <div className="niagara-rail-nav">
          <button
            type="button"
            className="secondary-btn niagara-rail-arrow"
            disabled={!stations.length || isNewDraft}
            onClick={() => go(-1)}
            aria-label="Previous station"
          >
            ‹
          </button>
          <div className="niagara-rail-card-wrap">
            {isNewDraft ? (
              <div className="niagara-rail-card active draft">
                <div className="niagara-rail-card-title">New station</div>
                <div className="muted">Fill connection details, then Save.</div>
              </div>
            ) : selected ? (
              <div className="niagara-rail-card active">
                {(() => {
                  const st = statusGlyph(metaById[selected.id], selected.enabled !== false);
                  return (
                    <>
                      <div className="niagara-rail-card-head">
                        <span className={st.className} title={st.title}>
                          {st.mark}
                        </span>
                        <div className="niagara-rail-card-title">{selected.name}</div>
                        <span className="niagara-rail-card-meta">
                          {metaById[selected.id]?.pointCount ?? 0} pt
                          {metaById[selected.id]?.pollRunning ? " · polling" : ""}
                        </span>
                      </div>
                      <div className="niagara-rail-card-url muted">{selected.station_url}</div>
                    </>
                  );
                })()}
              </div>
            ) : (
              <div className="niagara-rail-card muted">Select a station or create one.</div>
            )}
          </div>
          <button
            type="button"
            className="secondary-btn niagara-rail-arrow"
            disabled={!stations.length || isNewDraft}
            onClick={() => go(1)}
            aria-label="Next station"
          >
            ›
          </button>
        </div>

        {stations.length > 0 ? (
          <ul className="niagara-rail-chips" aria-label="Saved stations">
            {stations.map((s) => {
              const meta = metaById[s.id];
              const st = statusGlyph(meta, s.enabled !== false);
              const active = s.id === selectedStationId && !isNewDraft;
              return (
                <li key={s.id} className={`niagara-rail-chip${active ? " active" : ""}`}>
                  <button type="button" className="niagara-rail-chip-btn" onClick={() => onSelect(s)}>
                    <span className={st.className} title={st.title}>
                      {st.mark}
                    </span>
                    <span className="niagara-rail-chip-name">{s.name}</span>
                    <span className="muted niagara-rail-chip-pts">{meta?.pointCount ?? 0}</span>
                  </button>
                  <button
                    type="button"
                    className="niagara-rail-chip-delete"
                    title={`Delete ${s.name}`}
                    disabled={pending}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (window.confirm(`Delete station "${s.name}"?`)) onDelete(s.id);
                    }}
                  >
                    ×
                  </button>
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
