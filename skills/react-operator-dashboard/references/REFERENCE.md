# React dashboard — reference

Legacy app: `apps/desktop-ui/` (retired).

## Routes (`App.tsx`)

| Path | Page |
|------|------|
| `/site-management` | SiteManagementPage |
| `/csv-import` | CsvImportPage |
| `/weather` | WeatherDriverPage |
| `/bacnet-tools` | BacnetDriverPage |
| `/rule-setup` | RuleSetupPage |
| `/data-model` | DataModelPage |
| `/data-model-testing` | DataModelTestingPage |
| `/plots` | PlotsPage |
| `/data-maintenance` | DataMaintenancePage |
| `/ml-lab` | MlLabPage |
| `/ai-agent` | AiAgentChatPage |
| `/system` | SystemResourcesPage |

## Env

- `VITE_DESKTOP_BRIDGE_BASE` — default bridge URL.
- `localStorage` key `ofdd-bridge-base-override` for per-browser override.

## Optional shell

Tauri wrapper lived in `apps/desktop-ui/src-tauri/`; prefer plain Vite unless operator requests desktop packaging.
