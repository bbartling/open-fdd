# AHU workshop CSVs and rules

This folder holds two sample trend exports (`AHU7.csv`, `RTU11.csv`) and a small **YAML rule pack** under `rules/` (`sensor_bounds`, `sensor_flatline`, `sat_operating_band_when_fan_on`).

## One-command demo workspace

From the **repository root**:

```powershell
python scripts/bootstrap_ahu_examples.py --reset
```

The pack is **declarative** (`site_profiles.yaml` next to this README): CSV paths, equipment, and `brick_mappings` live in YAML — no workshop-specific logic in Python. Add new sites or files by editing that pack (or add another YAML under `examples/` and point the bridge at it).

This will:

- Use an isolated store under `examples/AHU/.openfdd_demo` (override with `--desktop-dir` if you want).
- Purge old Feather data and **empty the JSON model** when `--reset` is set.
- Apply `site_profiles.yaml`: two sites, ingest, equipment, BRICK mapping, TTL sync, and copy workshop rules into `…/rules/ahu_vav/`.

### Bridge API (for chat / OpenClaw later)

- `GET /assistant/readiness` — JSON with `message_markdown`, `deep_links`, `suggested_actions`, and a yes/no follow-up stub for the human.
- `POST /assistant/apply-site-profiles` — body `{"profiles_yaml": "<absolute path under examples/>", "reset": true}`. Same effect as the bootstrap script; **paths must stay under** the repo `examples/` tree.

MCP RAG (when action tools are enabled) exposes `bridge_readiness` and `bridge_apply_site_profiles` that proxy these routes.

## View plots with FDD

1. Point the bridge at the same data directory you used for bootstrap:

   ```powershell
   $env:OFDD_DESKTOP_DATA_DIR = "C:\path\to\open-fdd\examples\AHU\.openfdd_demo"
   open-fdd-desktop-bridge
   ```

   (Adjust the path to your clone; on Unix use `export OFDD_DESKTOP_DATA_DIR=…`.)

2. Open the **Plots** page in the desktop UI, pick **AHU7 workshop demo** or **RTU11 workshop demo** in the site selector.

3. Use **Load Site Data (Feather)** for raw trends, or **Load + FDD overlay** to fetch the same window **with fault columns** in one request (uses the **Run / backfill** panel’s source, join mode, time window, and rule file filter).

4. Optionally click **Run FDD backfill** for a text summary; overlay is usually enough for visualization.

## Rules path for automation

The bridge also accepts an absolute rules directory under the repo **`examples/`** tree (e.g. `…/examples/AHU/rules`) for `rules_path` on `/rules/run` and `/plots/fdd-frame`, so you can iterate on workshop YAMLs without copying them to the managed pack.
