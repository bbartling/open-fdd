# ML FDD benchmark on the LBNL single-duct AHU data

This page records how the `open-fdd[ml]` detectors and the Open-FDD pandas rule pack were tested on public, labeled
fault data, and what came out. Every number below was produced by `open-fdd-ml benchmark` (this branch of open-fdd) on the
files listed here; nothing is estimated or copied from a paper. Where a method does worse than the rules, the table says so.

## Data

Source: Lawrence Berkeley National Laboratory, *LBNL FDD Data Sets*, single-duct AHU (simulated), Granderson, Lin,
Chen, Casillas, Huang, Vrabie (2022), <https://faultdetection.lbl.gov/data/>, DOI
[10.25984/1881324](https://doi.org/10.25984/1881324), licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). A VAV AHU serving one floor of the DOE large office reference
building, Chicago TMY weather, one year at 1-minute resolution per file, each fault present for the whole year.

Subset (8 of the 21 files). `open-fdd-ml download` fetches only these members of the 580 MB zip with HTTP range
requests (about 30 MB compressed each) into `$OPENFDD_ML_CACHE` or `~/.cache/open-fdd/lbnl`; the CSVs are never
committed:

| File | Label | Fault | Intensity |
|---|---|---|---|
| `AHU_annual.csv` | normal | none | fault-free |
| `coi_bias_4_annual.csv` | fault | SAT sensor bias | +4 °C (`coi_bias_*` in the zip = `sa_bias_*` in the data sheet) |
| `coi_bias_-4_annual.csv` | fault | SAT sensor bias | -4 °C |
| `oa_bias_4_annual.csv` | fault | OAT sensor bias | the four `oa_bias_*` members are byte-identical (same CRC-32) |
| `damper_stuck_010_annual.csv` | fault | OA damper stuck | 10 % (the normal minimum position) |
| `damper_stuck_075_annual.csv` | fault | OA damper stuck | 75 % |
| `coi_stuck_050_annual.csv` | fault | Cooling valve stuck | 50 % |
| `coi_leakage_050_annual.csv` | fault | Cooling valve leaking | the four `coi_leakage_*` members are byte-identical |

The repo commits only a two-day derived fixture (`tests/fixtures/lbnl_sdahu/`, with attribution) for the unit tests.

## Column to role mapping (SI)

Only the data sheet's "basic" BAS points are used, the points a real AHU usually has. Rows are subsampled every
5 minutes (a poll, not an average) onto a UTC index (the simulation has no time zone).

| LBNL column | Open-FDD role | Conversion |
|---|---|---|
| `SA_TEMP` | `discharge-air-temp` | °F to °C |
| `SA_TEMPSPT` | `discharge-air-temp-sp` | °F to °C |
| `MA_TEMP` | `mixed-air-temp` | °F to °C |
| `RA_TEMP` | `return-air-temp` | °F to °C |
| `OA_TEMP` | `outside-air-temp` | °F to °C |
| `OA_DMPR_DM` | `outside-air-damper` | command, 0-1 |
| `CHWC_VLV_DM` | `cooling-valve` | command, 0-1 |
| `SF_CS` | `fan-cmd` | 0-1 |
| `RF_CS` | `return-fan-cmd` | 0-1 |
| `SF_SPD_DM` | `fan-status` | 0/1 |
| `SA_SP` | `duct-static-pressure` | Pa (unit detected per file, see below) |
| `SA_SPSPT` | `duct-static-pressure-sp` | Pa, magnitude (unit detected per file) |
| `SYS_CTL` | `occupied` | 0/1 |

No heating valve, coil entering/leaving temperatures or airflow totals are mapped, so the rules that need them
(FC5-FC7, FC14, FC15, AHU-SIMUL, ECON-3, ECON-5 and others) skip.

Published-data quirks found while mapping, and how they are handled:

- Duct static is stored differently in the fault-free file (`SA_SP` about 403 Pa and nearly constant even with the fan
  off, `SA_SPSPT` 1.607 inH2O) and in every faulted file (`SA_SP` in inH2O and varying, `SA_SPSPT` -400.25).
  `open_fdd.ml.lbnl.static_to_pa` converts by magnitude. Because the *behavior* also differs between the runs, duct
  static is left out of the ML features (`BENCHMARK_ROLES`). In a first trial run that kept it, PCA flagged 98-100 % of
  every faulted file with fan command and duct static as the top contributors whatever the fault; that run is not
  reported as a result.
- The logged OAT of the `oa_bias` file equals the fault-free OAT (median difference +0.00 °C), so the bias acted on the
  controller but is not visible in the logged sensor. The logged SAT of `coi_bias_4` is also nearly unchanged
  (+0.05 °C); the fault shows in the cooling valve instead.
- The occupied schedule of the fault-free run differs from the faulted runs on about 4.5 % of minutes (an hour a day
  for part of the year), and its unoccupied temperatures run warmer. Activity is therefore computed per file.

## Protocol

1. **Split by ISO week**: odd weeks train, even weeks test, so both seasons are in each half.
2. **Training**: detectors that learn are fitted on the fault-free file's odd weeks only, active rows only. No method
   sees a faulted file before it is scored. Thresholds: the 99th percentile of the training score (PCA / SPE,
   gray-box residuals); `nu` / contamination 0.01 (one-class SVM, COPOD).
3. **Active rows**: supply fan proven on (`fan-status`) and occupied.
4. **Evaluation sample** (Frank, Lin, Granderson et al. 2019): a one-hour window in a test week with the unit active for
   at least half of it, flagged when at least 25 % of its active 5-minute points are flagged (15 minutes of persistence).
5. **Labels**: every sample of a faulted file is a fault sample; every sample of the fault-free file is normal.
   FPR comes from the fault-free file, TPR and detection delay from each faulted file. Faults that are physically
   invisible in some hours (a valve stuck at 50 % when no cooling is needed, a damper stuck at its normal minimum)
   still count as fault samples, as in the LBNL framework, which caps every method's TPR.
6. **Detection delay**: hours from the first test window (early January) to the first flagged window. Because the
   faults last all year, this mostly shows the season in which a fault becomes visible.

| Row | What it is |
|---|---|
| `rules (all)` | Union of every Open-FDD pandas AHU rule that confirmed a fault (`open_fdd.ml.baseline`; gates and `confirm_min` as in parity) |
| `rules (tuned)` | The same minus rules whose one-hour FPR on the fault-free *training* weeks exceeds 5 % (advisories an engineer silences on a healthy unit); same training data as the ML rows |
| `pca` | PCA on 7 standardized roles (90 % variance), SPE above the training 99th percentile, per-role contributions |
| `grey_box` | Residuals against binned medians learned on normal data: OA fraction from the mixed-air balance vs damper command, cooling coil air-side delta-T vs valve command, SAT minus setpoint while the valve modulates |
| `ocsvm` | One-class SVM (scikit-learn) per operating mode (min OA, economizer only, mechanical at min OA, economizer + mechanical), seeded 4000-row subsample per mode |
| `copod` | COPOD (pyod) per operating mode, roles constant within a mode dropped |
| `zscore`, `mad` | The existing `open_fdd.analytics.anomaly` rolling detectors on each role, one-day window, no training |

## Results

| Method | FPR % (fault-free) | TPR % SAT sensor bias +4 °C | TPR % SAT sensor bias -4 °C | TPR % OAT sensor bias ±2/±4 °C (files identical) | TPR % OA damper stuck 10 % (= minimum position) | TPR % OA damper stuck 75 % | TPR % Cooling valve stuck 50 % | TPR % Cooling valve leaking 10-50 % (files identical) | Mean TPR % |
|---|---|---|---|---|---|---|---|---|---|
| `rules (all)` | 92.4 | 93.7 | 92.9 | 93.4 | 93.3 | 67.5 | 92.7 | 93.4 | 89.6 |
| `rules (tuned)` | 3.1 | 39.3 | 44.9 | 12.2 | 44.8 | 57.9 | 45.4 | 10.0 | 36.4 |
| `pca` | 1.0 | 3.5 | 2.2 | 0.0 | 0.3 | 25.3 | 0.0 | 0.0 | 4.5 |
| `grey_box` | 3.2 | 59.8 | 100.0 | 2.3 | 41.9 | 87.7 | 7.7 | 3.5 | 43.3 |
| `ocsvm` | 4.7 | 100.0 | 100.0 | 14.0 | 43.1 | 51.1 | 99.8 | 11.0 | 59.9 |
| `copod` | 1.7 | 1.2 | 1.5 | 1.7 | 1.5 | 0.2 | 1.3 | 1.8 | 1.3 |
| `zscore` | 14.1 | 16.3 | 11.2 | 14.8 | 12.5 | 12.5 | 13.4 | 14.5 | 13.6 |
| `mad` | 58.1 | 62.2 | 46.4 | 62.2 | 61.9 | 63.4 | 56.5 | 61.5 | 59.2 |

Evaluation samples: one-hour windows in even ISO weeks with the fan on and occupied (2328 windows in the fault-free file).

Detection delay, hours from the first test window (early January) to the first flagged window:

| Method | SAT sensor bias +4 °C | SAT sensor bias -4 °C | OAT sensor bias ±2/±4 °C (files identical) | OA damper stuck 10 % (= minimum position) | OA damper stuck 75 % | Cooling valve stuck 50 % | Cooling valve leaking 10-50 % (files identical) |
|---|---|---|---|---|---|---|---|
| `rules (all)` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `rules (tuned)` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `pca` | 0 | 76 | never | 72 | 0 | never | never |
| `grey_box` | 0 | 0 | 0 | 6 | 0 | 0 | 24 |
| `ocsvm` | 0 | 0 | 0 | 0 | 798 | 0 | 0 |
| `copod` | 96 | 0 | 0 | 96 | 3432 | 0 | 0 |
| `zscore` | 2 | 0 | 4 | 4 | 1 | 3 | 4 |
| `mad` | 0 | 0 | 0 | 2 | 1 | 0 | 0 |

`rules (tuned)` leaves out, by their one-hour FPR on the fault-free training weeks: ECON-4 (59 %), OA-1 (58 %), RESET-1 (69 %).

Rules that confirmed a fault, by test windows flagged (top 4 per file):

| File | Rules (windows) |
|---|---|
| none fault-free | RESET-1 (1566), ECON-4 (1236), OA-1 (1219), AHU-SATDEV (55) |
| SAT sensor bias +4 °C | RESET-1 (1544), ECON-4 (1268), OA-1 (1243), FC8 (795) |
| SAT sensor bias -4 °C | RESET-1 (1544), ECON-4 (1256), OA-1 (1238), FC8 (965) |
| OAT sensor bias ±2/±4 °C (files identical) | RESET-1 (1544), ECON-4 (1268), OA-1 (1249), FC1 (169) |
| OA damper stuck 10 % (= minimum position) | ECON-4 (2168), OA-1 (2156), RESET-1 (1544), FC10 (945) |
| OA damper stuck 75 % | RESET-1 (1544), FC8 (910), VLV-1 (736), AHU-SATDEV (429) |
| Cooling valve stuck 50 % | RESET-1 (1544), ECON-4 (1251), OA-1 (1227), FC8 (974) |
| Cooling valve leaking 10-50 % (files identical) | RESET-1 (1544), ECON-4 (1270), OA-1 (1250), FC1 (155) |

Data checks: oa_bias file minus fault-free OAT: median +0.00 °C; coi_bias_4 file minus fault-free SAT (fan on): median +0.05 °C.

## What the numbers say

- **No method is good on its own.** The untuned rule pack flags 92 % of fault-free hours (design-level advisories that
  fire on the healthy unit: RESET-1 for the fixed SAT setpoint, ECON-4 and OA-1 for the 10 % minimum OA), so its 90 %
  TPR means nothing. Silencing those three (`rules (tuned)`) gives 3.1 % FPR and 36.4 % mean TPR.
- **Gray-box residuals beat the tuned rules** at about the same FPR (3.2 % vs 3.1 %): 43.3 % mean TPR, much better on
  the damper stuck at 75 % (87.7 % vs 57.9 %) and the SAT bias -4 °C (100 % vs 44.9 %), but worse on the stuck valve
  (7.7 % vs 45.4 %), the damper stuck at minimum (41.9 % vs 44.8 %) and the OAT-bias file (2.3 % vs 12.2 %).
- **The mode-gated one-class SVM has the highest TPR** (59.9 % mean; 100 % on both SAT biases, 99.8 % on the stuck
  valve) at a higher FPR (4.7 %), and it cannot say which fault it saw.
- **PCA / SPE underperforms the rules** at its default threshold (1.0 % FPR, 4.5 % mean TPR). **COPOD is no better
  than chance**: it flags about its contamination rate in every file.
- **Z-score and MAD are not fault detectors here**: they flag faulty and fault-free hours at about the same rate
  (13-14 % and about 60 %). They find single-signal outliers, which is what `open-fdd-anomaly` uses them for.
- **No method detects the OAT-bias or valve-leakage files much above its false-positive rate**: the logged basic points
  barely change (see the data quirks).
- These are single-building, simulated results, with thresholds learned on the same unit's healthy weeks. They say
  nothing yet about transfer to another building.

## Reproduce

```bash
pip install "open-fdd[ml]"          # "open-fdd[ml-copod]" adds the COPOD row (pyod, numba)
open-fdd-ml download                 # about 240 MB compressed transferred, cached
open-fdd-ml benchmark --out lbnl-ahu-benchmark-results.md --json lbnl-ahu-benchmark.json
# a subset of methods: --methods rules,grey_box,ocsvm
```

The run is deterministic (seed 0) and took about 3 minutes on a workstation CPU, most of it the rolling MAD. The same
code runs on the committed fixture in `tests/test_ml_fdd.py`. The table above was produced on Linux (Python 3.13) and
reproduced row for row on Windows (Python 3.14) before merge.

## Use it on your own unit

```bash
open-fdd-ml detect ./AHU_1 --method grey_box --train-until 2026-06-01 --out ./ahu1_ml
open-fdd-ml detect ./AHU_1 --method pca --train ./AHU_1_known_good --out ./ahu1_ml_pca   # + contributions.png
```

`AHU_1` is the device folder `open-fdd-anomaly` reads (`history_wide.csv` in SI and `column_map.json`). Train only on
a period you know was healthy.

## References

- Granderson, J., Lin, G., et al. (2022). LBNL FDD Data Sets, single-duct AHU. DOI 10.25984/1881324.
- Frank, S., Lin, G., Jin, X., Singla, R., Farthing, A., Granderson, J. (2019). A performance evaluation framework for
  building fault detection and diagnosis algorithms. *Energy and Buildings* 192: 84-92. DOI 10.1016/j.enbuild.2019.03.024.
- Wang, S., Xiao, F. (2004). AHU sensor fault diagnosis using principal component analysis method. *Energy and
  Buildings* 36(2): 147-160. DOI 10.1016/j.enbuild.2003.10.002.
