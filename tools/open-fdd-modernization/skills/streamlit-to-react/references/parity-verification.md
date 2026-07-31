# Parity verification

## Contents

1. Baseline setup
2. Layered checks
3. Visual comparison
4. Interaction matrix
5. Failure diagnosis
6. Acceptance record

## Baseline setup

Use identical viewport, scale, zoom, project, dataset, scenario, widget values,
tab, locale, timezone, and font-loading state. Wait for charts and async
calculations before capture.

## Layered checks

1. Reference fixture/oracle repeatability.
2. API health, version, and capabilities.
3. Nominal, invalid, unauthorized, conflict, and cancellation API requests.
4. Contract compatibility and generated/checked TypeScript types.
5. Authoritative backend unit/integration tests.
6. React production build.
7. UI HTML and JS/CSS asset responses.
8. Browser initialization and console errors.
9. Raw semantic/numeric/temporal result comparison.
10. Initial content and geometry.
11. Interactions, keyboard, and accessibility.
12. Artifact/download comparison.
13. Screenshot comparison.
14. Production-like container, restart, and rollback checks.

Do not tune pixels while runtime errors or wrong data remain.

Classify parity as EXACT, NUMERIC, TEMPORAL, SEMANTIC, VISUAL, INTERACTION,
ARTIFACT, PERFORMANCE, or SECURITY. Record denominators, tolerances, fixture
hashes, source versions, skipped branches, and every mismatch classification.

## Visual comparison

Measure sidebar, main content, hero, tabs, active indicator, metric cards,
primary chart, tables, and major vertical positions. Compare computed font,
color, padding, gaps, borders, radii, shadows, and control dimensions.

Fix differences in this order:

1. Fonts.
2. Page/sidebar geometry.
3. Grids and vertical rhythm.
4. Component sizing.
5. Colors and borders.
6. Chart internals.
7. Micro-alignment.

## Interaction matrix

| Area | Checks |
|---|---|
| Navigation | Selection, persistence, URL if applicable |
| Selects | Default, options, disabled state |
| Sliders | Min, max, step, value, request timing |
| Checkboxes | Default, label click, keyboard |
| Buttons | Enabled, disabled, loading, success, failure |
| Tables | Headers, formatting, scroll, empty state |
| Charts | Data, hover, legend, resize |
| Downloads | Filename, MIME, headers, representative values |
| Feedback | Text, timing, position |
| API failure | Visible recovery; no fake result |

Also test keyboard tab order and visible focus.

## Failure diagnosis

### Blank page

1. Confirm HTML and referenced JS return 200.
2. Inspect browser errors.
3. Confirm the root element exists.
4. Confirm React/ReactDOM initialize to objects, not loaders or factories.
5. Confirm `createRoot` and hooks are functions.
6. Test the production bundle separately from HMR.
7. Check base paths and asset URLs.

### Layout is close but wrong

1. Confirm the same font loaded.
2. Compare sidebar width.
3. Compare main padding/max-width.
4. Compare Streamlit primary color.
5. Check zoom and device scale.
6. Fix parent grids before individual children.

### Results drift

1. Compare raw payloads.
2. Compare units.
3. Compare timestamps, timezone, sampling grid, and missing values.
4. If Python remains authoritative, confirm Streamlit and FastAPI use the same
   function.
5. If Python is being retired, compare the new backend to the normalized frozen
   oracle and verify the new runtime does not invoke Python.
6. Compare rounding only after raw values match.
7. Check stale/out-of-order requests.
8. Classify the mismatch; UNKNOWN blocks acceptance.

### Development works, production fails

1. Run the production build locally.
2. Confirm environment variables.
3. Confirm static-server fallback behavior.
4. Confirm the API URL is browser-reachable.
5. Confirm CORS or reverse proxy behavior.

## Acceptance record

Record reference/React versions, viewports, scenarios, commands, screenshot
locations, fixture hashes, contract/backend versions, exact test denominators,
tolerances, mismatch classifications, intentional differences, untested
branches, production image digests, rollback result, and user acceptance.

For multi-phase Python-removal programs, use the expanded gates in
`docs/open-fdd-modernization/TEST_PARITY_AND_ACCEPTANCE.md`.
