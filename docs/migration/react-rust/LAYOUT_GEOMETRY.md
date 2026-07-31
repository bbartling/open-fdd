# Layout geometry — P1-M3-01

Numeric CSS measurements for the React parity shell. Streamlit has no checked-in
theme; geometry targets the default wide Streamlit frame plus documented React tokens.

| Token / region | Value | Notes |
|---|---|---|
| `--sidebar-width` | `21rem` (336px @ 16px root) | Matches Streamlit default sidebar (~21rem) |
| `--sidebar-width-collapsed` | `3.25rem` | Icon/short-label rail |
| `--header-height` | `3.5rem` | Title + optional caption |
| `--section-tabs-height` | `2.75rem` | Horizontal main sections |
| `--content-max-width` | `1200px` | Main column clamp |
| `--content-gutter` | `1.5rem` | Page padding |
| `--page-caption-gap` | `0.35rem` | Title → caption rhythm |
| `--radius-sm` / `--radius-md` | `0.25rem` / `0.5rem` | Cards, alerts |
| Active sidebar indicator | `3px` teal left border | Visual active cue |
| Breakpoint stack | `max-width: 768px` | Sidebar → horizontal wrap |

## Section order (must match `REQUIRED_MAIN_SECTIONS`)

1. Overview  
2. Data Model  
3. Run Rules  
4. Results by Category  
5. FDD Plots  
6. RCx Plots  
7. Metering  
8. WattLab  

Source: `services/ui/app/dashboard_contract.py`.

## Visual evidence

Playwright screenshot capture deferred to controlled M3 visual harness; this PR
locks geometry tokens + interaction tests for collapse/section order.
