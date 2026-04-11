export function AnalyticsPage() {
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Analytics</h1>
      <p className="mb-4 max-w-2xl text-sm text-muted-foreground">
        Trend dashboards, fault-duration rollups, and M&amp;V-style reporting will land here in a future release. For
        now, use <strong>Energy Engineering</strong> to capture site-specific savings assumptions (stored per building
        and exported to the knowledge graph).
      </p>
      <p className="text-sm text-muted-foreground">
        TODO: interval-integrated analytics tied to points and fault history.
      </p>
    </div>
  );
}
