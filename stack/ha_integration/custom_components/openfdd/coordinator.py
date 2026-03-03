"""DataUpdateCoordinator for Open-FDD: sites, equipment, points, and latest telemetry."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api_client import OpenFDDClient
from .const import DOMAIN


class OpenFDDCoordinator(DataUpdateCoordinator):
    """
    Fetches GET /sites, GET /equipment, GET /capabilities, GET /points, GET /timeseries/latest.
    Sites → HA areas; equipment → HA devices; points + latest → HA sensors (value + stale).
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
            capabilities = await self.client.get_capabilities()
            points_list = await self.client.list_points()
            latest_list = await self.client.get_timeseries_latest()
            # Index latest by point_id for sensor platform
            latest_by_point = {}
            if isinstance(latest_list, list):
                for row in latest_list:
                    pid = row.get("point_id")
                    if pid:
                        latest_by_point[pid] = row
            return {
                "sites": sites or [],
                "equipment": equipment_list or [],
                "capabilities": capabilities or {},
                "points": points_list or [],
                "timeseries_latest": latest_by_point,
            }
        except Exception as e:
            self.logger.exception("Open-FDD update failed: %s", e)
            raise
