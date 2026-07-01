import { Link } from "react-router-dom";

type Props = {
  mergeError?: string;
  fileCount?: number;
};

export default function CsvDataAssistant({ mergeError, fileCount = 0 }: Props) {
  const hasTimezoneError = mergeError?.includes("timezone");

  return (
    <section className="panel csv-assistant-panel">
      <h3 className="panel-title">Data assistant</h3>
      <p className="muted">
        Use an external MCP agent to profile columns, pick join keys, and draft merge recipes. Setup on the{" "}
        <Link to="/agent">External agents</Link> tab.
      </p>
      {hasTimezoneError ? (
        <div className="csv-assistant-tip csv-assistant-tip--warn">
          <strong>Fix:</strong> Change merge key from <code>timezone</code> to <code>Date</code> (kW files) or switch
          operation to <strong>Append rows</strong>. For kW + weather join, use <strong>UT3 CSV Import</strong> with
          mode Join and weather timestamp <code>time_local</code>.
        </div>
      ) : null}
      {fileCount >= 4 && !mergeError ? (
        <div className="csv-assistant-tip">
          <strong>Tip:</strong> Four school-year files → UT3 mode <em>Append</em>, timestamp <code>Date</code>, value{" "}
          <code>kW</code>. Client fusion: operation <em>Append rows</em>, merge key <code>Date</code>.
        </div>
      ) : null}
      <details className="csv-assistant-mcp">
        <summary>MCP tools for CSV &amp; model</summary>
        <ul>
          <li>
            <code>openfdd_model_sparql</code> — list sites, equipment, points after commit
          </li>
          <li>
            <code>openfdd_model_coverage</code> — mapped vs unmapped points
          </li>
          <li>
            <code>openfdd_csv_fusion_preview</code> — load UT3/agent session into CSV tab (before Feather)
          </li>
        </ul>
        <p className="muted">
          Setup: <Link to="/agent">External agents</Link> · repo <code>mcp/README.md</code>
        </p>
      </details>
    </section>
  );
}
