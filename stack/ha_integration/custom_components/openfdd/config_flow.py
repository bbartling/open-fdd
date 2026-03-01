"""Config flow for Open-FDD integration."""

import aiohttp

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .api_client import OpenFDDClient
from .const import CONF_API_KEY, CONF_BASE_URL, DEFAULT_PORT, DOMAIN

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_BASE_URL, default="http://homeassistant.local:8000"): str,
    vol.Optional(CONF_API_KEY, default=""): str,
})


class OpenFDDConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Open-FDD."""

    VERSION = 1

    def _schema_with_defaults(self, base_url="", api_key=""):
        return vol.Schema({
            vol.Required(CONF_BASE_URL, default=base_url): str,
            vol.Optional(CONF_API_KEY, default=api_key): str,
        })

    async def async_step_user(self, user_input=None):
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)
        base = (user_input.get(CONF_BASE_URL) or "").strip().rstrip("/")
        api_key = (user_input.get(CONF_API_KEY) or "").strip()
        schema_with = self._schema_with_defaults(base, api_key)
        if not base:
            return self.async_show_form(
                step_id="user",
                data_schema=schema_with,
                errors={"base": "cannot_connect"},
            )
        try:
            # Try without auth first (server may not require it)
            client_no_auth = OpenFDDClient(base_url=base, api_key="")
            await client_no_auth.get_capabilities()
            return self.async_create_entry(
                title=base,
                data={CONF_BASE_URL: base, CONF_API_KEY: api_key},
            )
        except aiohttp.ClientResponseError as e:
            if e.status in (401, 403):
                if not api_key:
                    return self.async_show_form(
                        step_id="user",
                        data_schema=schema_with,
                        errors={"base": "auth_required"},
                    )
                try:
                    client_with_auth = OpenFDDClient(base_url=base, api_key=api_key)
                    await client_with_auth.get_capabilities()
                    return self.async_create_entry(
                        title=base,
                        data={CONF_BASE_URL: base, CONF_API_KEY: api_key},
                    )
                except aiohttp.ClientResponseError as e2:
                    if e2.status in (401, 403):
                        return self.async_show_form(
                            step_id="user",
                            data_schema=schema_with,
                            errors={"base": "invalid_auth"},
                        )
                    return self.async_show_form(
                        step_id="user",
                        data_schema=schema_with,
                        errors={"base": "cannot_connect"},
                    )
                except Exception:
                    return self.async_show_form(
                        step_id="user",
                        data_schema=schema_with,
                        errors={"base": "cannot_connect"},
                    )
            return self.async_show_form(
                step_id="user",
                data_schema=schema_with,
                errors={"base": "cannot_connect"},
            )
        except Exception:
            return self.async_show_form(
                step_id="user",
                data_schema=schema_with,
                errors={"base": "cannot_connect"},
            )
