/** Standard poll intervals — BACnet, Modbus, and JSON API. */

export const STANDARD_POLL_INTERVALS = [
  { seconds: 60, label: "1 min" },
  { seconds: 300, label: "5 min" },
  { seconds: 900, label: "15 min" },
  { seconds: 1800, label: "30 min" },
  { seconds: 3600, label: "1 hour" },
] as const;

/** Context-menu shape used by BACnet/Modbus/JSON API trees. */
export const POLL_OPTIONS = STANDARD_POLL_INTERVALS;

export const DEFAULT_POLL_INTERVAL_S = 900;
