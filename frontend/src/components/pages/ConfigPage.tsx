"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Settings, Save, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { JsonPrettyPanel } from "@/components/ui/json-pretty-panel";
import { getConfig, putConfig } from "@/lib/crud-api";
import type { PlatformConfig } from "@/types/api";

const inputClass =
  "h-9 w-full rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass = "mb-1 block text-xs font-medium text-muted-foreground";

function ConfigField({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  min,
  max,
  step,
  "data-testid": testId,
}: {
  label: string;
  value: string | number;
  onChange: (v: string | number) => void;
  type?: "text" | "number";
  placeholder?: string;
  min?: number;
  max?: number;
  step?: number;
  "data-testid"?: string;
}) {
  return (
    <div>
      <label className={labelClass}>{label}</label>
      <input
        type={type}
        value={value ?? ""}
        onChange={(e) =>
          onChange(type === "number" ? (e.target.value === "" ? 0 : Number(e.target.value)) : e.target.value)
        }
        placeholder={placeholder}
        min={min}
        max={max}
        step={step}
        className={inputClass}
        data-testid={testId}
      />
    </div>
  );
}

function ConfigSwitch({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 rounded border-border"
      />
      <span className="text-sm text-foreground">{label}</span>
    </label>
  );
}

function formatConfigValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "On" : "Off";
  if (typeof v === "string" && v.length > 48) return `${v.slice(0, 45)}…`;
  return String(v);
}

function ConfigSummary({ config }: { config: PlatformConfig }) {
  return (
    <Card className="mb-6 border-dashed">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Current settings (active)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
          <span className="col-span-full mt-1 border-b border-border/60 pb-1 font-medium text-muted-foreground">FDD</span>
          <dt className="text-muted-foreground">Rule interval (hours)</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.rule_interval_hours)}</dd>
          <dt className="text-muted-foreground">Lookback (days)</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.lookback_days)}</dd>
          <dt className="text-muted-foreground">Rules dir</dt>
          <dd className="truncate font-mono text-foreground" title={String(config.rules_dir ?? "")}>{formatConfigValue(config.rules_dir)}</dd>
          <dt className="text-muted-foreground">Brick TTL dir</dt>
          <dd className="truncate font-mono text-foreground" title={String(config.brick_ttl_dir ?? "")}>{formatConfigValue(config.brick_ttl_dir)}</dd>

          <span className="col-span-full mt-2 border-b border-border/60 pb-1 font-medium text-muted-foreground">BACnet</span>
          <dt className="text-muted-foreground">Enabled</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.bacnet_enabled)}</dd>
          <dt className="text-muted-foreground">Scrape interval (min)</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.bacnet_scrape_interval_min)}</dd>
          <dt className="text-muted-foreground">Server URL</dt>
          <dd className="truncate font-mono text-foreground" title={String(config.bacnet_server_url ?? "")}>{formatConfigValue(config.bacnet_server_url)}</dd>
          <dt className="text-muted-foreground">Site ID</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.bacnet_site_id)}</dd>
          <dt className="text-muted-foreground">Gateways</dt>
          <dd className="truncate font-mono text-foreground" title={String(config.bacnet_gateways ?? "")}>{formatConfigValue(config.bacnet_gateways)}</dd>

          <span className="col-span-full mt-2 border-b border-border/60 pb-1 font-medium text-muted-foreground">Open-Meteo</span>
          <dt className="text-muted-foreground">Enabled</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.open_meteo_enabled)}</dd>
          <dt className="text-muted-foreground">Interval (h, standalone)</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.open_meteo_interval_hours)}</dd>
          <dt className="text-muted-foreground">Latitude</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.open_meteo_latitude)}</dd>
          <dt className="text-muted-foreground">Longitude</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.open_meteo_longitude)}</dd>
          <dt className="text-muted-foreground">Timezone</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.open_meteo_timezone)}</dd>
          <dt className="text-muted-foreground">Days back (standalone)</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.open_meteo_days_back)}</dd>
          <dt className="text-muted-foreground">Site ID</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.open_meteo_site_id)}</dd>

          <span className="col-span-full mt-2 border-b border-border/60 pb-1 font-medium text-muted-foreground">Graph</span>
          <dt className="text-muted-foreground">Sync interval (min)</dt>
          <dd className="font-mono text-foreground">{formatConfigValue(config.graph_sync_interval_min)}</dd>
        </dl>
        <details className="group">
          <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">Raw JSON</summary>
          <div className="mt-2">
            <JsonPrettyPanel value={config} maxHeightClass="max-h-72" defaultExpandDepth={1} />
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

