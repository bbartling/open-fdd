import PageHeader from "../components/PageHeader";

export default function AgentPage() {
  return (
    <div className="page page-wide">
      <PageHeader
        title="AI Agent"
        subtitle="Ollama chat, Codex tools, and building-insight narratives — planned for a future release."
      />

      <div className="panel algorithms-coming-soon">
        <p className="algorithms-badge">COMING SOON</p>
        <h2>Interactive agent tab</h2>
        <p className="muted">
          This tab will host local Ollama chat, tool use against the Haystack model and historian, and optional
          Codex-assisted commissioning. The Rust edge already exposes agent REST hooks for automation; operator chat
          UI is not enabled in this build.
        </p>
        <ul>
          <li>Building context from Haystack + SQL FDD rules</li>
          <li>Commissioning JSON assist (import/export workflow)</li>
          <li>Fault narrative and operator Q&amp;A</li>
        </ul>
        <p className="muted">
          Use <a href="/sql-fdd">SQL FDD Rules</a> and{" "}
          <a href="/live-fdd-validation">Live FDD Validation</a> for bench proof today.
        </p>
      </div>
    </div>
  );
}
