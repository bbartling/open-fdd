// Generic, synthetic multi-sensor dataset shared by FDD hook and UI regressions.
const point = (uuid, name, role, unit, equipRef = 'AHU-A') => ({
  uuid, name, layer: 'default', pointType: 'POINT',
  attrs: {
    siteRef: 'site-fixture', equipRef, unit, dis: name,
    markers: `point,his,${role === 'sat' || role === 'mat' || role === 'oa_t' || role === 'rat' ? 'discharge,air,temp,sensor' : role === 'duct_static' ? 'discharge,air,pressure,sensor' : role === 'zone_flow' ? 'air,flow,sensor' : 'outside,air,temp,sensor'}`,
    class: role === 'sat' ? 'discharge-air-temp-sensor' : role === 'mat' ? 'mixed-air-temp-sensor' : role === 'rat' ? 'return-air-temp-sensor' : role === 'duct_static' ? 'discharge-air-pressure-sensor' : role === 'zone_flow' ? 'discharge-air-flow-sensor' : 'outside-air-temp-sensor',
  },
});

export const multiSensorEquip = Object.freeze({
  sites: [{ uuid: 'site-fixture-uuid', name: 'site-fixture', pointType: 'SITE', attrs: { id: 'site-fixture', markers: 'site' } }],
  equips: [
    { uuid: 'ahu-fixture-uuid', name: 'AHU-A', pointType: 'EQUIPMENT', attrs: { id: 'AHU-A', siteRef: 'site-fixture', markers: 'equip,ahu' } },
    { uuid: 'vav-fixture-uuid', name: 'VAV-A', pointType: 'EQUIPMENT', attrs: { id: 'VAV-A', siteRef: 'site-fixture', markers: 'equip,vav' } },
  ],
  points: [
    point('sensor-sat-1', 'sensor-1', 'sat', '°C'),
    point('sensor-sat-2', 'sensor-2', 'sat', '°C'),
    point('sensor-mat-1', 'sensor-3', 'mat', '°C'),
    point('sensor-oa-1', 'sensor-4', 'oa_t', '°C'),
    point('sensor-rat-1', 'sensor-5', 'rat', '°C'),
    point('sensor-static-1', 'sensor-6', 'duct_static', 'in h₂0'),
    point('sensor-flow-1', 'sensor-7', 'zone_flow', 'L/sec', 'VAV-A'),
  ],
  unitBoundaryPoint: point('sensor-unit-boundary', 'sensor-8', 'sat', '°C'),
  historyValue(uuid, index) {
    if (uuid === 'sensor-sat-2') return 20; // constant: flatline
    if (uuid === 'sensor-mat-1' && index === 120) return 100; // rate spike
    if (uuid === 'sensor-rat-1') return 65; // out of range
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
