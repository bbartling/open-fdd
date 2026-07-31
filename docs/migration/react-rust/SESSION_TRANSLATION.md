# Session translation — P1-M3-03

Maps Streamlit `st.session_state` shareable selections to React URL + local drafts.

| Streamlit key | React destination | Notes |
|---|---|---|
| `main_section` | Route + `?section=` (reports plots/metering) | SectionTabs |
| `openfdd_job_id` | `?job=` | JobsPage select |
| `selected_equipment` | `?eq=` | MappingPage (M4 expands) |
| `active_site` / `building_id` | `?site=` | reserved for M4 site picker |
| `wattlab_studio_page` | `?wl=` | WattLabPage radio |
| Form drafts (mapping notes, etc.) | `sessionStorage` `openfdd.formDraft.*` | Never sole SoT for jobs/mapping |
| Durable mapping / job meta | Rust `/api/jobs*`, `/api/fdd/session-config` | M4+ |

## Guarantees

- Refresh/back/forward restore URL-backed selections.
- No critical domain state exclusively in `localStorage`.
- Dirty drafts trigger `beforeunload` when `useDirtyFormWarning` is wired.
