import { useState } from "react";
import { ChevronDown, ChevronRight, CheckCircle2, XCircle, AlertCircle } from "lucide-react";
import { JsonPrettyPanel } from "@/components/ui/json-pretty-panel";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

function isRecord(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

/** Open-FDD proxy envelope or ad-hoc error payload */
function getBody(data: Record<string, unknown>): unknown {
  if ("body" in data && data.body !== undefined) return data.body;
  return null;
}

/** Inner JSON-RPC payload: { jsonrpc, id, result? | error? } */
function extractRpcPayload(body: unknown): {
  result: unknown;
  rpcError: { code?: number; message?: string; data?: unknown } | null;
} {
  if (!isRecord(body)) return { result: body, rpcError: null };
  if (body.error != null && isRecord(body.error)) {
    const e = body.error as Record<string, unknown>;
    return {
      result: null,
      rpcError: {
        code: typeof e.code === "number" ? e.code : undefined,
        message: typeof e.message === "string" ? e.message : String(e.message ?? "Error"),
        data: e.data,
      },
    };
  }
  if ("result" in body) return { result: body.result, rpcError: null };
  return { result: body, rpcError: null };
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number" || typeof v === "string") return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/** BACnet object-type enum (common HVAC subset) → hyphenated id */
const BACNET_OBJECT_TYPE_NAMES: Record<number, string> = {
  0: "analog-input",
  1: "analog-output",
  2: "analog-value",
  3: "binary-input",
  4: "binary-output",
  5: "binary-value",
  13: "multi-state-input",
  14: "multi-state-output",
  19: "multi-state-value",
  23: "loop",
};

/** Property identifier enum (subset); 85 = present-value per ASHRAE 135 */
const BACNET_PROPERTY_NAMES: Record<number, string> = {
  85: "present-value",
  87: "priority-array",
  117: "relinquish-default",
};

function formatBacnetObjectIdentifier(v: unknown): string {
  if (typeof v === "string") return v;
  if (Array.isArray(v) && v.length >= 2 && typeof v[0] === "number" && typeof v[1] === "number") {
    const typeName = BACNET_OBJECT_TYPE_NAMES[v[0]] ?? `type-${v[0]}`;
    return `${typeName},${v[1]}`;
  }
  return formatCell(v);
}

function formatBacnetPropertyIdentifier(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "number") {
    const name = BACNET_PROPERTY_NAMES[v];
    return name ? `${name} (${v})` : `property ${v}`;
  }
  return formatCell(v);
}

function formatRpmRowValue(row: Record<string, unknown>): string {
  const parts: string[] = [];
  if ("value" in row) {
    parts.push(`value: ${formatCell(row.value)}`);
  }
  if ("property_array_index" in row && row.property_array_index != null) {
    parts.push(`index: ${formatCell(row.property_array_index)}`);
  }
  return parts.length > 0 ? parts.join(" · ") : formatCell(row);
}

function isPriorityArrayRow(x: unknown): x is {
  priority_level: number;
  type: string;
  value: unknown;
} {
  return (
    isRecord(x) &&
    typeof x.priority_level === "number" &&
    typeof x.type === "string" &&
    "value" in x
  );
}

function isRpmResultRow(x: unknown): x is Record<string, unknown> {
  if (!isRecord(x)) return false;
  return (
    ("object_identifier" in x && "property_identifier" in x) ||
    ("objectIdentifier" in x && "propertyIdentifier" in x)
  );
}

/** diy BaseResponse shape: { success, message, data? } */
function isBaseResponse(r: unknown): r is { success: boolean; message: string; data?: unknown } {
  return (
    isRecord(r) &&
    typeof r.success === "boolean" &&
    typeof r.message === "string"
  );
}

/** Supervisory summary from client_supervisory_logic_checks */
function isSupervisorySummary(r: unknown): r is {
  device_id: number;
  address?: string | null;
  points: unknown[];
  summary: Record<string, number>;
} {
  return (
    isRecord(r) &&
    typeof r.device_id === "number" &&
    Array.isArray(r.points) &&
    isRecord(r.summary)
  );
}

/** Supervisory logic per-point row (client_supervisory_logic_checks). */
function isSupervisoryPointDetail(p: unknown): p is {
  priority_level: number;
  object_identifier: string;
  object_name?: unknown;
  type: string;
  value: unknown;
} {
  return (
    isRecord(p) &&
    typeof p.priority_level === "number" &&
    typeof p.object_identifier === "string" &&
    typeof p.type === "string" &&
    "value" in p
  );
}

function KeyValueGrid({ obj }: { obj: Record<string, unknown> }) {
  const entries = Object.entries(obj).filter(([, v]) => v !== undefined);
  if (entries.length === 0) return <p className="text-sm text-muted-foreground">(empty object)</p>;
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
      {entries.map(([k, v]) => (
        <div key={k} className="flex flex-wrap items-baseline gap-2 border-b border-border/40 py-1.5 last:border-0">
          <dt className="min-w-[8rem] font-mono text-xs text-muted-foreground">{k}</dt>
          <dd className="text-sm font-medium text-foreground break-all">{formatCell(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function PrettyResultCore({ result }: { result: unknown }) {
  if (result === null || result === undefined) {
    return <p className="text-sm text-muted-foreground">No result payload</p>;
  }

  if (Array.isArray(result)) {
    if (result.length > 0 && result.every(isPriorityArrayRow)) {
      return (
        <div className="rounded-lg border border-border/60 bg-card/50">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-24 text-xs">Priority</TableHead>
                <TableHead className="text-xs">Type</TableHead>
                <TableHead className="text-xs">Value</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {result.map((row, i) => (
                <TableRow key={i}>
                  <TableCell className="font-mono text-sm font-medium tabular-nums">
                    {row.priority_level}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{row.type}</TableCell>
                  <TableCell className="font-mono text-sm">
                    {Array.isArray(row.value) && row.value.length === 0
                      ? "—"
                      : formatCell(row.value)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      );
    }
    if (result.length > 0 && result.every((x) => x === null || typeof x !== "object")) {
      return (
        <div className="rounded-lg border border-border/60 bg-card/50">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">Priority</TableHead>
                <TableHead>Value</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {result.map((v, i) => (
                <TableRow key={i}>
                  <TableCell className="font-mono text-xs text-muted-foreground">{i + 1}</TableCell>
                  <TableCell className="font-mono text-sm">{formatCell(v)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      );
    }
    return (
      <ul className="max-h-48 list-inside list-decimal space-y-1 overflow-auto text-sm">
        {result.map((item, i) => (
          <li key={i} className="font-mono text-xs break-all">
            {formatCell(item)}
          </li>
        ))}
      </ul>
    );
  }

  if (isSupervisorySummary(result)) {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap gap-4 text-sm">
          <span>
            <span className="text-muted-foreground">Device </span>
            <span className="font-mono font-semibold">{result.device_id}</span>
          </span>
          {result.address != null && result.address !== "" && (
            <span>
              <span className="text-muted-foreground">Address </span>
              <span className="font-mono">{result.address}</span>
            </span>
          )}
        </div>
        {Object.keys(result.summary).length > 0 && (
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">Summary</p>
            <KeyValueGrid obj={result.summary as Record<string, unknown>} />
          </div>
        )}
        {result.points.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">
              Points ({result.points.length})
            </p>
            <div className="overflow-x-auto rounded-lg border border-border/60">
              {result.points.every(isSupervisoryPointDetail) ? (
                <div className="max-h-72 overflow-y-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-14 font-mono text-xs">Prio</TableHead>
                        <TableHead className="font-mono text-xs">object_identifier</TableHead>
                        <TableHead className="text-xs">name</TableHead>
                        <TableHead className="w-24 text-xs">type</TableHead>
                        <TableHead className="text-xs">value</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {result.points.slice(0, 50).map((p, i) => (
                        <TableRow key={i}>
                          <TableCell className="font-mono text-xs tabular-nums text-muted-foreground">
                            {p.priority_level}
                          </TableCell>
                          <TableCell className="font-mono text-xs">{p.object_identifier}</TableCell>
                          <TableCell className="text-xs">
                            {typeof p.object_name === "string" ? p.object_name : formatCell(p.object_name)}
                          </TableCell>
                          <TableCell className="font-mono text-xs text-muted-foreground">{p.type}</TableCell>
                          <TableCell className="font-mono text-sm tabular-nums">{formatCell(p.value)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <div className="max-h-56 overflow-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-xs">Details</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {result.points.slice(0, 50).map((p, i) => (
                        <TableRow key={i}>
                          <TableCell className="font-mono text-xs break-all">
                            {isRecord(p) ? formatCell(p) : String(p)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
            {result.points.length > 50 && (
              <p className="p-2 text-xs text-muted-foreground">Showing first 50 of {result.points.length}</p>
            )}
          </div>
        )}
      </div>
    );
  }

  if (isBaseResponse(result)) {
    const data = result.data;
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
              result.success
                ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
                : "bg-destructive/15 text-destructive"
            }`}
          >
            {result.success ? <CheckCircle2 className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}
            {result.success ? "Success" : "Failed"}
          </span>
          <span className="text-sm text-foreground">{result.message}</span>
        </div>
        {data != null && isRecord(data) && data.results != null && Array.isArray(data.results) && (
          <div>
            <div className="overflow-x-auto rounded-lg border border-border/60">
              <p className="mb-0 border-b border-border/60 px-2 py-1.5 text-xs font-medium text-muted-foreground">
                Readings ({(data.results as unknown[]).length})
              </p>
              <div className="max-h-72 overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10 font-mono text-xs">#</TableHead>
                    <TableHead className="font-mono text-xs">object</TableHead>
                    <TableHead className="font-mono text-xs">property</TableHead>
                    <TableHead className="text-xs">reading</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data.results as unknown[]).map((cell, i) => {
                    if (isRpmResultRow(cell)) {
                      const oid = cell.object_identifier ?? cell.objectIdentifier;
                      const pid = cell.property_identifier ?? cell.propertyIdentifier;
                      return (
                        <TableRow key={i}>
                          <TableCell className="font-mono text-xs text-muted-foreground tabular-nums">
                            {i}
                          </TableCell>
                          <TableCell className="font-mono text-xs">{formatBacnetObjectIdentifier(oid)}</TableCell>
                          <TableCell className="font-mono text-xs">{formatBacnetPropertyIdentifier(pid)}</TableCell>
                          <TableCell className="max-w-[min(28rem,50vw)] font-mono text-xs break-all">
                            {formatRpmRowValue(cell)}
                          </TableCell>
                        </TableRow>
                      );
                    }
                    return (
                      <TableRow key={i}>
                        <TableCell className="font-mono text-xs text-muted-foreground">{i}</TableCell>
                        <TableCell colSpan={3} className="font-mono text-xs break-all">
                          {formatCell(cell)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              </div>
            </div>
          </div>
        )}
        {data != null && isRecord(data) && data.devices != null && Array.isArray(data.devices) && (
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">Devices</p>
            <div className="max-h-56 overflow-auto rounded-lg border border-border/60">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-xs">i-am-device-identifier</TableHead>
                    <TableHead className="text-xs">device-address</TableHead>
                    <TableHead className="text-xs">description</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data.devices as Record<string, unknown>[]).slice(0, 30).map((d, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-mono text-xs">
                        {formatCell(d["i-am-device-identifier"])}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {formatCell(d["device-address"])}
                      </TableCell>
                      <TableCell className="text-xs">{formatCell(d["device-description"])}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
        {data != null && isRecord(data) && data.objects != null && Array.isArray(data.objects) && (
          <div>
            <p className="mb-2 text-xs font-medium text-muted-foreground">Objects</p>
            <div className="max-h-56 overflow-auto rounded-lg border border-border/60">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-xs">object_identifier</TableHead>
                    <TableHead className="text-xs">name</TableHead>
                    <TableHead className="text-xs">commandable</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data.objects as Record<string, unknown>[]).slice(0, 40).map((o, i) => (
                    <TableRow key={i}>
                      <TableCell className="font-mono text-xs">{formatCell(o.object_identifier)}</TableCell>
                      <TableCell className="text-xs">{formatCell(o.name ?? o.object_name)}</TableCell>
                      <TableCell className="text-xs">{formatCell(o.commandable)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}
        {data != null &&
          !(Array.isArray((data as { results?: unknown }).results)) &&
          !(Array.isArray((data as { devices?: unknown }).devices)) &&
          !(Array.isArray((data as { objects?: unknown }).objects)) &&
          isRecord(data) && <KeyValueGrid obj={data as Record<string, unknown>} />}
        {data != null && !isRecord(data) && (
          <JsonPrettyPanel value={data} maxHeightClass="max-h-40" showCopy={false} compact />
        )}
      </div>
    );
  }

  if (isRecord(result)) {
    return <KeyValueGrid obj={result} />;
  }

  return (
    <JsonPrettyPanel value={result} maxHeightClass="max-h-48" showCopy={false} compact />
  );
}

type EnvelopeProps = {
  label: string;
  data: Record<string, unknown>;
  testId?: string;
};

/**
 * Pretty view for Open-FDD /bacnet/* proxy responses: unwrap JSON-RPC, format BaseResponse / tables, collapsible raw JSON.
 */
export function BacnetProxyEnvelopeView({ label, data, testId }: EnvelopeProps) {
  const [rawOpen, setRawOpen] = useState(false);

  const ok = data.ok === true;
  const statusCode = typeof data.status_code === "number" ? data.status_code : null;
  const topError = typeof data.error === "string" ? data.error : null;
  const text = typeof data.text === "string" ? data.text : null;
  const body = getBody(data);
  const { result, rpcError } = extractRpcPayload(body);

  return (
    <div
      className="mt-3 rounded-lg border border-border/60 bg-card/40 p-4"
      data-testid={testId ?? `bacnet-result-${label.replace(/\s+/g, "-").toLowerCase()}`}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        {statusCode != null && (
          <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
            HTTP {statusCode}
          </span>
        )}
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
            ok
              ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
              : "bg-destructive/15 text-destructive"
          }`}
        >
          {ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertCircle className="h-3.5 w-3.5" />}
          {ok ? "Gateway OK" : "Gateway error"}
        </span>
      </div>

      {topError && (
        <p className="mb-2 text-sm text-destructive">{topError}</p>
      )}
      {text && !ok && (
        <pre className="mb-2 max-h-32 overflow-auto rounded border border-destructive/30 bg-destructive/5 p-2 text-xs whitespace-pre-wrap break-all">
          {text}
        </pre>
      )}

      {rpcError && (
        <div className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
          <p className="font-medium text-amber-900 dark:text-amber-200">JSON-RPC error</p>
          {rpcError.code != null && (
            <p className="mt-1 font-mono text-xs text-muted-foreground">code: {rpcError.code}</p>
          )}
          <p className="mt-1">{rpcError.message}</p>
          {rpcError.data != null &&
            (typeof rpcError.data === "object" ? (
              <div className="mt-2">
                <JsonPrettyPanel value={rpcError.data} maxHeightClass="max-h-32" showCopy={false} compact />
              </div>
            ) : (
              <pre className="mt-2 max-h-32 overflow-auto rounded bg-background/50 p-2 text-xs whitespace-pre-wrap break-all">
                {formatCell(rpcError.data)}
              </pre>
            ))}
        </div>
      )}

      {!rpcError && (ok || result != null) && (
        <div className="rounded-lg border border-border/40 bg-background/50 p-3">
          <PrettyResultCore result={result} />
        </div>
      )}

      <button
        type="button"
        onClick={() => setRawOpen((o) => !o)}
        className="mt-3 flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
      >
        {rawOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        Raw response
      </button>
      {rawOpen && (
        <div className="mt-2">
          <JsonPrettyPanel value={data} maxHeightClass="max-h-64" defaultExpandDepth={1} />
        </div>
      )}
    </div>
  );
}
