"""DataUpdateCoordinator for Open-FDD fault state and entities."""

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
            update_interval=update_interval_seconds,
        )
        self.client = client
        self._data = {"faults_active": [], "capabilities": {}}

    @property
    def data(self):
        return self._data

    async def _async_update_data(self):
        try:
            caps = await self.client.get_capabilities()
            self._data["capabilities"] = caps
            faults = await self.client.get_faults_active()
            self._data["faults_active"] = faults
            return self._data
        except Exception as e:
            self.logger.exception("Open-FDD update failed: %s", e)
            raise
