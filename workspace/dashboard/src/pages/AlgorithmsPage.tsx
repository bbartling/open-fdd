import { Link } from "react-router-dom";
import PageHeader from "../components/PageHeader";

export default function AlgorithmsPage() {
  return (
    <div className="page page-wide">
      <PageHeader
        title="Algorithms"
        subtitle="Python supervisory sequences (GL36 trim & respond, plant resets) — outputs setpoints and request levels instead of fault masks."
      />

      <div className="panel algorithms-coming-soon">
        <p className="algorithms-badge">COMING SOON</p>
        <h2>Supervisory algorithms tab</h2>
        <p className="muted">
          This tab will use the same Arrow historian as SQL FDD rules: download a dev kit zip, edit constants locally,
          run <code>run_test.py</code>, then upload <code>algorithm.py</code>. FDD rules detect faults; algorithms
          compute trim/respond setpoints, zone request counts, and plant enable logic.
        </p>
        <ul>
          <li>AHU duct static pressure reset (GL36 §5.1.14.4)</li>
          <li>AHU supply air temperature reset (GL36 trim & respond)</li>
          <li>VAV zone request generators (cooling + pressure)</li>
          <li>Chilled / hot water plant trim & respond</li>
        </ul>
        <p className="muted">
          Until this tab ships, use <Link to="/sql-fdd">SQL FDD Rules</Link> for fault detection and{" "}
          <Link to="/model">Model &amp; assignments</Link> for point bindings.
        </p>
      </div>
    </div>
  );
}
