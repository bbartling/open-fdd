import type { ModelEquipment, ModelSensor, ModelSite } from "../lib/useModelScope";

type Props = {
  sites: ModelSite[];
  siteId: string;
  onSiteChange: (id: string) => void;
  equipment: ModelEquipment[];
  equipmentId: string;
  onEquipmentChange: (id: string) => void;
  sensors: ModelSensor[];
  sensorPointId: string;
  onSensorChange: (pointId: string) => void;
  disabled?: boolean;
  idPrefix?: string;
  queryEngine?: string;
};

/** Site / equipment / sensor from BRICK model SPARQL scope API. */
export default function ModelScopePicker({
  sites,
  siteId,
  onSiteChange,
  equipment,
  equipmentId,
  onEquipmentChange,
  sensors,
  sensorPointId,
  onSensorChange,
  disabled = false,
  idPrefix = "model-scope",
  queryEngine,
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
          disabled={disabled || !sites.length}
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
          disabled={disabled || !equipment.length}
          onChange={(e) => onEquipmentChange(e.target.value)}
        >
          {!equipment.length ? <option value="">— no equipment —</option> : null}
          {equipment.map((eq) => (
            <option key={eq.equipment_id} value={eq.equipment_id}>
              {eq.name}
              {eq.bacnet_device_instance != null ? ` · dev ${eq.bacnet_device_instance}` : ""}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label className="field-label" htmlFor={`${idPrefix}-sensor`}>
          Sensor
        </label>
        <select
          id={`${idPrefix}-sensor`}
          value={sensorPointId}
          disabled={disabled || !sensors.length}
          onChange={(e) => onSensorChange(e.target.value)}
        >
          {!sensors.length ? <option value="">— no points —</option> : null}
          {sensors.map((s) => (
            <option key={s.point_id} value={s.point_id}>
              {s.label}
              {s.brick_type ? ` · ${s.brick_type}` : ""}
            </option>
          ))}
        </select>
      </div>
      {queryEngine ? (
        <p className="muted model-scope-engine">
          Data model scope via <code>{queryEngine}</code>
        </p>
      ) : null}
    </>
  );
}
