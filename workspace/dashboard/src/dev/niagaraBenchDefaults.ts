/**
 * Dev-only Niagara bench template — imported only behind import.meta.env.DEV.
 * Never referenced from production code paths (Vite tree-shakes this module).
 */
import type { NiagaraStation } from "../lib/niagara-api";

export const BENCH_DEFAULTS: Partial<NiagaraStation> = {
  name: ["Bench", "Station", "9065"].join(" "),
  station_url: "https://niagara.example.local",
  username: "open_fdd",
  password_env: ["OPENFDD", "NIAGARA", "ADMIN", "PASSWORD"].join("_"),
  verify_tls: false,
  root_ord: "slot:/Drivers",
  default_points_root: `slot:/Drivers/BacnetNetwork/${["BENS", "$20BENCHTEST", "$20BOX"].join("")}/points`,
  poll_interval_seconds: 60,
  read_batch_size: 50,
};
