# React best practices (canonical review standard)

This is the review standard for the product SPA (`frontend/web`). Presentation stays in React. Data and jobs stay on the NF portal API and CSV ingest (`central` Rust `/api`). Read [`../skills/openfdd-react-spa/SKILL.md`](../skills/openfdd-react-spa/SKILL.md) for product screen rules (Overview tables, RCx presets, quiet copy). This document is how that code is written.

The SPA does not grow a client for BACnet, Haystack, Modbus, fieldbus, or a second historian. MQTT, edge, and dual-write UI that still ships is archive-bound; do not extend it. Archived code lives in `archive/` and is never built.

Review as a frontend architect and React performance engineer. Find anti-patterns, rendering bottlenecks, state bugs, and non-idiomatic code. For each issue give a brief why and a concrete refactor snippet.

Lead with the answer. Use headers and bullets.

## 1. Rendering and performance

- Inline objects, arrays, or functions that force child re-renders. Suggest `useMemo` / `useCallback` where a child is memoized or the identity is a dependency. Do not wrap every handler.
- Missing or unstable `key` props. Index keys on lists that reorder, insert, or filter are defects. A static list that never reorders may use an index only with an `eslint-disable-next-line` and a one-line reason.
- Heavy transforms in the render body (sorts, filters, Plotly trace builds) belong in `useMemo` keyed by the data they read.
- Plotly pages load with `React.lazy` and a `Suspense` fallback (`Reports`, `RCx`, `Inspect`, `Metering`). Chart option objects passed into `PlotlyHost` are memoized in the module or with `useMemo`, not rebuilt as a fresh literal on every parent render when the figure data did not change.
- Large tables window their rows (the series preview cap is the product control). Add list virtualization when a single table renders an unbounded historian window. Do not virtualize a table that already slices to a fixed N.

## 2. State and hooks

- Derived state: do not copy props into state with `useEffect` just to render them. Render the prop, or derive it during render.
- Deeply nested state or stored values that can be a local variable. Do not put a constant, a route param, or a value computed from other state into `useState`.
- `useEffect` that subscribes, starts a timer, or opens an `EventSource` returns a cleanup that removes the listener, clears the timer, and closes the stream.
- `react-hooks/rules-of-hooks` and `react-hooks/exhaustive-deps` are errors. An intentional omission uses `eslint-disable-next-line` with the reason on the same line. Do not "fix" a dependency by widening it if that retriggers a fetch loop; disable with the reason instead.

## 3. Architecture and API integration

- Fetch races: a fetch started in `useEffect` takes an `AbortSignal` (pass `init.signal` into `apiFetch`) or ignores the result in cleanup. `apiFetch` already forwards `RequestInit`.
- God components split into a focused component or a hook when one function owns loading, mutation, and a large render tree and both pieces can be tested apart. Do not split a component only to satisfy a line count.
- Prop drilling through several layers that all ignore the value moves to existing React context or to the route/session hook that already owns that value. Do not add a new state library for one value.
- Route-level views sit in `RouteErrorBoundary` so one page exception does not blank the router. The boundary tells the operator to reload. It does not invent a second app shell.

## 4. Modern practices and safety

- TypeScript is `strict` (`frontend/web/tsconfig.app.json`: `strict`, `noUnusedLocals`, `noUnusedParameters`, `noFallthroughCasesInSwitch`). `any` is an error (`@typescript-eslint/no-explicit-any`). A CSS custom property uses a `React.CSSProperties` assertion, not `as any`. Unsafe `as` assertions on API payloads are defects; parse from `unknown` or type the `apiFetch<T>` call.
- Semantic HTML and accessibility: `jsx-a11y` recommended rules are errors. `onClick` on a `div` needs a role and a keyboard handler, or the element should be a `button`.
- Direct DOM access that bypasses React (`document.getElementById`) is an error outside `main.tsx`. The root mount is the exception (`eslint-disable-next-line` plus the reason). A download may use `document.createElement("a")` because the browser download API is not a React render. Do not use that pattern to poke at page nodes. Refs and `querySelector` on a ref are for focus within a widget the component owns.
- `dangerouslySetInnerHTML` is forbidden (`react/no-danger`) unless the string was sanitized and the disable comment names the sanitizer. Product copy is React text nodes.
- No secrets in the client bundle. Tokens live in `sessionStorage` via the auth API. Do not inline broker passwords, JWT secrets, or admin passwords into `frontend/web`.
- New components ship a Testing Library test next to the module when they own behavior (not a static markup snapshot). Cover the interaction the component adds.
- Each data view has a loading, empty, and error state. Reuse `InlineAlert` for the error and the actionable empty state. Do not add grey caption paragraphs under section titles.

## Output shape

```markdown
## Findings

### Rendering and performance
- **`path.tsx:line` `Component`** — why this is wrong.
  ```tsx
  // idiomatic replacement
  ```

### State and hooks
### Architecture and API integration
### Modern practices and safety
```

If a section has no findings, write "None."

## Mechanical enforcement

`frontend/web` CI runs `npm run lint` (`eslint .`). Errors fail the job. Warnings do not, so the rules below are `error`.

| Rule | Why |
| --- | --- |
| `react-hooks/rules-of-hooks` | Hooks called conditionally |
| `react-hooks/exhaustive-deps` | Stale effect dependencies |
| `react/jsx-key` | Missing list keys |
| `react/no-array-index-key` | Index keys on lists |
| `react/no-danger` | `dangerouslySetInnerHTML` |
| `@typescript-eslint/no-explicit-any` | Explicit `any` |
| `jsx-a11y` recommended | Semantic HTML and keyboard access |
| `no-restricted-syntax` on `document.getElementById` | DOM writes that skip React |

Tests (`src/**/*.test.ts(x)`) are not under the `getElementById` ban. They may query the document. They still cannot introduce `any` or a missing key.

## Related

- Product screen rules: [`../skills/openfdd-react-spa/SKILL.md`](../skills/openfdd-react-spa/SKILL.md)
- Review skill: [`../skills/openfdd-code-review-rust-react/SKILL.md`](../skills/openfdd-code-review-rust-react/SKILL.md)
- Rust standard: [`RUST_BEST_PRACTICES.md`](RUST_BEST_PRACTICES.md)
