import type { EquipmentGroup, SiteRow } from "../lib/telemetryCatalog";

type Props = {
  sites: SiteRow[];
  siteId: string;
  onSiteChange: (id: string) => void;
  equipmentGroups: EquipmentGroup[];
  equipmentId: string;
  onEquipmentChange: (id: string) => void;
  showAllDevices?: boolean;
  disabled?: boolean;
  idPrefix?: string;
};

/** Site + BACnet device selectors shared by Trend plot and Rule Lab. */
export default function TelemetryScopePicker({
  sites,
  siteId,
  onSiteChange,
  equipmentGroups,
  equipmentId,
  onEquipmentChange,
  showAllDevices = true,
  disabled = false,
  idPrefix = "scope",
}: Props) {
  return (
    <>
      <div className="field">
        <label className="field-label" htmlFor={`${idPrefix}-site`}>
          Site
        </label>
        <select
          id={`${idPrefix}-site`}
          value={siteId}
          disabled={disabled}
          onChange={(e) => onSiteChange(e.target.value)}
        >
          {sites.map((s) => (
            <option key={s.site_id} value={s.site_id}>
              {s.name || s.site_id}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label className="field-label" htmlFor={`${idPrefix}-device`}>
          Device
        </label>
        <select
          id={`${idPrefix}-device`}
          value={equipmentId}
          disabled={disabled || (!equipmentGroups.length && !siteId)}
          onChange={(e) => onEquipmentChange(e.target.value)}
        >
          {showAllDevices && equipmentGroups.length > 1 ? (
            <option value="__all__">All devices (building)</option>
          ) : null}
          {equipmentGroups.map((g) => (
            <option key={g.equipment_id || "_unassigned"} value={g.equipment_id}>
              {g.label} ({g.keys.length} pts)
            </option>
          ))}
        </select>
      </div>
    </>
  );
}
