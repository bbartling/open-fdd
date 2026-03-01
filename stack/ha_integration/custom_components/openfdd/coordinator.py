"""DataUpdateCoordinator for Open-FDD fault state and entities."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api_client import OpenFDDClient
from .const import DOMAIN


class OpenFDDCoordinator(DataUpdateCoordinator):
    """Fetch fault state and optionally occupancy from Open-FDD."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: OpenFDDClient,
        update_interval_seconds: int = 60,
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
            caps = await self.client.get_capabilities()
            faults = await self.client.get_faults_active()
            return {"faults_active": faults, "capabilities": caps}
        except Exception as e:
            self.logger.exception("Open-FDD update failed: %s", e)
            raise
