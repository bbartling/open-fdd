# Home Assistant integration development reference

> **TODO:** Home Assistant integration has been removed from this project. This doc is kept for reference only; stack/ha_integration and stack/ha_addon no longer exist.

This page summarizes **Home Assistant developer docs** for building and aligning custom integrations. The official site is [developers.home-assistant.io](https://developers.home-assistant.io/); links below point to the canonical paths (structure may change).

Open-FDD’s integration is a **custom integration** living in `stack/ha_integration/custom_components/openfdd/`. It is **not** part of Home Assistant Core; you do **not** fork [home-assistant/core](https://github.com/home-assistant/core) to develop it. Core is for contributions that will be merged upstream; custom integrations are installed via `custom_components/` or HACS.

---

## Open-FDD: what we do and what we don’t

The HA docs often say: “Fork Core, run `script/setup`, run `script.scaffold integration`.” **That path is for contributing an integration into Home Assistant Core.** Open-FDD is a **third-party custom integration**, so we do **not** do any of that.

| You do **not** need to … | Reason |
|--------------------------|--------|
| Fork [home-assistant/core](https://github.com/home-assistant/core) | We are not merging into Core. |
| Run `script/setup` in a Core clone | Our integration is developed outside Core. |
| Run `python3 -m script.scaffold integration` | Scaffold generates code *inside* Core’s `homeassistant/components/`. We already have a full integration in `stack/ha_integration/`. |
| Use `hass -c config` from a Core venv for day-to-day dev | Optional: you can run HA in Docker and copy the integration into `config/custom_components/openfdd/` to test. |

**What we do:**

- **Develop** the integration in this repo: `stack/ha_integration/custom_components/openfdd/` (and tests in `stack/ha_integration/tests/`).
- **Develop** the addon in this repo: `stack/ha_addon/`.
- **Install** by copying into HA’s `config/custom_components/openfdd/` (e.g. via `./scripts/bootstrap.sh --ha-install-integration <config_path>`) or, if you set it up, via HACS from a repo that contains only the integration (see below).
- **Version** the integration in `manifest.json`; the addon gets its version from the main app at build time.

No fork of Home Assistant Core is required.

---

## Optional: separate repo for the integration (and addon)

Right now the integration and addon live **inside the Open-FDD monorepo** (`stack/ha_integration/`, `stack/ha_addon/`). That keeps them in sync with API and version. If you want to **carve them out into their own repo** (e.g. for HACS or a dedicated “Open-FDD for Home Assistant” repo), you can do this:

**Option A — Repo that only ships the integration (HACS-friendly)**  
- New repo, e.g. `open-fdd-ha` or `openfdd-homeassistant`.
- Copy **only** the contents that HA (or HACS) need:
  - Put `stack/ha_integration/custom_components/openfdd/` at the **root** of the repo as `custom_components/openfdd/` (so the repo root has `custom_components/openfdd/manifest.json`, `__init__.py`, etc.).
- HACS can install from that repo: users add the repo in HACS and get `openfdd` in `custom_components/`.
- **Version:** Keep `version` in `manifest.json` in sync (e.g. manual or CI that copies from main Open-FDD release).

**Option B — Repo that ships both integration and addon**  
- Same as Option A, plus add the addon:
  - e.g. `openfdd-addon/` at repo root with the same structure as `stack/ha_addon/` (so `openfdd-addon/openfdd/config.yaml`, `Dockerfile`, etc.).
- Users who run HA OS / Supervised can add the repo as a custom addon repository and install the addon; the integration can still be installed via copy or by adding the same repo to HACS if the repo layout exposes `custom_components/openfdd/`.

**What to avoid**  
- Do **not** put a fork of `home-assistant/core` in that repo. The separate repo should contain only the custom integration (and optionally the addon), not Core.

**Recommendation**  
- If you’re the only maintainer and want minimal overhead, **keeping the integration and addon in the Open-FDD repo** is simpler (one place for code and versions).  
- A **separate repo** is useful if you want HACS one-click install, or a “HA-only” repo for discoverability; then use CI (e.g. on tag in the main repo) to copy `stack/ha_integration/custom_components/openfdd/` (and optionally `stack/ha_addon/`) into the other repo and tag a release there.

---

## Official doc index (bookmarks)

- **Development index (Core):** [development_index](https://developers.home-assistant.io/docs/development_index) — how to build new integrations.
- **Creating your first integration:** [creating_component_index](https://developers.home-assistant.io/docs/creating_component_index) — scaffold, minimum files, manifest.
- **Architecture:** [architecture_index](https://developers.home-assistant.io/docs/architecture_index) — layers and concepts (read this first).
- **Dev environment:** [development_environment](https://developers.home-assistant.io/docs/development_environment) — devcontainer + VS Code or manual (Ubuntu/Debian, macOS, etc.).
- **Devcontainer:** [setup_devcontainer_environment](https://developers.home-assistant.io/docs/setup_devcontainer_environment).
- **Manifest:** [creating_integration_manifest](https://developers.home-assistant.io/docs/creating_integration_manifest).
- **File structure:** [creating_integration_file_structure](https://developers.home-assistant.io/docs/creating_integration_file_structure).
- **Fetching data:** [integration_fetching_data](https://developers.home-assistant.io/docs/integration_fetching_data).
- **Multiple platforms / discovery:** [creating_component_generic_discovery](https://developers.home-assistant.io/docs/creating_component_generic_discovery).
- **Checklist / code review:** [creating_component_code_review](https://developers.home-assistant.io/docs/creating_component_code_review).

If a link 404s, check [www.home-assistant.io/developers](https://www.home-assistant.io/developers/) for the current doc layout.

---

## Development environment

- **Option A — Devcontainer (recommended):** Docker + VS Code + [Remote - Containers](https://code.visualstudio.com/docs/remote/containers). Clone from [Home Assistant Core](https://github.com/home-assistant/core) (or fork), open in VS Code, “Open in Container”. Run task **Tasks: Run Task → Run Home Assistant Core**, then open `http://localhost:8123`. Good for contributing to **Core**; hardware (USB, Bluetooth, Zigbee) is easier on Linux host.
- **Option B — Manual (for custom integrations):** You don’t need a Core clone to develop the Open-FDD integration. Use any Python 3.11+ env and run HA in Docker or install HA Core in a venv. For Core development: clone your fork, `git remote add upstream https://github.com/home-assistant/core.git`, run `script/setup`, then `source .venv/bin/activate` and `hass -c config`.

**Python:** Core currently expects **Python 3.11+** (check [development_environment](https://developers.home-assistant.io/docs/development_environment) for the exact version). Wrong version can make the venv incompatible — remove `.venv` and re-run setup after fixing.

---

## Creating your first integration (minimum)

From the official “Creating your first integration” docs:

1. **Scaffold (Core only):** From a Core repo dev environment:
   ```bash
   python3 -m script.scaffold integration
   ```
   This generates an integration with config flow, config flow tests, and translation stubs. **Custom integrations** don’t use the Core scaffold; they live under `config/custom_components/<domain>/` and must include a **`version`** in `manifest.json`.

2. **Minimum files for a custom integration:**
   - **`manifest.json`** — at least `domain` and `name`; **custom integrations must have `version`**. Example:
     ```json
     {
       "domain": "openfdd",
       "name": "Open-FDD",
       "version": "2.0.2"
     }
     ```
   - **`__init__.py`** — define `DOMAIN` and either:
     - **Sync:** `def setup(hass, config):` that returns `True` on success, or  
     - **Async:** `async def async_setup(hass, config):` that returns `True` on success.  
     Example minimum async:
     ```python
     DOMAIN = "openfdd"
     async def async_setup(hass, config):
         hass.states.async_set("openfdd.world", "ok")
         return True
     ```
   To load without config flow, add `openfdd:` to `configuration.yaml`. For UI setup, add `"config_flow": true` to the manifest and implement a config flow.

3. **Example custom configs:** [example-custom-config](https://github.com/home-assistant/example-custom-config/tree/master/custom_components/) shows custom integrations in `custom_components/`; same architecture as Core, but with `version` in the manifest.

---

## Integration file structure

- **Directory name** = integration **domain** (e.g. `openfdd`).
- **Location:** `<<config>>/custom_components/<domain>/` or Core `homeassistant/components/<domain>/`.
- **Common files:**
  - `manifest.json` — domain, name, version (required for custom), dependencies, config_flow, etc.
  - `__init__.py` — `async_setup` / `async_setup_entry`, registration of platforms, `hass.data[DOMAIN]`.
  - `config_flow.py` — UI config flow (optional but recommended).
  - `const.py` — domain, config keys, etc.
  - `coordinator.py` — `DataUpdateCoordinator` if you poll.
  - Platform modules: `sensor.py`, `binary_sensor.py`, `button.py`, etc.
  - `services.yaml` — if you expose services.
  - `strings.json` / `translations/` — for UI strings.

---

## Manifest

- **Required (custom):** `domain`, `name`, `version`.
- **Optional:** `config_flow`, `dependencies`, `issue_tracker`, `codeowners`, `documentation`, `iot_class`, `requirements`, etc.
- Pin **external dependencies** in `requirements` with versions for reproducibility.

---

## Config flow

- Implement `ConfigFlow` (and optionally `OptionsFlow`) in `config_flow.py`.
- Use `async_step_user` (and optionally `async_step_reauth`) to collect URL, API key, etc.
- Validate by calling your API (e.g. GET /capabilities); on 401/403 retry with Bearer token if the user can provide a key.
- Return `self.async_create_entry(title=..., data={...})` with the config data that will be stored in the config entry and passed to `async_setup_entry`.

---

## Fetching data

- **Push:** Prefer subscriptions / webhooks / WebSocket when the backend supports it (e.g. Open-FDD’s `/ws/events`).
- **Poll:** Use a **DataUpdateCoordinator** to fetch at an interval and share data across entities. Set `always_update=False` to avoid unnecessary updates when data hasn’t changed.
- Open-FDD uses one coordinator (sites, equipment, faults, definitions, capabilities, etc.) and optionally a WebSocket listener to refresh on `fault.*` and `fdd.run.*`.

---

## Devices and entities

- **Device registry:** Create devices with `device_registry.async_get_or_create` (e.g. one “gateway” device per config entry, plus one device per equipment).
- **Entity registry:** Entities are created by platform modules (sensor, binary_sensor, button); link them to the correct device via `device_id`.
- **Areas:** Map your “sites” to HA areas and assign devices to areas via `suggested_area_id` (or the current API) when creating/updating devices.
- **Parent device:** Use `via_device_id` only when the parent device exists (e.g. equipment devices linked to the main gateway device).

---

## Multiple platforms

- Centralize connection/API logic in the component’s `__init__.py` (or a shared module). Store client/coordinator in `hass.data[DOMAIN][entry.entry_id]`.
- Use `async_forward_entry_setups(entry, ["sensor", "binary_sensor", "button"])` to set up platforms; each platform’s `async_setup_entry` receives the same `ConfigEntry` and can read from `hass.data[DOMAIN][entry.entry_id]`.

---

## Checklist (code review / best practices)

- Follow style guidelines (e.g. Black, type hints).
- Add external requirements to `manifest.json` with pinned versions.
- Use Voluptuous (or similar) for configuration validation where applicable.
- Keep API-specific code in a dedicated client module (e.g. `api_client.py`), not scattered in HA code.
- Share data with platforms via `hass.data[DOMAIN]`.
- Start minimal; keep PRs and scope small.
- **Custom integrations:** Always set `version` in `manifest.json`.

---

## Open-FDD alignment

The Open-FDD integration in `stack/ha_integration/custom_components/openfdd/` already follows these patterns:

- **Manifest:** `domain`, `name`, `version`, `config_flow`.
- **Config flow:** URL + API key, validation via GET /capabilities, Bearer on 401.
- **Coordinator:** Single `DataUpdateCoordinator`; optional WebSocket listener for live updates.
- **Devices:** Main gateway device + per-equipment devices; sites → areas; equipment → devices with `via_device` to gateway.
- **Platforms:** `binary_sensor`, `sensor`, `button`; entities attached to the correct equipment device.
- **Services:** Full API exposed as `openfdd.*` services with results as events.

When updating the integration, use the official docs (and the links above) to keep structure, config flow, device/entity model, and manifest in line with Home Assistant’s expectations.
