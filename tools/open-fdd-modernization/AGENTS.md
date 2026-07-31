# Streamlit → React Parity Guide

## Mission

Preserve the existing Streamlit app as the behavioral and visual reference while
building a React client that a normal user cannot distinguish from it. Keep
domain-specific Python calculations in a separate FastAPI service. Treat parity
as a measured engineering requirement, not a redesign exercise.

For porting or synchronization work, also use
`skills/streamlit-to-react/SKILL.md`.

## Repository map

```text
app.py                         Streamlit reference
requirements.txt               Streamlit dependencies
backend/main.py                FastAPI and HVAC calculations
backend/requirements.txt       API dependencies
backend/Dockerfile             API container
frontend/src/App.jsx           React composition and behavior
frontend/src/styles.css        Visual parity styling
frontend/package.json          React/Vite dependencies
frontend/Dockerfile            UI container
docker-compose.yml             Two-sidecar deployment
```

Do not move authoritative calculations into React merely to make a widget
update easier. Do not delete or redesign `app.py` unless explicitly requested.

## Source-of-truth hierarchy

Use evidence in this order:

1. Running Streamlit app at the target viewport and state.
2. Streamlit source, CSS, theme configuration, and assets.
3. Browser measurements and same-viewport screenshots.
4. Defaults from the installed Streamlit version.
5. Visual inference.

Prefer the running reference when evidence conflicts. Document intentional
differences instead of silently accepting them.

## Required architecture

```text
Streamlit reference ── visual/behavioral specification

React client ── HTTP/JSON ── FastAPI ── Python domain functions
```

### React owns

- Layout, components, tabs, responsive behavior, and visible UI state.
- Form state, selections, open/closed state, and transient feedback.
- Loading, empty, disconnected, validation, and error presentation.
- Client downloads when no server authority is needed.

### FastAPI owns

- HVAC and other domain calculations.
- Input validation, data access, file parsing, and durable project state.
- Report generation that depends on Python libraries.
- Stable JSON contracts usable by multiple clients.

### Streamlit owns

- The reference workflow until React parity is accepted.
- A runnable comparison target.
- No new duplicated business logic.

Prefer extracting calculation functions into importable Python modules used by
both Streamlit and FastAPI. Avoid copying formulas between `app.py`,
`backend/main.py`, and TypeScript.

## Migration workflow

### 1. Establish a baseline

- Run Streamlit without changing it.
- Record Streamlit/Python versions, viewport, theme, dataset, and scenario.
- Verify the baseline has no visible exceptions.
- List every page, tab, sidebar section, expander, dialog, and download.
- Save representative inputs and outputs.

If the reference does not run, fix or document that failure before porting.

### 2. Inventory the app

Cover:

- Navigation and page hierarchy.
- Sidebar controls and ordering.
- Labels, defaults, min/max/step, formats, help, and disabled conditions.
- `st.session_state` keys, callbacks, forms, fragments, and rerun behavior.
- Metrics, tables, charts, maps, alerts, status, and progress elements.
- Uploads, downloads, caching, custom components, and custom HTML/CSS.
- Every branch that adds, removes, or reorders UI.

Map each element to a React component and identify its state/data owner.

### 3. Capture a visual specification

For each important state, record:

- Viewport dimensions and device scale.
- Sidebar width, content max-width, gutters, gaps, and vertical rhythm.
- Rectangles for hero, tabs, metrics, charts, tables, and controls.
- Computed font family, size, weight, and line height.
- Backgrounds, borders, radii, shadows, and state colors.
- Hover, focus, active, disabled, selected, loading, and error states.

Measure the DOM when possible. Use screenshots for comparison, not as the only
source for measurable properties.

Omit Streamlit product chrome unless requested: deploy button, runner menu,
connection status, and framework decorations.

### 4. Define API contracts

- Add golden tests before refactoring calculations.
- Define Pydantic models with bounds matching Streamlit widgets.
- Return structured, display-neutral values rather than HTML.
- Provide `/api/health`.
- Use narrow development and production CORS origins.
- Keep units and raw versus rounded values explicit.
- Return field-specific validation errors.
- Use jobs/polling for work too long for a normal request.

### 5. Build the static React shell

Implement in this order:

1. Font and page background.
2. Sidebar.
3. Main max-width and gutters.
4. Hero/header.
5. Tabs and active indicator.
6. Content grids and vertical rhythm.
7. Metrics, chart/table frames, buttons, and controls.
8. Footer and transient feedback.

Match the canonical desktop viewport before adding responsive rules.

### 6. Implement interaction parity

Preserve:

- Default values and option order.
- Slider range, step, value label, and formatting.
- Immediate versus submitted updates.
- State persistence across tabs.
- Conditional visibility.
- Button loading and disabled behavior.
- Alert/toast text, timing, and location.
- Download filename, MIME type, headers, and column order.
- Keyboard focus and tab order.

Streamlit reruns top-to-bottom after most interactions. Reproduce the intended
result of that rerun, not unnecessary full-page work.

### 7. Connect FastAPI

