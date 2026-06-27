import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { useActiveSiteId } from "../lib/useActiveSiteId";

const RULE_CHAIN = [
  "AHU",
  "Supply Air Temp",
  "Supply Air Temp Setpoint",
  "Static Pressure",
  "Outdoor Air Temp",
  "SQL Rule",
  "Fault",
  "Alert",
  "Report",
];

/** Rule mapping shell — links Haystack metadata to executable DataFusion rules. */
export default function WiresheetRulesPage() {
  const siteId = useActiveSiteId();

  return (
    <div className="page wiresheet-subpage">
      <PageHeader
        title="Rule Mapping"
        subtitle="Map Haystack points into SQL rules with inputs, outputs, dependencies, and runtime status."
        meta={
          <div className="wiresheet-toolbar">
            <Link className="secondary-btn" to="/wiresheet">
              Wiresheet Studio
            </Link>
            <Link className="secondary-btn" to="/sql-fdd">
              SQL FDD editor
            </Link>
          </div>
        }
      />

      <p className="muted">Site: {siteId || "loading…"}</p>

      <section className="panel">
        <h3 className="panel-title">Example rule chain</h3>
        <ol className="wiresheet-rule-chain">
          {RULE_CHAIN.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>

      <div className="wiresheet-subpage-grid">
        <section className="panel">
          <h3 className="panel-title">Per-rule detail</h3>
          <ul className="muted">
            <li>Inputs & outputs</li>
            <li>Dependencies graph</li>
            <li>SQL body & validation status</li>
            <li>Last runtime & performance</li>
          </ul>
        </section>
        <section className="panel">
          <h3 className="panel-title">Open in studio</h3>
          <p className="muted">
            Edit the live validation graph visually on the Wiresheet canvas, then validate and activate from SQL FDD.
          </p>
          <Link className="primary-btn" to="/wiresheet">
            Open Wiresheet Studio
          </Link>
        </section>
      </div>
    </div>
  );
}
