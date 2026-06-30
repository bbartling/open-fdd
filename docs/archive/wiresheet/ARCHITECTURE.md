# Open-FDD Wiresheet Architecture (v3.2.2 — shipped; development continues on 3.2.3)

Original visual workflow editor for HVAC supervisory FDD. Inspired by electrical wiresheets and flow-based automation, optimized for Haystack + Arrow + DataFusion.

## 1. Architecture overview

```
Haystack Model ──► Arrow Tables ──► DataFusion SQL ──► Fault Engine ──► Historian / Reports
       ▲                    ▲              ▲
       └──── Wiresheet Studio (React Flow) ─┘
```

| Layer | Stack |
|-------|-------|
| Frontend | React 19, TypeScript, Vite, Tailwind-style tokens, React Flow, TanStack Query, TanStack Table |
| Backend | Rust edge, Arrow, DataFusion, Haystack, JWT, OpenAPI |
| Persistence | `workspace/data/fdd_wires/` JSON graphs, rules, assignments |

## 2. Wireframes (text)

**Studio** — palette | canvas | property panel; toolbar: Save, Validate, CSV Fusion, Haystack, Rules.

**CSV Fusion** (`/csv`) — upload → preview → schema → map → join/merge → SQL preview → save dataset.

**Haystack Model** (`/wiresheet/haystack`) — site tree | validation | preview.

**Rule Mapping** (`/wiresheet/rules`) — rule chain | inputs/outputs | link to SQL FDD.

## 3. Component hierarchy

```
App
└── WiresheetStudioPage
    ├── PageHeader + toolbar
    ├── GlobalSearchBar
    ├── WiresheetPalette
    ├── WiresheetCanvas
    │   └── WiresheetNode
    └── WiresheetPropertyPanel
```

## 4. Page hierarchy

| Route | Page |
|-------|------|
| `/wiresheet` | Studio canvas |
| `/csv` | CSV Fusion |
| `/wiresheet/haystack` | Haystack model shell |
| `/wiresheet/rules` | Rule mapping shell |
| `/fdd-wires` | Redirect → `/wiresheet` |

## 5. API requirements (existing + planned)

| Method | Path | Status |
|--------|------|--------|
| GET | `/api/fdd-wires/graphs/{id}` | ✅ |
| PUT | `/api/fdd-wires/graphs/{id}` | ✅ |
| POST | `/api/fdd-wires/graphs/{id}/validate` | ✅ |
| POST | `/api/fdd-wires/propose-assignments` | ✅ |
| GET | `/api/model/sites` | ✅ |
| POST | `/api/csv/...` | ✅ (CSV workbench) |
| POST | `/api/datasets/...` | 🔜 parquet commit |
| GET | `/api/search/wiresheet` | 🔜 global search index |

## 6. Rust endpoint requirements

- Graph CRUD with site scope (`site_id` query param)
- Validate graph topology against Haystack assignments
- Test graph → DataFusion dry-run
- Dataset registry for CSV Fusion outputs
- Search index over points, rules, graph nodes

## 7. React component tree

See `workspace/dashboard/src/wiresheet/` and `src/pages/Wiresheet*.tsx`.

## 8. State management

- **Local canvas**: React Flow `useNodesState` / `useEdgesState`
- **Server graphs**: TanStack Query (increment 2) with optimistic PUT
- **Site scope**: `useActiveSiteId()` hook
- **AI suggestions**: future Zustand slice + SSE from `/openfdd-agent`

## 9. Folder layout

```
workspace/dashboard/src/
  wiresheet/
    nodeCatalog.ts
    graphAdapter.ts
    WiresheetCanvas.tsx
    WiresheetNode.tsx
    WiresheetPalette.tsx
    WiresheetPropertyPanel.tsx
    GlobalSearchBar.tsx
  pages/
    WiresheetStudioPage.tsx
    WiresheetHaystackPage.tsx
    WiresheetRulesPage.tsx
docs/wiresheet/
  ARCHITECTURE.md
  ROADMAP.md
  ACCEPTANCE.md
```

## 10. Migration strategy

1. Ship Studio shell + CSV plot removal (this PR)
2. TanStack Query for graph load/save
3. Haystack tree integration from `DataModelPage`
4. Rule mapping links to `/api/fdd-rules/*`
5. Deprecate duplicate graph UI in SQL FDD tab

## 11. Accessibility

- Palette/search/property panels use semantic landmarks and labels
- Keyboard: React Flow built-in pan/zoom; tab order on toolbar buttons
- Color accents paired with text labels on nodes
- `sr-only` helpers where needed

## 12. Performance

- Virtualize large CSV previews (TanStack Table)
- Lazy-load React Flow minimap
- Debounce graph PUT (500ms)
- Server-side DataFusion for heavy SQL

## 13. Dark mode

Uses existing `[data-theme="dark"]` CSS variables; wiresheet panels inherit `--panel`, `--border`, `--text`.

## 14. Responsive design

`@media (max-width: 960px)` stacks palette / canvas / props vertically.

## 15. Unit test plan

- `nodeCatalog.test.ts` — palette integrity
- `graphAdapter.test.ts` — round-trip graph ↔ flow
- CSV workbench tests (existing)

## 16. Playwright UI tests (planned)

- Login → open `/wiresheet` → canvas renders
- Add node from palette → appears on canvas
- Save + validate returns OK
- CSV upload flow without plot section

## 17. Acceptance criteria

- [x] CSV tab has no embedded plot (link to `/plot` instead)
- [x] `/wiresheet` loads demo graph from API
- [x] Palette adds nodes; property panel edits label
- [x] Save/validate call existing Rust endpoints
- [x] Nav section "Wiresheet" with Studio, CSV Fusion, Haystack, Rules
- [ ] Full Haystack drag-drop (increment 2)
- [ ] AI-assisted mapping (increment 3)

## 18. GitHub Issues (proposed)

1. Wiresheet: TanStack Query graph persistence
2. CSV Fusion: parquet commit + dataset registry UI
3. Haystack model: drag-drop assignment from tree
4. Rule mapping: runtime status columns
5. Global search: server-side index
6. Playwright wiresheet smoke test

## 19. Implementation roadmap

| Phase | Deliverable |
|-------|-------------|
| 3.2.2a | Studio shell, CSV plot removal, docs (this PR) |
| 3.2.2b | Haystack tree + assignments on canvas |
| 3.2.3 | CSV Fusion SQL preview + dataset save |
| 3.3.0 | AI SQL/join suggestions |

## 20. Incremental PR plan

- **PR A** (this): Wiresheet studio MVP + CSV cleanup + architecture doc
- **PR B**: Haystack model page wired to `/api/model/*`
- **PR C**: Rule mapping with live runtime metrics
- **PR D**: Playwright + TanStack Query refactor

## Design inspiration (internal)

High-level patterns from plugin-style node editors: composable node registry, side property inspector, scoped settings, graph persistence JSON, review/approve workflow. No third-party UI assets or code copied.

## Local dev (WSL)

```bash
# Terminal 1 — edge (if not already running)
./scripts/openfdd_rust_edge_bootstrap.sh --start

# Terminal 2 — dashboard (bind all interfaces for Windows browser)
cd workspace/dashboard
VITE_DEV_HOST=0.0.0.0 npm run dev
```

Open from Windows: `http://localhost:5173/wiresheet` (WSL2 forwards ports) or `http://$(hostname -I | awk '{print $1}'):5173/wiresheet`.

Sign in via `/login` with integrator credentials from `workspace/auth.env.local`.
