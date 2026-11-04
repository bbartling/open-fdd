import { postAnalytics } from "./analyticsApi";
import type { AnalyticsEnvelope, AnalyticsRequest } from "./analyticsApi";

type HealthInit = { signal?: AbortSignal };

function postHealth(
  path: string,
  body: AnalyticsRequest,
  init?: HealthInit,
): Promise<AnalyticsEnvelope> {
  return postAnalytics(path, body, init);
}

export const postAhuTemperatureHealth = (
  body: AnalyticsRequest,
  init?: HealthInit,
) => postHealth("/api/analytics/ahu-temperature-health", body, init);

export const postAhuPressureHealth = (body: AnalyticsRequest, init?: HealthInit) =>
  postHealth("/api/analytics/ahu-pressure-health", body, init);

export const postAhuEconomizerHealth = (
  body: AnalyticsRequest,
  init?: HealthInit,
) => postHealth("/api/analytics/ahu-economizer-health", body, init);

export const postCoolingTowerHealth = (
  body: AnalyticsRequest,
  init?: HealthInit,
) => postHealth("/api/analytics/cooling-tower-health", body, init);

export const postPidHunting = (body: AnalyticsRequest, init?: HealthInit) =>
  postHealth("/api/analytics/pid-hunting", body, init);

export const postSensorFaults = (body: AnalyticsRequest, init?: HealthInit) =>
  postHealth("/api/analytics/sensor-faults", body, init);

export const postZoneOtherHealth = (body: AnalyticsRequest, init?: HealthInit) =>
  postHealth("/api/analytics/zone-other-health", body, init);
