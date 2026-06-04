type ZoneRow = {
  label?: string;
  day_avg_f?: number;
  night_avg_f?: number;
  recovery_f_per_min?: number;
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
  opportunities?: Opportunity[];
  lookbackDays: number;
};

export default function ComfortZonePanel({
  zoneSentence,
  deviceSentence,
  worstZones,
  opportunities,
  lookbackDays,
}: Props) {
  const zones = (worstZones || []).slice(0, 6);
  return (
    <div className="bis-card bis-comfort-card">
      <h3>Comfort</h3>
      <h2>Zone temperature</h2>
      <p className="bis-card-sub">{lookbackDays}-day historian · overnight vs occupied averages</p>
      {zoneSentence ? <p className="bis-lead">{zoneSentence}</p> : null}
      {deviceSentence ? <p className="bis-muted-line">{deviceSentence}</p> : null}
      {zones.length ? (
        <div className="bis-zone-table-wrap">
          <table className="bis-zone-table">
            <thead>
              <tr>
                <th>Zone / sensor</th>
                <th>Night avg</th>
                <th>Day avg</th>
                <th>Recovery</th>
              </tr>
            </thead>
            <tbody>
              {zones.map((z, i) => (
                <tr key={`${z.label}-${i}`}>
                  <td>{z.label || "—"}</td>
                  <td>{z.night_avg_f != null ? `${z.night_avg_f}°F` : "—"}</td>
                  <td>{z.day_avg_f != null ? `${z.day_avg_f}°F` : "—"}</td>
                  <td>
                    {z.recovery_f_per_min != null ? `${z.recovery_f_per_min}°F/min` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {opportunities?.length ? (
        <ul className="bis-opp-list">
          {opportunities.slice(0, 3).map((o) => (
            <li key={o.topic}>
              <strong>{(o.topic || "tip").replace(/_/g, " ")}</strong>
              <span>{o.suggestion || o.signal}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
