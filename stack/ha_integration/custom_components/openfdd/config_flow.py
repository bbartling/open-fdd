"""Config flow for Open-FDD integration."""

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import CONF_API_KEY, CONF_BASE_URL, DEFAULT_PORT, DOMAIN

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_BASE_URL, default="http://homeassistant.local:8000"): str,
    vol.Required(CONF_API_KEY): str,
})


class OpenFDDConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Open-FDD."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)
        # Validate by calling /capabilities with Bearer token
        base = user_input[CONF_BASE_URL].rstrip("/")
        api_key = user_input[CONF_API_KEY]
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{base}/capabilities",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return self.async_show_form(
                            step_id="user",
                            data_schema=DATA_SCHEMA,
                            errors={"base": "invalid_auth"},
                        )
        except Exception as e:
            return self.async_show_form(
                step_id="user",
                data_schema=DATA_SCHEMA,
                errors={"base": "cannot_connect"},
            )
        return self.async_create_entry(
            title=base,
            data={CONF_BASE_URL: base, CONF_API_KEY: api_key},
        )
