import { postAnalytics } from "./analyticsApi";
import type { AnalyticsEnvelope, AnalyticsRequest } from "./analyticsApi";

function postHealth(path: string, body: AnalyticsRequest): Promise<AnalyticsEnvelope> {
  return postAnalytics(path, body);
}

export const postAhuTemperatureHealth = (body: AnalyticsRequest) =>
  postHealth("/api/analytics/ahu-temperature-health", body);

export const postAhuPressureHealth = (body: AnalyticsRequest) =>
  postHealth("/api/analytics/ahu-pressure-health", body);

export const postAhuEconomizerHealth = (body: AnalyticsRequest) =>
  postHealth("/api/analytics/ahu-economizer-health", body);

export const postCoolingTowerHealth = (body: AnalyticsRequest) =>
  postHealth("/api/analytics/cooling-tower-health", body);

export const postPidHunting = (body: AnalyticsRequest) =>
  postHealth("/api/analytics/pid-hunting", body);

export const postSensorFaults = (body: AnalyticsRequest) =>
  postHealth("/api/analytics/sensor-faults", body);
