"""Open-FDD buttons: main device (global) + per-equipment supervisory actions."""

import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Open-FDD buttons: main device + per-equipment (run FDD, BACnet discover, export TTL, refresh)."""
    data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator = data.get("coordinator")
    client = data.get("client")
    entry_id = entry.entry_id
    if not coordinator or not client:
        return

    # Main gateway device buttons
    main_buttons = [
        OpenFDDRunFDDButton(coordinator, client, entry_id),
        OpenFDDBacnetDiscoveryButton(coordinator, client, entry_id),
        OpenFDDExportGraphButton(coordinator, client, entry_id),
        OpenFDDRefreshFaultsButton(coordinator, entry_id),
    ]
    async_add_entities(main_buttons)

    added_eq: set[str] = set()

    @callback
    def _add_equipment_buttons() -> None:
        d = coordinator.data or {}
        equipment_list = d.get("equipment") or []
        points_by_equipment = d.get("points_by_equipment") or {}
        bacnet_map = (entry.options or {}).get("equipment_bacnet_device", {}) or {}
        new_entities: list[ButtonEntity] = []
        for eq in equipment_list:
            eq_id = eq.get("id")
            if not eq_id:
                continue
            eq_id = str(eq_id)
            if eq_id in added_eq:
                continue
            added_eq.add(eq_id)
            site_id = eq.get("site_id")
            name = eq.get("name") or eq_id
            # BACnet device_instance: options override, else infer from first point with bacnet_device_id
            bacnet_device = bacnet_map.get(eq_id)
            if bacnet_device is None and eq_id in points_by_equipment:
                for pt in points_by_equipment[eq_id]:
                    bid = pt.get("bacnet_device_id")
                    if bid is not None and str(bid).strip():
                        try:
                            bacnet_device = int(bid)
                        except (TypeError, ValueError):
                            pass
                        break
            new_entities.append(OpenFDDEquipmentRunFDDButton(coordinator, client, eq_id, name))
            new_entities.append(OpenFDDEquipmentBacnetDiscoverButton(coordinator, client, eq_id, name, bacnet_device))
            new_entities.append(OpenFDDEquipmentExportTTLButton(coordinator, client, eq_id, name, site_id))
            new_entities.append(OpenFDDEquipmentFetchFaultHistoryButton(coordinator, client, eq_id, name, site_id))
            new_entities.append(OpenFDDEquipmentRefreshButton(coordinator, eq_id, name))
        if new_entities:
            async_add_entities(new_entities)

    _add_equipment_buttons()
    entry.async_on_unload(coordinator.async_add_listener(_add_equipment_buttons))


# ----- Main device buttons -----

class OpenFDDButtonBase(CoordinatorEntity, ButtonEntity):
    """Base for Open-FDD buttons on the main device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry_id: str, unique_id_suffix: str, name: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_{unique_id_suffix}"
        self._attr_name = name
        self._attr_device_info = {"identifiers": {(DOMAIN, entry_id)}}


class OpenFDDRunFDDButton(OpenFDDButtonBase):
    """Trigger FDD rule run (main device)."""

    def __init__(self, coordinator, client, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "run_fdd", "Run FDD")
        self._client = client

    async def async_press(self) -> None:
        await self._client.post_job_fdd_run()


class OpenFDDBacnetDiscoveryButton(OpenFDDButtonBase):
    """BACnet Who-Is range (main device)."""

    def __init__(self, coordinator, client, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "bacnet_discovery", "BACnet discovery")
        self._client = client

    async def async_press(self) -> None:
        await self._client.bacnet_whois_range(start_instance=1, end_instance=4194303)


class OpenFDDExportGraphButton(OpenFDDButtonBase):
    """Serialize graph to TTL file (main device)."""

    def __init__(self, coordinator, client, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "export_graph", "Export graph")
        self._client = client

    async def async_press(self) -> None:
        await self._client.data_model_serialize()


class OpenFDDRefreshFaultsButton(OpenFDDButtonBase):
    """Refresh coordinator (main device)."""

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "refresh_faults", "Refresh faults")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()


# ----- Per-equipment buttons -----

class OpenFDDEquipmentButtonBase(CoordinatorEntity, ButtonEntity):
    """Base for per-equipment buttons."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, equipment_id: str, equipment_name: str, unique_suffix: str, name: str) -> None:
        super().__init__(coordinator)
        self._equipment_id = equipment_id
        self._equipment_name = equipment_name
        self._attr_unique_id = f"{DOMAIN}_{unique_suffix}_{equipment_id}"
        self._attr_name = name
        self._attr_device_info = {"identifiers": {(DOMAIN, equipment_id)}}


class OpenFDDEquipmentRunFDDButton(OpenFDDEquipmentButtonBase):
    """Run FDD (per equipment)."""

    def __init__(self, coordinator, client, equipment_id: str, equipment_name: str) -> None:
        super().__init__(coordinator, equipment_id, equipment_name, "equipment_run_fdd", "Run FDD")
        self._client = client

    async def async_press(self) -> None:
        await self._client.post_job_fdd_run()


class OpenFDDEquipmentBacnetDiscoverButton(OpenFDDEquipmentButtonBase):
    """BACnet point discovery to graph for this equipment's device_instance (if configured)."""

    def __init__(self, coordinator, client, equipment_id: str, equipment_name: str, bacnet_device_instance: str | int | None) -> None:
        super().__init__(coordinator, equipment_id, equipment_name, "equipment_bacnet_discover", "BACnet discover")
        self._client = client
        self._bacnet_device = int(bacnet_device_instance) if bacnet_device_instance is not None else None

    async def async_press(self) -> None:
        if self._bacnet_device is not None:
            await self._client.bacnet_point_discovery_to_graph(device_instance=self._bacnet_device, update_graph=True, write_file=True)
        else:
            # No device_instance configured; run whois (user can set options later)
            await self._client.bacnet_whois_range(start_instance=1, end_instance=4194303)


class OpenFDDEquipmentExportTTLButton(OpenFDDEquipmentButtonBase):
    """Export data model TTL for this equipment's site."""

    def __init__(self, coordinator, client, equipment_id: str, equipment_name: str, site_id: str | None) -> None:
        super().__init__(coordinator, equipment_id, equipment_name, "equipment_export_ttl", "Export TTL")
        self._client = client
        self._site_id = site_id

    async def async_press(self) -> None:
        await self._client.get_data_model_ttl(site_id=self._site_id, save=True)


class OpenFDDEquipmentFetchFaultHistoryButton(OpenFDDEquipmentButtonBase):
    """Fetch fault state (active + cleared) for this equipment and fire openfdd_fault_history event."""

    def __init__(self, coordinator, client, equipment_id: str, equipment_name: str, site_id: str | None) -> None:
        super().__init__(coordinator, equipment_id, equipment_name, "equipment_fetch_fault_history", "Fetch fault history")
        self._client = client
        self._site_id = site_id

    async def async_press(self) -> None:
        data = await self._client.get_faults_state(site_id=self._site_id, equipment_id=self._equipment_id)
        self.hass.bus.async_fire(
            "openfdd_fault_history",
            {"equipment_id": self._equipment_id, "equipment_name": self._equipment_name, "state": data or []},
        )


class OpenFDDEquipmentRefreshButton(OpenFDDEquipmentButtonBase):
    """Refresh coordinator (per equipment)."""

    def __init__(self, coordinator, equipment_id: str, equipment_name: str) -> None:
        super().__init__(coordinator, equipment_id, equipment_name, "equipment_refresh", "Refresh")

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
