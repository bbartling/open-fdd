/**
 * Keeps parity renderer modules in the app.js import graph (static_product reachability test).
 */
import {
  sensorHealthHeatmapOption,
  sensorFaultChartOption,
} from "./sensor-charts.js";
import {
  summaryPeerBulletOption,
  rankedSiteEuiOption,
  stackedFuelOption,
} from "./fuel-charts.js";
import { rcxPresetOption, multiEquipmentTimeseriesOption } from "./rcx-vibe-charts.js";

export {
  sensorHealthHeatmapOption,
  sensorFaultChartOption,
  summaryPeerBulletOption,
  rankedSiteEuiOption,
  stackedFuelOption,
  rcxPresetOption,
  multiEquipmentTimeseriesOption,
};
