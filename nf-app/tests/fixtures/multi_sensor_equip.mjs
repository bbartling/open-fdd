// Generic, synthetic multi-sensor dataset shared by FDD hook and UI regressions.
const point = (uuid, name, role, unit, equipRef = 'AHU-A') => ({
  uuid, name, layer: 'default', pointType: 'POINT',
  attrs: {
    siteRef: 'site-fixture', equipRef, unit, dis: name,
    markers: `point,his,${role === 'discharge_air_temperature' || role === 'mixed_air_temperature' || role === 'outdoor_air_intake_temperature' || role === 'return_air_temperature' ? 'discharge,air,temp,sensor' : role === 'discharge_air_static_pressure' ? 'discharge,air,pressure,sensor' : role === 'discharge_air_volume_flow_rate' ? 'air,flow,sensor' : 'outside,air,temp,sensor'}`,
    class: role === 'discharge_air_temperature' ? 'discharge-air-temp-sensor' : role === 'mixed_air_temperature' ? 'mixed-air-temp-sensor' : role === 'return_air_temperature' ? 'return-air-temp-sensor' : role === 'discharge_air_static_pressure' ? 'discharge-air-pressure-sensor' : role === 'discharge_air_volume_flow_rate' ? 'discharge-air-flow-sensor' : 'outside-air-temp-sensor',
  },
});

export const multiSensorEquip = Object.freeze({
  sites: [{ uuid: 'site-fixture-uuid', name: 'site-fixture', pointType: 'SITE', attrs: { id: 'site-fixture', markers: 'site' } }],
  equips: [
    { uuid: 'ahu-fixture-uuid', name: 'AHU-A', pointType: 'EQUIPMENT', attrs: { id: 'AHU-A', siteRef: 'site-fixture', markers: 'equip,ahu' } },
    { uuid: 'vav-fixture-uuid', name: 'VAV-A', pointType: 'EQUIPMENT', attrs: { id: 'VAV-A', siteRef: 'site-fixture', markers: 'equip,vav' } },
  ],
  points: [
    point('sensor-discharge_air_temperature-1', 'sensor-1', 'discharge_air_temperature', '°C'),
    point('sensor-discharge_air_temperature-2', 'sensor-2', 'discharge_air_temperature', '°C'),
    point('sensor-mixed_air_temperature-1', 'sensor-3', 'mixed_air_temperature', '°C'),
    point('sensor-oa-1', 'sensor-4', 'outdoor_air_intake_temperature', '°C'),
    point('sensor-return_air_temperature-1', 'sensor-5', 'return_air_temperature', '°C'),
    point('sensor-static-1', 'sensor-6', 'discharge_air_static_pressure', 'in h₂0'),
    point('sensor-flow-1', 'sensor-7', 'discharge_air_volume_flow_rate', 'L/sec', 'VAV-A'),
  ],
  unitBoundaryPoint: point('sensor-unit-boundary', 'sensor-8', 'discharge_air_temperature', '°C'),
  historyValue(uuid, index) {
    if (uuid === 'sensor-discharge_air_temperature-2') return 20; // constant: flatline
    if (uuid === 'sensor-mixed_air_temperature-1' && index === 120) return 100; // rate spike
    if (uuid === 'sensor-return_air_temperature-1') return 65; // out of range
    if (uuid === 'sensor-unit-boundary') return index < 144 ? 12 : 12; // caller supplies the historical unit boundary
    return uuid === 'sensor-static-1' ? 250 : uuid === 'sensor-flow-1' ? 1 : 22;
  },
  unitBoundarySeries() {
    return Array.from({ length: 288 }, (_, index) => ({
      ts: new Date(Date.UTC(2026, 10, 8, 0, 0) + index * 300000).toISOString(),
      value: index < 144 ? 18 : 2.25,
      unit: index < 144 ? '%' : 'h',
    }));
  },
  unitBoundaryIndex: 144,
});