export function ConfigPage() {
  const queryClient = useQueryClient();
  const { data: config, isLoading } = useQuery<PlatformConfig>({
    queryKey: ["config"],
    queryFn: getConfig,
  });

  const [form, setForm] = useState<PlatformConfig>({});
  const [saveStatus, setSaveStatus] = useState<"idle" | "success" | "error">("idle");
  useEffect(() => {
    if (config && typeof config === "object") {
      const normalized: PlatformConfig = { ...config };
      if (normalized.rule_interval_hours === 0 || normalized.rule_interval_hours == null) {
        normalized.rule_interval_hours = 3;
      }
      // eslint-disable-next-line react-hooks/set-state-in-effect -- sync GET /config into form when loaded/refetched
      setForm(normalized);
    }
  }, [config]);

  const update = (key: keyof PlatformConfig, value: string | number | boolean | null) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const putMutation = useMutation<PlatformConfig, Error, Partial<PlatformConfig>>({
    mutationFn: putConfig,
    onSuccess: (data) => {
      setForm({ ...data });
      setSaveStatus("success");
      queryClient.invalidateQueries({ queryKey: ["config"] });
      setTimeout(() => setSaveStatus("idle"), 2000);
    },
    onError: () => setSaveStatus("error"),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    putMutation.mutate(form);
  };

  if (isLoading || !config) {
    return (
      <div>
        <h1 className="mb-6 text-2xl font-semibold tracking-tight">OpenFDD Config</h1>
        <div className="h-72 animate-pulse rounded-2xl bg-muted/50" />
      </div>
    );
  }

  return (
    <div>
      <h1 className="mb-6 flex items-center gap-2 text-2xl font-semibold tracking-tight">
        <Settings className="h-7 w-7" />
        OpenFDD Config
      </h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Platform settings stored in the knowledge graph. Changes take effect on the next FDD run or scraper cycle.
      </p>

      {/* Current settings summary (read-only, grouped) */}
      <ConfigSummary config={config} />

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* FDD rules */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">FDD rules</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <ConfigField
              label="Rule interval (hours)"
              type="number"
              value={form.rule_interval_hours ?? 3}
              onChange={(v) => update("rule_interval_hours", Number(v))}
              min={0}
              step={0.1}
              placeholder="3"
            />
            <ConfigField
              label="Lookback (days)"
              type="number"
              value={form.lookback_days ?? 0}
              onChange={(v) => update("lookback_days", Number(v))}
              min={0}
            />
            <ConfigField
              label="Rules directory"
              value={form.rules_dir ?? ""}
              onChange={(v) => update("rules_dir", String(v))}
              placeholder="stack/rules"
            />
            <ConfigField
              label="Brick TTL directory"
              value={form.brick_ttl_dir ?? ""}
              onChange={(v) => update("brick_ttl_dir", String(v))}
              placeholder="config"
            />
          </CardContent>
        </Card>

        {/* BACnet */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">BACnet</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <ConfigSwitch
                label="BACnet enabled"
                checked={form.bacnet_enabled ?? true}
                onChange={(v) => update("bacnet_enabled", v)}
              />
            </div>
            <ConfigField
              label="Scrape interval (min)"
              type="number"
              value={form.bacnet_scrape_interval_min ?? 1}
              onChange={(v) => update("bacnet_scrape_interval_min", Number(v))}
              min={0}
              data-testid="config-bacnet-scrape-interval"
            />
            <ConfigField
              label="BACnet server URL"
              value={form.bacnet_server_url ?? ""}
              onChange={(v) => update("bacnet_server_url", String(v))}
              placeholder="http://localhost:8080"
            />
          </CardContent>
        </Card>

        {/* Open-Meteo */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Open-Meteo (weather)</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <ConfigSwitch
                label="Open-Meteo enabled"
                checked={form.open_meteo_enabled ?? true}
                onChange={(v) => update("open_meteo_enabled", v)}
              />
            </div>
            <p className="sm:col-span-2 text-sm text-muted-foreground">
              Weather is fetched with each FDD run (same as rule interval above; 1-day lookback). Standalone scraper uses &quot;Days back&quot; and its own interval. Units: °F, mph, %, W/m².
            </p>
            <ConfigField
              label="Latitude"
              type="number"
              value={form.open_meteo_latitude ?? 0}
              onChange={(v) => update("open_meteo_latitude", Number(v))}
              step={0.01}
            />
            <ConfigField
              label="Longitude"
              type="number"
              value={form.open_meteo_longitude ?? 0}
              onChange={(v) => update("open_meteo_longitude", Number(v))}
              step={0.01}
            />
            <ConfigField
              label="Timezone"
              value={form.open_meteo_timezone ?? ""}
              onChange={(v) => update("open_meteo_timezone", String(v))}
              placeholder="America/Chicago"
            />
            <ConfigField
              label="Days back (standalone scraper only)"
              type="number"
              value={form.open_meteo_days_back ?? 3}
              onChange={(v) => update("open_meteo_days_back", Number(v))}
              min={0}
            />
            <ConfigField
              label="Open-Meteo site ID"
              value={form.open_meteo_site_id ?? ""}
              onChange={(v) => update("open_meteo_site_id", String(v))}
              placeholder="default"
            />
          </CardContent>
        </Card>

        {/* Graph */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Graph sync</CardTitle>
          </CardHeader>
          <CardContent>
            <ConfigField
              label="Graph sync to TTL (minutes)"
              type="number"
              value={form.graph_sync_interval_min ?? 5}
              onChange={(v) => update("graph_sync_interval_min", Number(v))}
              min={0}
            />
          </CardContent>
        </Card>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={putMutation.isPending}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
            data-testid="config-save-button"
          >
            {putMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            Save config
          </button>
          {saveStatus === "success" && (
            <span className="text-sm text-green-600 dark:text-green-400">Saved. Config written to RDF + TTL.</span>
          )}
          {saveStatus === "error" && (
            <span className="text-sm text-destructive">{putMutation.error?.message ?? "Save failed."}</span>
          )}
        </div>
      </form>
    </div>
  );
}
