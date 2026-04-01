import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Network, Loader2, Wrench, Plus, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BacnetDiscoveryPanel } from "@/components/site/BacnetDiscoveryPanel";
import {
  bacnetGateways,
  bacnetReadProperty,
  bacnetReadMultiple,
  bacnetWriteProperty,
  bacnetSupervisoryLogicChecks,
  bacnetReadPointPriorityArray,
  type BacnetGatewayRow,
  type BacnetProxyResult,
} from "@/lib/crud-api";
import { BacnetProxyResultView } from "@/components/bacnet/BacnetProxyResultView";

/** Match BACnet discovery panel field styling */
const bnField =
  "h-9 rounded-lg border border-border/60 bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring";
const bnMono = `${bnField} font-mono text-xs`;

type RpmRow = { object_identifier: string; property_identifier: string };

function GatewaySelect({
  gateways,
  value,
  onChange,
}: {
  gateways: BacnetGatewayRow[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="mb-4">
      <label className="mb-1 block text-xs font-medium text-muted-foreground">Gateway</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`${bnField} max-w-md`}
        data-testid="bacnet-tools-gateway-select"
      >
        {gateways.map((g) => (
          <option key={g.id} value={g.id}>
            {g.id} — {g.description ?? g.url}
          </option>
        ))}
      </select>
    </div>
  );
}

