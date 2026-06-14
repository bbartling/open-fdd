/**
 * Dev-only Niagara bench template — imported only behind import.meta.env.DEV.
 * Never referenced from production code paths (Vite tree-shakes this module).
 */
import type { NiagaraStation } from "../lib/niagara-api";

export const BENCH_DEFAULTS: Partial<NiagaraStation> = {
  name: "Bench Station 9065",
  station_url: "https://192.168.204.11",
  username: "open_fdd",
  password_env: "OPENFDD_NIAGARA_ADMIN_PASSWORD",
  verify_tls: false,
  root_ord: "slot:/Drivers",
  default_points_root: "slot:/Drivers/BacnetNetwork/BENS$20BENCHTEST$20BOX/points",
  poll_interval_seconds: 60,
  read_batch_size: 50,
};
