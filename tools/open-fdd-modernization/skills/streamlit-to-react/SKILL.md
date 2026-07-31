---
name: streamlit-to-react
description: Port or synchronize a Streamlit application to a visually faithful React frontend backed by a stable service contract. Use for Streamlit-to-React migrations, pixel-parity recreations, extracting calculations behind Python/FastAPI or Rust APIs, translating st.session_state and widgets into React state, reproducing tabs/sidebars/charts/tables/downloads, preparing separate frontend/backend containers, retiring Python when required, or diagnosing parity gaps and blank React builds.
---

# Streamlit to React

## Goal

Reproduce the user-observable Streamlit experience in React while keeping
domain logic authoritative behind a versioned API. Preserve the running
Streamlit app as the comparison target until parity is accepted.

Select the backend target from the repository's product goal:

- If Python remains part of the product, reuse authoritative Python functions
  behind FastAPI.
- If Python is being retired, use Python only as a frozen characterization
  oracle and build the new contract in the target backend (for example Rust).

Never introduce a Python sidecar into a product whose stated goal is a
Python-free runtime.

### Open-FDD binding (this monorepo)

For `bbartling/open-fdd` Phase 1+, **always** use the Rust retirement path:

- Backend = `services/central` `/api/*` (not FastAPI).
- Compute = DataFusion / `sql_rules/`.
- Agent OS = `openfdd_agent_spec/` +
  `tools/open-fdd-modernization/AGENT_SKILL_BRIDGE.md`.
- Wrapper skill =
  `openfdd_agent_spec/skills/openfdd-streamlit-to-react/SKILL.md`.

When references mention FastAPI persistence or sidecars, substitute central
Rust jobs/routes.

## Read references selectively

- Read [component-mapping.md](references/component-mapping.md) when inventorying
  Streamlit elements or deciding React equivalents.
- Read [sidecar-architecture.md](references/sidecar-architecture.md) when
  extracting calculations, defining FastAPI routes, handling state, or preparing
  containers.
- Read [parity-verification.md](references/parity-verification.md) before visual
  acceptance, interaction testing, or diagnosing a mismatch.

If the repository contains `AGENTS.md`, read and follow it before editing.

## Workflow

### 1. Inspect before editing

1. Locate Streamlit entry points, pages, theme config, CSS, assets, tests,
   requirements, and existing frontend/backend directories.
2. Run Streamlit and establish a known viewport and dataset.
3. Record navigation, controls, defaults, branches, outputs, uploads, downloads,
   and visible errors.
4. Search for `st.session_state`, callbacks, forms, fragments, cache decorators,
   custom components, HTML injection, and calculation functions.
5. Preserve unrelated user changes.

Do not begin by choosing a React component library. First determine what the
reference actually renders.

### 2. Build a parity contract

Create an inventory with:

- Streamlit location and control.
- Visible label and position.
- Default, min, max, step, format, and disabled conditions.
- State key and rerun behavior.
- React component and state owner.
- API dependency.
- Required visual and interaction checks.

Mark Streamlit chrome that should be omitted, such as deploy/menu controls.
Record intentional product differences and obtain agreement when needed.

### 3. Measure the reference

When browser inspection is available:

- Capture viewport and element rectangles.
- Read computed fonts, colors, padding, gaps, borders, radii, and shadows.
- Capture representative screenshots after measurements.
- Observe hover, focus, active, disabled, loading, empty, and error states.

When inspection is unavailable, use explicit app CSS, theme configuration,
installed-version conventions, and source order. State the limitation; do not
invent measured precision.

### 4. Separate domain logic

1. Add golden tests for representative calculations and error behavior.
2. Define a versioned request/response/error contract matching widget bounds.
3. Implement validation and computation in the selected authoritative backend.
4. Expose structured `/api/...` routes and `/api/health`.
5. Configure authentication and expected CORS origins.
6. Keep units, timestamps, missing values, and raw/rounded values explicit.
7. When Python remains, reuse the same functions from Streamlit and FastAPI.
8. When Python is being retired, compare the replacement to normalized Python
   oracle artifacts and prohibit Python in the new runtime.

Never translate authoritative calculations to TypeScript merely to avoid an API
call. Allow JS fallbacks only for explicitly labeled prototypes.

### 5. Recreate the static shell

Implement in order:

1. Global font and background.
2. Sidebar width, padding, and fixed/scroll behavior.
3. Main max-width and gutters.
4. Hero/header.
5. Tabs and active indicator.
6. Content grids and vertical rhythm.
7. Metrics, chart/table frames, buttons, and controls.
8. Footer and transient feedback.

Centralize measured values as CSS variables. Match the canonical desktop
viewport before adding responsive rules.

### 6. Translate interactions

- Use controlled inputs with identical defaults, bounds, steps, and formats.
- Preserve values that should survive tab changes.
- Translate Streamlit rerun outcomes into targeted state/effect updates.
- Debounce high-frequency requests and abort stale ones.
- Provide explicit loading and error behavior.
- Preserve text, filenames, table columns, chart semantics, and toast timing.
- Maintain keyboard focus and semantic HTML.

Do not interpret parity as permission to redesign.

### 7. Verify in layers

Run all applicable checks:

1. Reference/oracle tests when applicable.
2. Authoritative backend unit, contract, and validation tests.
3. React production build and lint/type checks.
4. HTTP UI, asset, API health, and CORS checks.
5. Browser initialization and console-error inspection.
6. Interaction tests across every primary tab.
7. Same-viewport screenshot or overlay comparison.

Fix runtime errors before visual differences. Fix global geometry and typography
before tuning individual controls.

### 8. Package independently

- Keep frontend and backend dependencies separate.
- Provide independent Dockerfiles.
- Use environment-based API configuration or reverse-proxied `/api`.
- Test the production static build, not only HMR.
- Document ports, health endpoints, and container startup.

## Guardrails

- Do not delete the Streamlit reference during migration.
- Do not duplicate the same business formula in Python and TypeScript.
- Do not add a Python production path when the target architecture is Rust-only.
- Do not silently fall back from the target engine to the reference oracle.
- Do not claim pixel parity without a same-viewport comparison.
- Do not use screenshots alone when DOM measurements are possible.
- Do not vendor Streamlit's internal React bundles for production. Permit a
  documented local preview adapter only when normal packages are unavailable.
- Do not hide API failures behind fake data in production.
- Do not let responsive changes alter the graded desktop layout.

## Completion report

Report:

- React and API locations.
- Migrated workflows.
- Calculations retained in Python.
- Tests/builds and results.
- Live URLs when running.
- Intentional differences and verification limitations.
