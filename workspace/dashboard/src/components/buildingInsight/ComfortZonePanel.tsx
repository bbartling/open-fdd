type ZoneRow = {
  label?: string;
  equipment_name?: string;
  equipment_id?: string;
  column?: string;
  day_avg_f?: number;
  night_avg_f?: number;
  recovery_f_per_min?: number;
  worst_reason?: string;
};

type AhuSystem = {
  ahu_id?: string;
  ahu_name?: string;
  fan_column?: string | null;
  median_recovery_f_per_min?: number | null;
  zones?: ZoneRow[];
};

type Opportunity = {
  topic?: string;
  suggestion?: string;
  signal?: string;
};

type Props = {
  zoneSentence?: string;
  deviceSentence?: string;
  worstZones?: ZoneRow[];
  zoneSystems?: AhuSystem[];
  opportunities?: Opportunity[];
  lookbackDays: number;
};

function fmtTemp(v: number | null | undefined): string {
  return v != null ? `${v}°F` : "—";
}

function fmtRecovery(v: number | null | undefined): string {
  return v != null ? `${v}°F/min` : "—";
}

export default function ComfortZonePanel({
  zoneSentence,
  deviceSentence,
  worstZones,
  zoneSystems,
  opportunities,
  lookbackDays,
}: Props) {
  const zones = (worstZones || []).slice(0, 6);
  const systems = (zoneSystems || []).filter((s) => (s.zones?.length ?? 0) > 0);
  return (
    <div className="bis-card bis-comfort-card">
      <h3>Comfort</h3>
      <h2>Zone temperature</h2>
      <p className="bis-card-sub">{lookbackDays}-day historian · overnight vs occupied averages</p>
      {zoneSentence ? <p className="bis-lead">{zoneSentence}</p> : null}
      {deviceSentence ? <p className="bis-muted-line">{deviceSentence}</p> : null}
      {zones.length ? (
        <div className="bis-zone-table-wrap">
          <p className="bis-muted-line">
            Site averages are in the summary above. Table lists worst-case zones (weak setback or slow recovery), not
            every sensor.
          </p>
          <table className="bis-zone-table">
            <thead>
              <tr>
                <th>VAV / zone</th>
                <th>Night avg</th>
                <th>Day avg</th>
                <th>Recovery</th>
              </tr>
            </thead>
            <tbody>
              {zones.map((z, i) => (
                <tr key={`${z.column || z.equipment_name || z.label}-${i}`}>
                  <td>{z.equipment_name || z.label || "—"}</td>
                  <td>{fmtTemp(z.night_avg_f)}</td>
                  <td>{fmtTemp(z.day_avg_f)}</td>
                  <td>{fmtRecovery(z.recovery_f_per_min)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {systems.length ? (
        <div className="bis-zone-tree-wrap">
          <p className="bis-muted-line">Per-AHU breakdown (collapsed — expand to see all VAVs on each system).</p>
          {systems.map((sys) => (
            <details key={sys.ahu_id || sys.ahu_name} className="bis-zone-tree-ahu">
              <summary>
                {sys.ahu_name || sys.ahu_id || "AHU"}
                {sys.median_recovery_f_per_min != null
                  ? ` · median recovery ${sys.median_recovery_f_per_min}°F/min`
                  : sys.fan_column
                    ? ""
                    : " · no fan column mapped"}
                {!sys.fan_column ? " · recovery N/A" : ""}
              </summary>
              <table className="bis-zone-table bis-zone-table-nested">
                <thead>
                  <tr>
                    <th>VAV / zone</th>
                    <th>Night</th>
                    <th>Day</th>
                    <th>Recovery</th>
                  </tr>
                </thead>
                <tbody>
                  {(sys.zones || []).map((z, i) => (
                    <tr key={`${sys.ahu_id}-${z.column || i}`}>
                      <td>{z.equipment_name || z.label || "—"}</td>
                      <td>{fmtTemp(z.night_avg_f)}</td>
                      <td>{fmtTemp(z.day_avg_f)}</td>
                      <td>{fmtRecovery(z.recovery_f_per_min)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          ))}
        </div>
      ) : null}
      {opportunities?.length ? (
        <ul className="bis-opp-list">
          {opportunities.slice(0, 3).map((o, i) => (
            <li key={`${o.topic ?? "tip"}-${i}`}>
              <strong>{(o.topic || "tip").replace(/_/g, " ")}</strong>
              <span>{o.suggestion || o.signal}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
