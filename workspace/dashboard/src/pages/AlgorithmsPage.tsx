import PageHeader from "../components/PageHeader";

export default function AlgorithmsPage() {
  return (
    <div className="page page-wide">
      <PageHeader
        title="Algorithms"
        subtitle={
          <>
            Python supervisory sequences (GL36 trim &amp; respond, plant resets) — same Arrow kit workflow as{" "}
            <a href="/rule-lab">Rule Lab</a>, but outputs setpoints and request levels instead of fault masks.
          </>
        }
      />

      <div className="panel algorithms-coming-soon">
        <p className="algorithms-badge">COMING SOON</p>
        <h2>Supervisory algorithms tab</h2>
        <p className="muted">
          This tab will mirror Rule Lab: download a PyArrow dev kit zip, edit constants locally, run{" "}
          <code>run_test.py</code>, then upload <code>algorithm.py</code>. FDD rules detect faults; algorithms
          compute trim/respond setpoints, zone request counts, and plant enable logic from the same feather historian.
        </p>
        <ul>
          <li>AHU duct static pressure reset (GL36 §5.1.14.4)</li>
          <li>AHU supply air temperature reset (GL36 trim &amp; respond)</li>
          <li>VAV zone request generators (cooling + pressure)</li>
          <li>Chilled / hot water plant trim &amp; respond</li>
        </ul>
        <p className="muted">
          Draft patterns and doc-only Python stubs live in the repo docs:{" "}
          <a
            href="https://github.com/bbartling/open-fdd/blob/develop/docs/operator-bridge/algorithms.md"
            target="_blank"
            rel="noreferrer"
          >
            docs/operator-bridge/algorithms.md
          </a>
          . Reference Niagara GL36 blocks:{" "}
          <a
            href="https://github.com/bbartling/niagara4-vibe-code-addict/blob/develop/README_TRIM_RESPOND.md"
            target="_blank"
            rel="noreferrer"
          >
            README_TRIM_RESPOND
          </a>
          .
        </p>
        <p className="muted">
          Until this tab ships, use <a href="/rule-lab">Rule Lab</a> for fault detection and{" "}
          <a href="/model">Model &amp; assignments</a> for point bindings.
        </p>
      </div>
    </div>
  );
}
