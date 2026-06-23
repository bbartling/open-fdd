import { useCallback, useEffect, useMemo, useState, type MouseEvent } from "react";
import PageHeader from "../components/PageHeader";
import { TabDebugPanel } from "../components/TabDebugPanel";
import FddRulePinMenu, { type RulePinTarget } from "../components/FddRulePinMenu";
import RuleAssignmentMultiSelect from "../components/RuleAssignmentMultiSelect";
import { apiFetch } from "../lib/api";
import { formatApiError } from "../lib/formatApiError";
import {
  fetchAssignments,
  type AssignmentsDevice,
  type AssignmentsPoint,
  type SavedRule,
} from "../lib/ruleBindings";
type SiteRow = { id: string; name: string };

type PinMenu = RulePinTarget & { x: number; y: number };

export default function FddAssignmentsPage() {
  const [sites, setSites] = useState<SiteRow[]>([]);
  const [siteId, setSiteId] = useState("");
  const [deviceKey, setDeviceKey] = useState("");
  const [devices, setDevices] = useState<AssignmentsDevice[]>([]);
  const [points, setPoints] = useState<AssignmentsPoint[]>([]);
  const [rules, setRules] = useState<SavedRule[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [pinMenu, setPinMenu] = useState<PinMenu | null>(null);

  useEffect(() => {
    apiFetch<{ active_site_id?: string; sites: SiteRow[] }>("/api/model/sites")
      .then((res) => {
        const list = res.sites ?? [];
        setSites(list);
        const sid = res.active_site_id || list[0]?.id || "";
        if (sid) setSiteId(sid);
      })
      .catch((e) => setError(formatApiError(e)));
  }, []);

  const loadAssignments = useCallback(async () => {
    if (!siteId) return;
    setLoading(true);
    setError("");
    try {
      const data = await fetchAssignments(siteId);
      setDevices(data.devices ?? []);
      setPoints(data.points ?? []);
      setRules(data.rules ?? []);
      setDeviceKey((prev) => {
        const keys = (data.devices ?? []).map((d) => d.device_key);
        if (prev && keys.includes(prev)) return prev;
        return keys[0] ?? "";
      });
    } catch (e) {
      setError(formatApiError(e));
    } finally {
      setLoading(false);
    }
  }, [siteId]);

  useEffect(() => {
    void loadAssignments();
  }, [loadAssignments, refreshKey]);

  useEffect(() => {
    const onChange = () => setRefreshKey((k) => k + 1);
    window.addEventListener("ofdd-assignments-changed", onChange);
    return () => window.removeEventListener("ofdd-assignments-changed", onChange);
  }, []);

  const activeDevice = useMemo(
    () => devices.find((d) => d.device_key === deviceKey),
    [devices, deviceKey],
  );

  const visiblePoints = useMemo(() => {
    if (!deviceKey) return points;
    return points.filter((p) => p.device_key === deviceKey);
  }, [points, deviceKey]);

  function openPinMenu(e: MouseEvent, point: AssignmentsPoint) {
    e.preventDefault();
    e.stopPropagation();
    setPinMenu({
      kind: "point",
      id: point.point_id,
      label: point.name || point.point_id,
      x: e.clientX,
      y: e.clientY,
    });
  }

  return (
    <div className="page page-wide fdd-assignments-page">
      <PageHeader
        title="FDD assignments"
        subtitle={
          <>
            Map which saved rules run on which BACnet points. Use the multi-select on each row (or right-click for
            the same picker). Rule Lab edits Python only — assignments live here.
          </>
        }
      />
      <TabDebugPanel tab="fdd-assignments" />

      <section className="panel fdd-assign-panel">
        <h3 className="panel-title">Pin rules by device</h3>
        <p className="muted">
          Choose a BACnet device, then use the <strong>Pinned rules</strong> dropdown on each point. Right-click
          still works for the legacy pin menu.
        </p>

        <div className="form-row fdd-assign-filters">
          <div className="field">
            <label className="field-label" htmlFor="fdd-assign-site">
              Site
            </label>
            <select
              id="fdd-assign-site"
              value={siteId}
              disabled={loading || !sites.length}
              onChange={(e) => setSiteId(e.target.value)}
            >
              {sites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name || s.id}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="fdd-assign-device">
              BACnet device
            </label>
            <select
              id="fdd-assign-device"
              value={deviceKey}
              disabled={loading || !devices.length}
              onChange={(e) => setDeviceKey(e.target.value)}
            >
              {devices.map((d) => (
                <option key={d.device_key} value={d.device_key}>
                  {d.label} ({d.point_count} pts)
                </option>
              ))}
            </select>
          </div>
          {activeDevice ? (
            <p className="muted fdd-assign-device-meta">
              {visiblePoints.length} point{visiblePoints.length === 1 ? "" : "s"} on this device
            </p>
          ) : null}
        </div>

        {loading ? <p className="muted">Loading points…</p> : null}
        {error ? <p className="error">{error}</p> : null}

        {visiblePoints.length ? (
          <div className="dm-points-table-wrap">
            <table className="dm-points-table fdd-assign-points-table">
              <thead>
                <tr>
                  <th>Raw name</th>
                  <th>Point address</th>
                  <th>BRICK class</th>
                  <th>Unit</th>
                  <th>Equipment</th>
                  <th>Pinned rules</th>
                </tr>
              </thead>
              <tbody>
                {visiblePoints.map((p) => (
                  <tr
                    key={p.point_id}
                    className="dm-points-row dm-focusable"
                    tabIndex={0}
                    role="button"
                    title="Right-click to pin or unpin FDD rules"
                    onContextMenu={(e) => openPinMenu(e, p)}
                  >
                    <td>
                      <strong>{p.name}</strong>
                    </td>
                    <td>
                      <code>{p.object_identifier || "—"}</code>
                    </td>
                    <td className="dm-brick-cell">{p.brick_type || "—"}</td>
                    <td className="muted">{p.unit || "—"}</td>
                    <td className="muted">{p.equipment_name || p.equipment_id || "—"}</td>
                    <td>
                      <RuleAssignmentMultiSelect
                        pointId={p.point_id}
                        pointLabel={p.name || p.point_id}
                        rules={rules}
                        boundRuleIds={(p.bound_rules ?? []).map((r) => r.rule_id)}
                        disabled={loading}
                        onChanged={() => setRefreshKey((k) => k + 1)}
                        onStatus={setStatus}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : !loading ? (
          <p className="muted">No points for this device. Import a model or enable BACnet polling.</p>
        ) : null}
      </section>

      <FddRulePinMenu
        menu={pinMenu}
        rules={rules}
        onClose={() => setPinMenu(null)}
        onStatus={setStatus}
        onChanged={() => setRefreshKey((k) => k + 1)}
      />

      {status ? <p className="ok">{status}</p> : null}
    </div>
  );
}
