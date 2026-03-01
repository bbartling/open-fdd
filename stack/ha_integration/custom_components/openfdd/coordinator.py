"""DataUpdateCoordinator for Open-FDD: sites, equipment, fault state, definitions, capabilities."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api_client import OpenFDDClient
from .const import DOMAIN


def _group_equipment_by_site(equipment_list: list) -> dict:
    """Group equipment list by site_id."""
    by_site: dict[str, list] = {}
    for eq in equipment_list or []:
        sid = eq.get("site_id")
        if not sid:
            continue
        by_site.setdefault(sid, []).append(eq)
    return by_site


class OpenFDDCoordinator(DataUpdateCoordinator):
    """
    Single coordinator: sites, equipment (grouped by site), faults_active,
    fault_definitions, run_fdd_status, capabilities.
    Refresh every 30s; sites/equipment/definitions are stable, faults_active changes often.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: OpenFDDClient,
        update_interval_seconds: int = 30,
    ):
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval_seconds),
        )
        self.client = client

    async def _async_update_data(self):
        try:
            sites = await self.client.list_sites()
            equipment_list = await self.client.list_equipment()
            equipment_by_site = _group_equipment_by_site(equipment_list or [])
            points_list = await self.client.list_points()
            points_by_equipment: dict[str, list] = {}
            for p in points_list or []:
                eid = p.get("equipment_id")
                if eid:
                    eid = str(eid)
                    points_by_equipment.setdefault(eid, []).append(p)
            faults_active = await self.client.get_faults_active()
            fault_definitions = await self.client.get_faults_definitions()
            run_status = await self.client.get_run_fdd_status()
            capabilities = await self.client.get_capabilities()
            try:
                suggested = await self.client.get_entities_suggested()
            except Exception:
                suggested = []
            return {
                "sites": sites or [],
                "equipment": equipment_list or [],
                "equipment_by_site": equipment_by_site,
                "points_by_equipment": points_by_equipment,
                "faults_active": faults_active or [],
                "fault_definitions": fault_definitions or [],
                "run_fdd_status": run_status or {},
                "capabilities": capabilities or {},
                "entities_suggested": suggested or [],
            }
        except Exception as e:
            self.logger.exception("Open-FDD update failed: %s", e)
            raise
