# Bench 5007 DataFusion smoke verification

Rust-only rebuild of the old master bench FDD smoke: BACnet device **5007** → Arrow historian → DataFusion SQL → confirmation-duration faults.

## Prerequisites

1. Bring up the Rust edge stack (see `README.md` / bootstrap scripts).
2. For **live** bench runs on Ben's Linux OT LAN:

```bash
export OPENFDD_BACNET_MODE=live
export OPENFDD_BACNET_IFACE=enp3s0
export OPENFDD_BACNET_BIND=192.168.204.55/24:47808
export OPENFDD_BACNET_ROUTER_IP=192.168.204.200
export OPENFDD_BACNET_MSTP_NET=2000
export OPENFDD_BENCH_DEVICE_INSTANCE=5007
export OPENFDD_BENCH_5007_LIVE=1
docker compose -f docker-compose.yml -f docker-compose.bacnet-live.yml up -d --build
```

3. Verify device 5007 appears in the driver tree:

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bacnet/driver/tree | jq '.drivers[0].devices[] | select(.device_instance==5007)'
```

## Run 1-hour live smoke (Ben's bench)

```bash
cd edge
cargo run --release --bin bench_5007_datafusion_smoke -- \
  --live-required \
  --duration-minutes 60 \
  --phase-minutes 15 \
  --poll-interval-seconds 60 \
  --confirmation-seconds 300
```

Reports are written to `workspace/reports/bench_5007_datafusion_smoke/`:

- `final_report.json` / `final_report.md`
- `events.csv`, `samples_summary.csv`, `rule_phase_results.csv`

## Shorter dry run

```bash
cargo run --release --bin bench_5007_datafusion_smoke -- \
  --allow-simulated \
  --duration-minutes 20 \
  --phase-minutes 5 \
  --confirmation-seconds 120 \
  --poll-interval-seconds 10
```

## CI simulated mode

GitHub Actions runs `cargo test bench_5007_simulated` which executes a **labeled simulated** 4-minute smoke (Rust-generated samples, real DataFusion SQL + Arrow path).

Manual:

```bash
cd edge && cargo test simulated_bench5007_datafusion_smoke_passes -- --nocapture
```

## Phase plan (default 60 / 15 min)

| Phase | Minutes | high_limit | Expected |
| --- | --- | --- | --- |
| 0 | 0–15 | 150 °F | no fault (~72 °F OAT) |
| 1 | 15–30 | 50 °F | raw fault immediately; confirmed after 5 min continuous |
| 2 | 30–45 | 150 °F | raw clears on next sample; **confirmed clears immediately** |
| 3 | 45–60 | 50 °F | raw + confirmed fault pattern repeats |

**Confirmation policy:** `fault_confirmed` requires continuous `fault_raw` for `OPENFDD_CONFIRMATION_SECONDS` (default 300). Missing gaps larger than poll interval + tolerance reset the streak. Clearing is **immediate** when limits return to normal.

## BACnet proof (live)

Live mode records `requests_sent`, `responses_received`, `source=real`, `generated_from_demo_fixture=false`. If live BACnet is unavailable, the smoke **fails** (no silent fallback).

Optional packet capture:

```bash
sudo tcpdump -ni enp3s0 'udp port 47808' -vv
```

## API status

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/bench/5007/smoke/status | jq .
```

Full 1-hour runs should use the CLI (auth-protected `POST /api/bench/5007/smoke/run` returns CLI guidance).

## Bench points (device 5007)

| FDD input | BACnet object | point id |
| --- | --- | --- |
| oa-t | analog-input:1173 | bacnet:5007:analog-input:1173 |
| oa-h | analog-input:1168 | bacnet:5007:analog-input:1168 |
| duct-t | analog-input:1192 | bacnet:5007:analog-input:1192 |
| stat_zn-t | analog-input:10014 | bacnet:5007:analog-input:10014 |

SQL column for oa-t rule: `oa_t`.

## DataFusion / Arrow

- Telemetry stored as Apache Arrow `RecordBatch` (`bench5007_telemetry` table).
- FDD rule executed via DataFusion SQL (`CASE WHEN oa_t > high OR oa_t < low`).
- Report includes `target_partitions`, batch shape, and execution path metadata.
- A 1-hour bench dataset is tiny; it will not saturate all CPU cores—this is expected.

## No Python / PyArrow

This path uses **zero** PyArrow, Pandas, or Python rule execution at runtime.
