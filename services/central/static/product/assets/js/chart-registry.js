/**
 * Keeps parity renderer modules in the app.js import graph (static_product reachability test).
 * Tab code may import these directly when wiring new UI surfaces.
 */
export { sensorHealthHeatmapOption, sensorFaultChartOption } from "./sensor-charts.js";
export {
  summaryPeerBulletOption,
  rankedSiteEuiOption,
  stackedFuelOption,
} from "./fuel-charts.js";
export { rcxPresetOption, multiEquipmentTimeseriesOption } from "./rcx-vibe-charts.js";
