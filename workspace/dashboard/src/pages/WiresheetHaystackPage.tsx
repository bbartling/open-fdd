import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";
import { useActiveSiteId } from "../lib/useActiveSiteId";

/** Haystack metadata management shell — site tree, tags, relationships (incremental). */
export default function WiresheetHaystackPage() {
  const siteId = useActiveSiteId();

  return (
    <div className="page wiresheet-subpage">
      <PageHeader
        title="Haystack Model"
        subtitle="Site → equipment → points → tags → relationships. Drag-and-drop assignment with validation preview."
        meta={
          <div className="wiresheet-toolbar">
            <Link className="secondary-btn" to="/wiresheet">
              Wiresheet Studio
            </Link>
            <Link className="secondary-btn" to="/model">
              Full model editor
            </Link>
          </div>
        }
      />

      <div className="wiresheet-subpage-grid">
        <section className="panel">
          <h3 className="panel-title">Site tree</h3>
          <p className="muted">Active site: {siteId || "loading…"}</p>
          <ul className="wiresheet-tree">
            <li>Site</li>
            <li className="indent">Equipment (AHU, VAV, plant)</li>
            <li className="indent-2">Points (cur, sensor, sp)</li>
            <li className="indent">Tags & markers</li>
            <li className="indent">Relationships</li>
          </ul>
        </section>
        <section className="panel">
          <h3 className="panel-title">Validation</h3>
          <p className="muted">
            Connect Haystack entities to driver refs on the Wiresheet canvas. AI-assisted tag suggestions ship in a
            later increment.
          </p>
        </section>
        <section className="panel">
          <h3 className="panel-title">Preview</h3>
          <p className="muted">Arrow schema preview and Brick compatibility hooks will appear here.</p>
        </section>
      </div>
    </div>
  );
}
