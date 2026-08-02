# Python boundary and model supply chain

## Policy

Open-FDD is not “anti-Python.” It uses Python deliberately for human/agent
engineering and data-science work while removing Python from the supported
production web runtime.

## Allowed zones

### PyPI engineering/oracle package

Keep and publish:

- pandas FDD/analytics oracle and examples;
- `openpyxl` engineering workbooks/ECM spreadsheets;
- notebook helpers and report tooling intended for a workstation;
- characterization fixtures and readable expression cookbook code.

Package metadata must say this is not the production DataFusion runtime.
Optional extras keep pandas/report dependencies out of the base package where
possible. The PyPI contract is versioned and tested independently.

### Offline data science

Allowed activities include EnergyPlus farm preparation, feature research,
training, explainability, grouped validation, notebook reporting, and portable
artifact export. Environments are pinned and produce reproducibility manifests.

### CI compatibility jobs

CI may run Python to validate PyPI, regenerate oracles, render documentation, or
export a portable model. Release runtime images remain Python-free.

## Forbidden production zones

- central, edge, fieldbus, MQTT, MCP, and web runtime dependencies;
- subprocess calls to `python`, notebooks, pandas, or Flask for an API request;
- FastAPI/Flask sidecars as a migration fallback;
- deserializing joblib/pickle in a production service;
- silent callout to PythonAnywhere or a workstation;
- JavaScript copies of authoritative formulas.

## Enforcement

- Architecture script scans manifests, Dockerfiles, compose, code imports,
  commands, and images.
- Clean-host qualification uses a host without Python.
- Container inspection rejects Python binaries/site-packages in target images.
- Integration tests stop the oracle environment and prove the product fails
  explicitly only for offline-only tasks, not online workflows.
- Network policy prevents runtime callout to prototype services.

## Training-to-serving flow

```text
versioned IDF/EPW + scenario design
  -> digest-pinned external EnergyPlus runs
  -> immutable raw outputs + run manifest
  -> versioned transform/feature compiler
  -> grouped train/validation/test datasets
  -> candidate search + physics/persistence baselines
  -> model card + domain policy + conformance fixtures
  -> portable non-executable artifact
  -> Rust import validation and parity qualification
  -> human approval
  -> atomic activation
  -> observe drift/errors
  -> revoke/rollback/retrain
```

## Artifact requirements

The bundle is self-contained and path-independent:

- no developer absolute paths;
- portable model artifact;
- schema/model release manifest;
- exact ordered features and outputs;
- categorical vocabulary and preprocessing;
- units and missing-value policy;
- grouped-split metrics and per-target thresholds;
- training domain and OOD policy;
- data/source/toolchain hashes;
- conformance JSONL with expected feature/output vectors;
- licenses, SBOM, and optional signature.

## Model acceptance

A candidate cannot activate merely because it loads. It must:

- match the frozen oracle or approved retrained behavior;
- meet global, peak-window, worst-group, and per-target metrics;
- beat named baselines where the product claim requires it;
- pass physical plausibility and invalid-input tests;
- produce reliable domain/coverage warnings;
- fit latency/memory/concurrency budgets;
- be compatible with the selected twin/scenario schemas;
- have an approved status and rollback predecessor.

Vibe 21 v2 at 360 rows/three days remains a source fixture, not the production
candidate. The 40-day facility-only v1 evidence is stronger for facility kW;
the multi-target replacement must be rerun at adequate coverage.

## Retraining and drift

Measured BAS data, when legally and technically available, is stored separately
from synthetic data with provenance and consent. Evaluation reports synthetic
holdout and real-site holdout separately. A synthetic model remains labeled
`ENERGYPLUS_SIMULATED`; G14 monthly calibration does not imply hourly truth.

Runtime monitoring records model release, domain status, feature coverage,
latency, and aggregate error where truth later becomes available. Drift never
triggers automatic unreviewed retraining or activation.