export function BacnetToolsPage() {
  const { data: gateways = [] } = useQuery({
    queryKey: ["bacnet", "gateways"],
    queryFn: bacnetGateways,
  });
  const [gateway, setGateway] = useState("default");

  const [readDev, setReadDev] = useState(3456789);
  const [readObj, setReadObj] = useState("analog-output,1");
  const [readProp, setReadProp] = useState("present-value");
  const [readRes, setReadRes] = useState<BacnetProxyResult | null>(null);

  const [rmDev, setRmDev] = useState(3456789);
  const [rmRows, setRmRows] = useState<RpmRow[]>([
    { object_identifier: "analog-input,2", property_identifier: "present-value" },
  ]);
  const [rmRes, setRmRes] = useState<BacnetProxyResult | null>(null);

  const [wDev, setWDev] = useState(3456789);
  const [wObj, setWObj] = useState("analog-output,1");
  const [wProp, setWProp] = useState("present-value");
  const [wVal, setWVal] = useState("72.5");
  const [wPri, setWPri] = useState("8");
  const [wReleaseNull, setWReleaseNull] = useState(false);
  const [wRes, setWRes] = useState<BacnetProxyResult | null>(null);

  const [supDev, setSupDev] = useState(3456789);
  const [supRes, setSupRes] = useState<BacnetProxyResult | null>(null);

  const [paDev, setPaDev] = useState(3456789);
  const [paObj, setPaObj] = useState("analog-output,1");
  const [paRes, setPaRes] = useState<BacnetProxyResult | null>(null);

  const readMut = useMutation({
    mutationFn: () =>
      bacnetReadProperty(
        {
          request: {
            device_instance: readDev,
            object_identifier: readObj.trim(),
            property_identifier: readProp.trim() || "present-value",
          },
        },
        gateway,
      ),
    onSuccess: (d) => setReadRes(d as BacnetProxyResult),
  });

  const rmMut = useMutation({
    mutationFn: () => {
      const requests = rmRows
        .map((r) => ({
          object_identifier: r.object_identifier.trim(),
          property_identifier: r.property_identifier.trim() || "present-value",
        }))
        .filter((r) => r.object_identifier.length > 0);
      if (requests.length === 0) {
        return Promise.reject(new Error("Add at least one object id + property."));
      }
      return bacnetReadMultiple({ request: { device_instance: rmDev, requests } }, gateway);
    },
    onSuccess: (d) => setRmRes(d as BacnetProxyResult),
    onError: (e: Error) => setRmRes({ ok: false, error: e.message }),
  });

  const writeMut = useMutation({
    mutationFn: () => {
      const pr = Number(wPri);
      if (!Number.isFinite(pr) || pr < 1 || pr > 16) {
        return Promise.reject(new Error("Priority must be 1–16 for every write or release."));
      }
      let value: string | number | null;
      if (wReleaseNull) {
        value = null;
      } else {
        const raw = wVal.trim();
        if (!raw) {
          return Promise.reject(new Error("Enter a numeric value or enable “Release (null) at priority”."));
        }
        if (!Number.isNaN(Number(raw)) && /^-?\d*\.?\d+$/.test(raw)) {
          value = Number(raw);
        } else {
          value = raw;
        }
      }
      return bacnetWriteProperty(
        {
          request: {
            device_instance: wDev,
            object_identifier: wObj.trim(),
            property_identifier: wProp.trim() || "present-value",
            value,
            priority: pr,
          },
        },
        gateway,
      );
    },
    onSuccess: (d) => setWRes(d as BacnetProxyResult),
    onError: (e: Error) => setWRes({ ok: false, error: e.message }),
  });

  const supMut = useMutation({
    mutationFn: () =>
      bacnetSupervisoryLogicChecks({ instance: { device_instance: supDev } }, gateway),
    onSuccess: (d) => setSupRes(d as BacnetProxyResult),
  });

  const paMut = useMutation({
    mutationFn: () =>
      bacnetReadPointPriorityArray(
        {
          request: {
            device_instance: paDev,
            object_identifier: paObj.trim(),
          },
        },
        gateway,
      ),
    onSuccess: (d) => setPaRes(d as BacnetProxyResult),
  });

  return (
    <div>
      <h1 className="mb-2 text-2xl font-semibold tracking-tight" data-testid="bacnet-tools-heading">
        BACnet tools
      </h1>
      <p className="mb-6 max-w-3xl text-sm text-muted-foreground">
        Run discovery, reads, writes, and diagnostics through Open-FDD (same login as the rest of the app). The gateway API
        key stays on the server. After you build the graph, continue in{" "}
        <Link to="/data-model" className="font-medium text-primary underline-offset-4 hover:underline">
          Data Model BRICK
        </Link>
        .
      </p>

      {gateways.length > 0 && (
        <GatewaySelect gateways={gateways} value={gateway} onChange={setGateway} />
      )}

      <BacnetDiscoveryPanel />

      <Card className="mt-6">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Wrench className="h-5 w-5" />
            Read property
          </CardTitle>
          <p className="text-sm font-normal text-muted-foreground">
            Single object/property (JSON-RPC <code className="rounded bg-muted px-1 text-xs">client_read_property</code>).
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Device instance</label>
              <input
                type="number"
                className={`${bnField} w-32`}
                value={readDev}
                onChange={(e) => setReadDev(Number(e.target.value) || 0)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Object id</label>
              <input className={`${bnMono} w-44`} value={readObj} onChange={(e) => setReadObj(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Property</label>
              <input className={`${bnMono} w-40`} value={readProp} onChange={(e) => setReadProp(e.target.value)} />
            </div>
            <button
              type="button"
              onClick={() => readMut.mutate()}
              disabled={readMut.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              data-testid="bacnet-read-property-run"
            >
              {readMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Network className="h-4 w-4" />}
              Run
            </button>
          </div>
          <BacnetProxyResultView label="read_property" data={readRes} />
        </CardContent>
      </Card>

      <Card className="mt-6">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg">Read multiple (RPM)</CardTitle>
          <p className="text-sm font-normal text-muted-foreground">
            One device, many reads — same pattern as discovery above. Results appear below after <strong>Run</strong>.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Device instance</label>
              <input
                type="number"
                min={0}
                max={4194303}
                className={`${bnField} w-32`}
                value={rmDev}
                onChange={(e) => setRmDev(Number(e.target.value) || 0)}
              />
            </div>
            <button
              type="button"
              onClick={() => rmMut.mutate()}
              disabled={rmMut.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              data-testid="bacnet-read-multiple-run"
            >
              {rmMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Network className="h-4 w-4" />}
              Run
            </button>
            <button
              type="button"
              onClick={() =>
                setRmRows((rows) => [
                  ...rows,
                  { object_identifier: "analog-input,1", property_identifier: "present-value" },
                ])
              }
              className="inline-flex h-9 items-center gap-1 rounded-lg border border-border/60 bg-muted/50 px-3 text-sm font-medium transition-colors hover:bg-muted"
            >
              <Plus className="h-4 w-4" />
              Add row
            </button>
          </div>

          <div className="overflow-x-auto rounded-lg border border-border/60">
            <p className="border-b border-border/60 px-2 py-1.5 text-xs font-medium text-muted-foreground">
              Properties to read ({rmRows.length})
            </p>
            <div className="space-y-2 p-3">
              {rmRows.map((row, idx) => (
                <div key={idx} className="flex flex-wrap items-end gap-2">
                  <div className="min-w-0 flex-1">
                    <label className="mb-1 block text-xs font-medium text-muted-foreground">object_identifier</label>
                    <input
                      className={`${bnMono} w-full min-w-[12rem]`}
                      value={row.object_identifier}
                      onChange={(e) => {
                        const v = e.target.value;
                        setRmRows((rows) => rows.map((r, i) => (i === idx ? { ...r, object_identifier: v } : r)));
                      }}
                      data-testid={idx === 0 ? "bacnet-read-multiple-oid-0" : undefined}
                    />
                  </div>
                  <div className="min-w-0 flex-1">
                    <label className="mb-1 block text-xs font-medium text-muted-foreground">property_identifier</label>
                    <input
                      className={`${bnMono} w-full min-w-[10rem]`}
                      value={row.property_identifier}
                      onChange={(e) => {
                        const v = e.target.value;
                        setRmRows((rows) => rows.map((r, i) => (i === idx ? { ...r, property_identifier: v } : r)));
                      }}
                    />
                  </div>
                  <button
                    type="button"
                    disabled={rmRows.length <= 1}
                    onClick={() => setRmRows((rows) => rows.filter((_, i) => i !== idx))}
                    className="inline-flex h-9 items-center gap-1 rounded-lg border border-border/60 px-2 text-sm text-muted-foreground hover:bg-destructive/10 hover:text-destructive disabled:opacity-40"
                    title="Remove row"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          <BacnetProxyResultView label="read_multiple" data={rmRes} />
        </CardContent>
      </Card>

      <Card className="mt-6">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg">Write / release</CardTitle>
          <p className="text-sm font-normal text-muted-foreground">
            BACnet priority <strong>1–16</strong> is required for every call (write and release). Use the checkbox to send
            JSON <code className="rounded bg-muted px-1 text-xs">null</code> and relinquish that priority slot.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Device instance</label>
              <input
                type="number"
                className={`${bnField} w-32`}
                value={wDev}
                onChange={(e) => setWDev(Number(e.target.value) || 0)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Object id</label>
              <input className={`${bnMono} w-44`} value={wObj} onChange={(e) => setWObj(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Property</label>
              <input className={`${bnMono} w-40`} value={wProp} onChange={(e) => setWProp(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Priority (1–16)</label>
              <input
                type="number"
                min={1}
                max={16}
                className={`${bnField} w-20`}
                value={wPri}
                onChange={(e) => setWPri(e.target.value)}
              />
            </div>
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={wReleaseNull}
              onChange={(e) => setWReleaseNull(e.target.checked)}
              className="h-4 w-4 rounded border-border"
            />
            <span>Release (null) at this priority — relinquishes the override at the slot above</span>
          </label>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Value</label>
            <input
              className={`${bnField} w-48`}
              value={wVal}
              onChange={(e) => setWVal(e.target.value)}
              disabled={wReleaseNull}
              placeholder={wReleaseNull ? "— (release)" : "e.g. 72.5"}
            />
          </div>
          <button
            type="button"
            onClick={() => writeMut.mutate()}
            disabled={writeMut.isPending}
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50"
            data-testid="bacnet-write-property-run"
          >
            {writeMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            Run
          </button>
          <BacnetProxyResultView label="write_property" data={wRes} />
        </CardContent>
      </Card>

      <Card className="mt-6">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg">Supervisory logic checks</CardTitle>
          <p className="text-sm font-normal text-muted-foreground">
            Summary and per-point overrides for the device. Results below match the discovery tables layout.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Device instance</label>
              <input
                type="number"
                className={`${bnField} w-32`}
                value={supDev}
                onChange={(e) => setSupDev(Number(e.target.value) || 0)}
              />
            </div>
            <button
              type="button"
              onClick={() => supMut.mutate()}
              disabled={supMut.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              data-testid="bacnet-supervisory-run"
            >
              {supMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Run
            </button>
          </div>
          <BacnetProxyResultView label="supervisory_logic_checks" data={supRes} />
        </CardContent>
      </Card>

      <Card className="mt-6">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg">Read priority array</CardTitle>
          <p className="text-sm font-normal text-muted-foreground">16 BACnet priority slots for a commandable object.</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Device instance</label>
              <input
                type="number"
                className={`${bnField} w-32`}
                value={paDev}
                onChange={(e) => setPaDev(Number(e.target.value) || 0)}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Object id</label>
              <input className={`${bnMono} w-44`} value={paObj} onChange={(e) => setPaObj(e.target.value)} />
            </div>
            <button
              type="button"
              onClick={() => paMut.mutate()}
              disabled={paMut.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
              data-testid="bacnet-priority-array-run"
            >
              {paMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Run
            </button>
          </div>
          <BacnetProxyResultView label="read_point_priority_array" data={paRes} />
        </CardContent>
      </Card>
    </div>
  );
}