- Debounce continuous controls and cancel stale requests.
- Keep the last valid result during short refreshes when appropriate.
- Show explicit API failure and recovery states.
- Do not silently substitute fake results in production.
- Permit local JS fallback calculations only for labeled demos.
- Configure the API URL through environment or same-origin `/api`.

### 8. Verify

Run:

- Python compile/lint/tests.
- FastAPI nominal, boundary, and invalid contract tests.
- React production build and lint/type checks.
- HTTP checks for HTML, assets, health, API requests, and CORS.
- Browser console checks.
- Interaction tests for all tabs and control families.
- Same-viewport visual comparison.

Fix runtime errors before pixel differences. Fix global fonts and geometry
before tuning individual controls.

## Visual parity rules

- Reuse the same font files when licensing permits.
- Centralize measured values as CSS custom properties.
- Preserve content order, wording, capitalization, punctuation, and formatting.
- Match empty space as carefully as visible components.
- Match table headers, cells, borders, scrolling, and formatting.
- Match chart domains, ticks, lines, fills, annotations, margins, and legends.
- Do not add cards, icons, animation, copy, or decoration absent from reference.
- Use semantic, accessible HTML while matching visible output.
- Responsive work must not alter the graded desktop layout.

## State translation

| Streamlit state | Destination |
|---|---|
| Current tab, select, open panel | React local or URL state |
| Cross-panel temporary selection | Lifted state/context/store |
| Shareable filters | URL search parameters |
| Calculation input | React form state → API request |
| Calculation result | Query/cache state |
| Durable project configuration | Authoritative backend persistence |
| Authentication/authorization | Server-side validation/session |

Keep state close to its consumers; do not create one global store for every
`st.session_state` key.

## Calculation rules

- Follow the repository's declared target backend. Python is authoritative only
  when the product intends to retain it.
- For a Python-retirement program, freeze Python as a characterization oracle
  and implement the new runtime in the target backend (for Open-FDD: Rust plus
  DataFusion SQL). Do not add a FastAPI bridge.
- Extract or characterize pure behavior before adding replacement routes.
- Preserve representative golden inputs/outputs.
- Validate on the server even when React validates.
- Distinguish raw values from presentation rounding.
- Never silently fall back from the target computation engine to the oracle.
- Never claim engineering validity for intentionally illustrative calculations.

## Minimum test coverage

- Health and nominal calculation.
- Minimum, maximum, and invalid calculation inputs.
- Initial React render with API available.
- Explicit React error state with API unavailable.
- Every primary tab.
- Representative select, slider, checkbox, and action button.
- Download filename and headers.
- Project/scenario changes updating visible context.
- No uncaught browser errors.

Add screenshot baselines at the canonical desktop size for high-fidelity work.
Mask only genuinely nondeterministic content.

## Service and container rules

- Keep frontend and backend dependency files and Dockerfiles independent.
- Test a production static build, not only Vite HMR.
- Inject the browser-reachable API URL or reverse proxy `/api`.
- Never put secrets in frontend build variables.
- Add API health checks and document ports.
- Remember: Docker service names are not browser-resolvable by default.

## Common failures

- **Blank React page:** check HTML/JS responses, browser errors, root element,
  `createRoot`, hooks, module factories, asset paths, and production build.
- **No calculations:** test API health, CORS, URL, payload, and response shape.
- **Visibly close but wrong:** measure font, sidebar, main padding, and primary
  color before adjusting individual components.
- **Too many requests:** debounce sliders and abort stale requests.
- **State resets:** lift only the state that must survive unmounting.
- **Docker UI cannot call API:** use a host-reachable or proxied URL.
- **Dev works, production blank:** check build variables, base path, and assets.

## Definition of done

Do not call the port complete until:

- Every inventoried workflow is migrated or explicitly waived.
- React and the authoritative backend run independently.
- Production React build and API tests pass.
- Reference and React are compared at identical viewport/state.
- Critical interactions and downloads work.
- No uncaught browser errors remain.
- Intentional differences and verification limits are documented.
- Local and container run instructions are current.

## Open-FDD modernization program

When working on the Open-FDD Streamlit-to-React and Python-exit program, also
read these files in order:

1. `docs/open-fdd-modernization/README.md`
2. the current phase document
3. `docs/open-fdd-modernization/TEST_PARITY_AND_ACCEPTANCE.md`
4. `docs/open-fdd-modernization/AGENT_EXECUTION_SYSTEM.md`
5. the matching prompt pack when starting a bounded PR

For that program:

- React owns presentation and browser interaction state.
- `services/central` and the Rust workspace own APIs, jobs, persistence,
  ingestion, exports, and orchestration.
- `crates/fdd_sql`, `crates/fdd_rules`, and `sql_rules/` own deterministic
  telemetry analytics and FDD.
- Python/Streamlit is a Phase 1 oracle/fallback, not the new backend.
- Phase 2 removes production Python only after parity, canary, rollback, and
  deletion gates.
- Phase 3 edge/BACnet/MQTTS work is planning-only until separately authorized.
