export const SIMPLE_COMPLEX_POLICY_PRESET = `{
  "OFDD_OPENCLAW_ROUTE_SIMPLE_AGENT": "simple",
  "OFDD_OPENCLAW_ROUTE_COMPLEX_AGENT": "complex",
  "OFDD_OPENCLAW_ROUTE_SIMPLE_BACKEND_MODEL": "openai-codex/gpt-5.5",
  "OFDD_OPENCLAW_ROUTE_COMPLEX_BACKEND_MODEL": "openai-codex/gpt-5.5",
  "OFDD_OPENCLAW_ROUTE_DEFAULT_CLASS": "simple",
  "OFDD_OPENCLAW_ROUTE_STRICT_MODE": "true"
}`;

export const SECURITY_SAFE_DEFAULTS_PRESET = `{
  "gateway.auth.mode": "token",
  "gateway.auth.token": "set-from-secret-store",
  "gateway.bind": "127.0.0.1",
  "agents.defaults.sandbox.mode": "non-main",
  "ops.note": "Treat gateway token as operator secret; keep private ingress only."
}`;

export const PHASE2_CRON_STRICT_PRESET = `{
  "failureDestination": "ops-alerts",
  "alertOnSkipped": true,
  "idempotencyKey": "open-fdd-site-sweep-v1",
  "reconcileTag": "portfolio-default",
  "correlationIdPrefix": "ofdd"
}`;

export const PHASE2_CRON_RELAXED_PRESET = `{
  "failureDestination": "",
  "alertOnSkipped": false,
  "idempotencyKey": "",
  "reconcileTag": "ad-hoc",
  "correlationIdPrefix": "ofdd"
}`;

export const PHASE3_MEMORY_GOVERNANCE_PRESET = `{
  "memoryProfile": {
    "durableFacts": ["equipment_inventory", "controls_topology", "known_quirks_with_evidence"],
    "dailyNotes": ["incidents", "alarms", "maintenance_actions"],
    "claimFreshnessDays": 30,
    "contradictionHandling": "require-evidence-link"
  }
}`;

export const PHASE3_SUBAGENT_LANES_PRESET = `{
  "OFDD_OPENCLAW_ROUTE_SIMPLE_LANES": "simple-1,simple-2",
  "OFDD_OPENCLAW_ROUTE_COMPLEX_LANES": "complex-1,complex-2",
  "routingKey": "site_id"
}`;

