type Props = {
  variant: "ut3" | "fusion";
};

export default function CsvWorkflowGuide({ variant }: Props) {
  if (variant === "ut3") {
    return (
      <section className="panel csv-workflow-guide">
        <h3 className="panel-title">How to use UT3 import (recommended)</h3>
        <ol className="csv-workflow-steps">
          <li>
            <strong>Upload</strong> CSV files (sign in as integrator).
          </li>
          <li>
            <strong>Choose mode:</strong> <em>Append</em> stacks school-year kW files on <code>Date</code>.{" "}
            <em>Join</em> merges one kW file with weather (uses file 1 + file 2 only).
          </li>
          <li>
            Set <strong>Timestamp column</strong> to <code>Date</code> for kW · <code>time_local</code> for Open-Meteo
            weather.
          </li>
          <li>
            <strong>Preview plan</strong>, then <strong>Open in fusion preview</strong> (or share <code>/csv?session=…</code>)
          </li>
          <li>
            Review merged table in fusion wiresheet, then <strong>Save to Arrow store (session)</strong>
          </li>
        </ol>
      </section>
    );
  }

  return (
    <section className="panel csv-workflow-guide">
      <h3 className="panel-title">Client fusion (quick preview &amp; historian commit)</h3>
      <ol className="csv-workflow-steps">
        <li>
          <strong>Drop CSV files</strong> below (browser-only parse).
        </li>
        <li>
          <strong>Append rows</strong> — stack files that share the same columns (e.g. four school-year kW files on{" "}
          <code>Date</code>).
        </li>
        <li>
          <strong>Join on key</strong> — only when every file has the <em>same</em> timestamp column name. Different
          names (e.g. <code>Date</code> vs <code>time_local</code>) → use UT3 import above.
        </li>
        <li>
          Check <strong>Merged preview</strong>, map FDD inputs, then <strong>Commit → historian + model</strong>.
        </li>
      </ol>
      <p className="muted csv-workflow-note">
        <code>timezone</code> is a label column in weather files, not a timestamp — use <code>Date</code> or{" "}
        <code>time_local</code> as the merge key.
      </p>
    </section>
  );
}
