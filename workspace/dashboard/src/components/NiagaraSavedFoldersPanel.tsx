import { useMemo } from "react";
import ActionButton from "./ActionButton";
import type { NiagaraCommissionDevice, NiagaraCommissionProfile } from "../lib/niagaraCommissionProfile";
import { brickBindingHint } from "../lib/niagaraCommissionProfile";

type Props = {
  profile: NiagaraCommissionProfile;
  pending?: boolean;
  pointCountByDevice?: Record<string, number>;
  onDiscoverDevice: (deviceId: string) => void;
  onDiscoverAll: () => void;
  onRemoveBuilding: (buildingId: string) => void;
  onRemoveDevice: (deviceId: string) => void;
  onSaveProfile: () => void;
};

export default function NiagaraSavedFoldersPanel({
  profile,
  pending,
  pointCountByDevice = {},
  onDiscoverDevice,
  onDiscoverAll,
  onRemoveBuilding,
  onRemoveDevice,
  onSaveProfile,
}: Props) {
  const devicesByBuilding = useMemo(() => {
    const map = new Map<string, NiagaraCommissionDevice[]>();
    for (const dev of profile.devices) {
      const list = map.get(dev.building_id) ?? [];
      list.push(dev);
      map.set(dev.building_id, list);
    }
    for (const [, list] of map) {
      list.sort((a, b) => a.label.localeCompare(b.label));
    }
    return map;
  }, [profile.devices]);

  if (!profile.buildings.length && !profile.devices.length) {
    return (
      <div className="niagara-saved-folders-empty">
        <p className="muted" style={{ margin: 0 }}>
          Check folders in the station tree above, then <strong>Add as building</strong> or{" "}
          <strong>Add as device</strong>. Saved folders appear here for point discovery and polling.
        </p>
      </div>
    );
  }

  return (
    <div className="niagara-saved-folders">
      <div className="bacnet-bulk-toolbar" style={{ marginBottom: "0.75rem" }}>
        <span className="muted">
          {profile.buildings.length} building(s) · {profile.devices.length} device folder(s)
        </span>
        <ActionButton secondary pending={pending} disabled={!profile.devices.length} onClick={onDiscoverAll}>
          Discover points in all saved folders
        </ActionButton>
        <ActionButton secondary pending={pending} onClick={onSaveProfile}>
          Save folders to Open-FDD
        </ActionButton>
      </div>
      {profile.buildings.map((building) => {
        const devices = devicesByBuilding.get(building.id) ?? [];
        return (
          <details key={building.id} className="niagara-saved-building" open>
            <summary>
              <span className="niagara-saved-building-title">🏢 {building.label}</span>
              <code className="mono muted">{building.folder_ord}</code>
              <button
                type="button"
                className="secondary-btn small-btn"
                onClick={(e) => {
                  e.preventDefault();
                  onRemoveBuilding(building.id);
                }}
              >
                Remove
              </button>
            </summary>
            {devices.length ? (
              <table className="data-table niagara-saved-device-table">
                <thead>
                  <tr>
                    <th>Device folder</th>
                    <th>Points root</th>
                    <th>Cached points</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {devices.map((dev) => (
                    <tr key={dev.id}>
                      <td>
                        <strong>{dev.label}</strong>
                        <div className="muted mono">{dev.folder_ord}</div>
                        <div className="muted" style={{ fontSize: "0.78rem" }}>
                          {brickBindingHint(dev, building)}
                        </div>
                      </td>
                      <td className="mono">{dev.points_root || dev.folder_ord}</td>
                      <td>{pointCountByDevice[dev.id] ?? 0}</td>
                      <td>
                        <button
                          type="button"
                          className="secondary-btn"
                          disabled={pending}
                          onClick={() => onDiscoverDevice(dev.id)}
                        >
                          Discover points
                        </button>
                        <button
                          type="button"
                          className="secondary-btn small-btn"
                          disabled={pending}
                          onClick={() => onRemoveDevice(dev.id)}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">No devices under this building yet — select device folders in the browse tree.</p>
            )}
          </details>
        );
      })}
    </div>
  );
}
