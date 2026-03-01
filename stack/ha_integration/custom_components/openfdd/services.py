"""Register Open-FDD services. Full API coverage: config, CRUD, data-model, BACnet, download."""

import logging
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _get_client(hass: HomeAssistant):
    """Return the Open-FDD client for the first config entry, or None."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None
    data = hass.data.get(DOMAIN, {}).get(entries[0].entry_id, {})
    return data.get("client")


# --- Config ---
SERVICE_GET_CONFIG = "get_config"
SERVICE_PUT_CONFIG = "put_config"

# --- Sites ---
SERVICE_LIST_SITES = "list_sites"
SERVICE_CREATE_SITE = "create_site"
SERVICE_GET_SITE = "get_site"
SERVICE_UPDATE_SITE = "update_site"
SERVICE_DELETE_SITE = "delete_site"

# --- Equipment ---
SERVICE_LIST_EQUIPMENT = "list_equipment"
SERVICE_CREATE_EQUIPMENT = "create_equipment"
SERVICE_GET_EQUIPMENT = "get_equipment"
SERVICE_UPDATE_EQUIPMENT = "update_equipment"
SERVICE_DELETE_EQUIPMENT = "delete_equipment"

# --- Points ---
SERVICE_LIST_POINTS = "list_points"
SERVICE_CREATE_POINT = "create_point"
SERVICE_GET_POINT = "get_point"
SERVICE_UPDATE_POINT = "update_point"
SERVICE_DELETE_POINT = "delete_point"

# --- Data model ---
SERVICE_DATA_MODEL_SERIALIZE = "data_model_serialize"
SERVICE_GET_DATA_MODEL_TTL = "get_data_model_ttl"
SERVICE_GET_DATA_MODEL_EXPORT = "get_data_model_export"
SERVICE_PUT_DATA_MODEL_IMPORT = "put_data_model_import"
SERVICE_RUN_SPARQL = "run_sparql"
SERVICE_GET_DATA_MODEL_CHECK = "get_data_model_check"

# --- BACnet ---
SERVICE_BACNET_SERVER_HELLO = "bacnet_server_hello"
SERVICE_BACNET_WHOIS_RANGE = "bacnet_whois_range"
SERVICE_BACNET_POINT_DISCOVERY_TO_GRAPH = "bacnet_point_discovery_to_graph"

# --- Download ---
SERVICE_GET_DOWNLOAD_CSV = "get_download_csv"
SERVICE_POST_DOWNLOAD_CSV = "post_download_csv"
SERVICE_GET_DOWNLOAD_FAULTS = "get_download_faults"

# --- Health ---
SERVICE_GET_HEALTH = "get_health"

# --- Job (existing) ---
SERVICE_RUN_FDD = "run_fdd"


def _schema_optional(**kwargs):
    return {k: vol.Optional(v) for k, v in kwargs.items()}


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register all Open-FDD services."""

    async def get_config(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            _LOGGER.warning("Open-FDD: no config entry")
            return
        try:
            result = await client.get_config()
            call.hass.bus.async_fire(f"{DOMAIN}.get_config_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("get_config failed: %s", e)

    async def put_config(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            await client.put_config(call.data)
        except Exception as e:
            _LOGGER.exception("put_config failed: %s", e)

    async def list_sites(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.list_sites()
            call.hass.bus.async_fire(f"{DOMAIN}.list_sites_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("list_sites failed: %s", e)

    async def create_site(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.create_site(
                name=call.data["name"],
                description=call.data.get("description"),
                metadata=call.data.get("metadata"),
            )
            call.hass.bus.async_fire(f"{DOMAIN}.create_site_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("create_site failed: %s", e)

    async def get_site(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.get_site(call.data["site_id"])
            call.hass.bus.async_fire(f"{DOMAIN}.get_site_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("get_site failed: %s", e)

    async def update_site(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            await client.update_site(
                call.data["site_id"],
                name=call.data.get("name"),
                description=call.data.get("description"),
                metadata=call.data.get("metadata"),
            )
        except Exception as e:
            _LOGGER.exception("update_site failed: %s", e)

    async def delete_site(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            await client.delete_site(call.data["site_id"])
        except Exception as e:
            _LOGGER.exception("delete_site failed: %s", e)

    async def list_equipment(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.list_equipment(site_id=call.data.get("site_id"))
            call.hass.bus.async_fire(f"{DOMAIN}.list_equipment_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("list_equipment failed: %s", e)

    async def create_equipment(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.create_equipment(
                site_id=call.data["site_id"],
                name=call.data["name"],
                description=call.data.get("description"),
                equipment_type=call.data.get("equipment_type"),
                feeds_equipment_id=call.data.get("feeds_equipment_id"),
                fed_by_equipment_id=call.data.get("fed_by_equipment_id"),
                metadata=call.data.get("metadata"),
            )
            call.hass.bus.async_fire(f"{DOMAIN}.create_equipment_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("create_equipment failed: %s", e)

    async def get_equipment(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.get_equipment(call.data["equipment_id"])
            call.hass.bus.async_fire(f"{DOMAIN}.get_equipment_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("get_equipment failed: %s", e)

    async def update_equipment(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            await client.update_equipment(
                call.data["equipment_id"],
                name=call.data.get("name"),
                description=call.data.get("description"),
                equipment_type=call.data.get("equipment_type"),
                feeds_equipment_id=call.data.get("feeds_equipment_id"),
                fed_by_equipment_id=call.data.get("fed_by_equipment_id"),
                metadata=call.data.get("metadata"),
            )
        except Exception as e:
            _LOGGER.exception("update_equipment failed: %s", e)

    async def delete_equipment(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            await client.delete_equipment(call.data["equipment_id"])
        except Exception as e:
            _LOGGER.exception("delete_equipment failed: %s", e)

    async def list_points(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.list_points(
                site_id=call.data.get("site_id"),
                equipment_id=call.data.get("equipment_id"),
            )
            call.hass.bus.async_fire(f"{DOMAIN}.list_points_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("list_points failed: %s", e)

    async def create_point(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.create_point(
                site_id=call.data["site_id"],
                external_id=call.data["external_id"],
                brick_type=call.data.get("brick_type"),
                fdd_input=call.data.get("fdd_input"),
                unit=call.data.get("unit"),
                description=call.data.get("description"),
                equipment_id=call.data.get("equipment_id"),
                bacnet_device_id=call.data.get("bacnet_device_id"),
                object_identifier=call.data.get("object_identifier"),
                object_name=call.data.get("object_name"),
                polling=call.data.get("polling"),
            )
            call.hass.bus.async_fire(f"{DOMAIN}.create_point_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("create_point failed: %s", e)

    async def get_point(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.get_point(call.data["point_id"])
            call.hass.bus.async_fire(f"{DOMAIN}.get_point_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("get_point failed: %s", e)

    async def update_point(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            await client.update_point(
                call.data["point_id"],
                brick_type=call.data.get("brick_type"),
                fdd_input=call.data.get("fdd_input"),
                unit=call.data.get("unit"),
                description=call.data.get("description"),
                equipment_id=call.data.get("equipment_id"),
                bacnet_device_id=call.data.get("bacnet_device_id"),
                object_identifier=call.data.get("object_identifier"),
                object_name=call.data.get("object_name"),
                polling=call.data.get("polling"),
            )
        except Exception as e:
            _LOGGER.exception("update_point failed: %s", e)

    async def delete_point(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            await client.delete_point(call.data["point_id"])
        except Exception as e:
            _LOGGER.exception("delete_point failed: %s", e)

    async def data_model_serialize(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            await client.data_model_serialize()
        except Exception as e:
            _LOGGER.exception("data_model_serialize failed: %s", e)

    async def get_data_model_ttl(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.get_data_model_ttl(
                site_id=call.data.get("site_id"),
                save=call.data.get("save", True),
            )
            call.hass.bus.async_fire(f"{DOMAIN}.get_data_model_ttl_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("get_data_model_ttl failed: %s", e)

    async def get_data_model_export(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.get_data_model_export(
                site_id=call.data.get("site_id"),
                bacnet_only=call.data.get("bacnet_only", False),
            )
            call.hass.bus.async_fire(f"{DOMAIN}.get_data_model_export_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("get_data_model_export failed: %s", e)

    async def put_data_model_import(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.put_data_model_import(
                points=call.data["points"],
                equipment=call.data.get("equipment"),
            )
            call.hass.bus.async_fire(f"{DOMAIN}.put_data_model_import_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("put_data_model_import failed: %s", e)

    async def run_sparql(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.post_data_model_sparql(call.data["query"])
            call.hass.bus.async_fire(f"{DOMAIN}.run_sparql_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("run_sparql failed: %s", e)

    async def get_data_model_check(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.get_data_model_check()
            call.hass.bus.async_fire(f"{DOMAIN}.get_data_model_check_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("get_data_model_check failed: %s", e)

    async def bacnet_server_hello(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.bacnet_server_hello(url=call.data.get("url"))
            call.hass.bus.async_fire(f"{DOMAIN}.bacnet_server_hello_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("bacnet_server_hello failed: %s", e)

    async def bacnet_whois_range(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.bacnet_whois_range(
                start_instance=call.data.get("start_instance", 1),
                end_instance=call.data.get("end_instance", 3456799),
                url=call.data.get("url"),
                gateway=call.data.get("gateway"),
            )
            call.hass.bus.async_fire(f"{DOMAIN}.bacnet_whois_range_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("bacnet_whois_range failed: %s", e)

    async def bacnet_point_discovery_to_graph(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.bacnet_point_discovery_to_graph(
                device_instance=call.data["device_instance"],
                update_graph=call.data.get("update_graph", True),
                write_file=call.data.get("write_file", True),
                url=call.data.get("url"),
                gateway=call.data.get("gateway"),
            )
            call.hass.bus.async_fire(f"{DOMAIN}.bacnet_point_discovery_to_graph_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("bacnet_point_discovery_to_graph failed: %s", e)

    async def get_download_csv(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.get_download_csv(
                site_id=call.data["site_id"],
                start_date=call.data["start_date"],
                end_date=call.data["end_date"],
                format=call.data.get("format", "wide"),
            )
            call.hass.bus.async_fire(f"{DOMAIN}.get_download_csv_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("get_download_csv failed: %s", e)

    async def post_download_csv(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.post_download_csv(
                site_id=call.data["site_id"],
                start_date=call.data["start_date"],
                end_date=call.data["end_date"],
                format=call.data.get("format", "wide"),
                point_ids=call.data.get("point_ids"),
            )
            call.hass.bus.async_fire(f"{DOMAIN}.post_download_csv_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("post_download_csv failed: %s", e)

    async def get_download_faults(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.get_download_faults(
                start_date=call.data["start_date"],
                end_date=call.data["end_date"],
                site_id=call.data.get("site_id"),
                format=call.data.get("format", "json"),
            )
            call.hass.bus.async_fire(f"{DOMAIN}.get_download_faults_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("get_download_faults failed: %s", e)

    async def get_health(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.get_health()
            call.hass.bus.async_fire(f"{DOMAIN}.get_health_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("get_health failed: %s", e)

    async def run_fdd(call: ServiceCall):
        client = _get_client(hass)
        if not client:
            return
        try:
            result = await client.post_job_fdd_run()
            call.hass.bus.async_fire(f"{DOMAIN}.run_fdd_result", {"data": result})
        except Exception as e:
            _LOGGER.exception("run_fdd failed: %s", e)

    # Schemas (minimal required fields; optional passed in call.data)
    hass.services.async_register(DOMAIN, SERVICE_GET_CONFIG, get_config)
    hass.services.async_register(
        DOMAIN, SERVICE_PUT_CONFIG, put_config, vol.Schema({}, extra=vol.ALLOW_EXTRA)
    )

    hass.services.async_register(DOMAIN, SERVICE_LIST_SITES, list_sites)
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_SITE,
        create_site,
        vol.Schema({vol.Required("name"): cv.string, "description": cv.string, "metadata": dict}),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GET_SITE, get_site, vol.Schema({vol.Required("site_id"): cv.string})
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_SITE,
        update_site,
        vol.Schema({
            vol.Required("site_id"): cv.string,
            "name": cv.string,
            "description": cv.string,
            "metadata": dict,
        }),
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_SITE, delete_site, vol.Schema({vol.Required("site_id"): cv.string})
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_EQUIPMENT,
        list_equipment,
        vol.Schema({"site_id": cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_EQUIPMENT,
        create_equipment,
        vol.Schema({
            vol.Required("site_id"): cv.string,
            vol.Required("name"): cv.string,
            "description": cv.string,
            "equipment_type": cv.string,
            "feeds_equipment_id": cv.string,
            "fed_by_equipment_id": cv.string,
            "metadata": dict,
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_EQUIPMENT,
        get_equipment,
        vol.Schema({vol.Required("equipment_id"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_EQUIPMENT,
        update_equipment,
        vol.Schema({
            vol.Required("equipment_id"): cv.string,
            "name": cv.string,
            "description": cv.string,
            "equipment_type": cv.string,
            "feeds_equipment_id": cv.string,
            "fed_by_equipment_id": cv.string,
            "metadata": dict,
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_EQUIPMENT,
        delete_equipment,
        vol.Schema({vol.Required("equipment_id"): cv.string}),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_POINTS,
        list_points,
        vol.Schema({"site_id": cv.string, "equipment_id": cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_POINT,
        create_point,
        vol.Schema({
            vol.Required("site_id"): cv.string,
            vol.Required("external_id"): cv.string,
            "brick_type": cv.string,
            "fdd_input": cv.string,
            "unit": cv.string,
            "description": cv.string,
            "equipment_id": cv.string,
            "bacnet_device_id": cv.string,
            "object_identifier": cv.string,
            "object_name": cv.string,
            "polling": cv.boolean,
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_POINT,
        get_point,
        vol.Schema({vol.Required("point_id"): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_POINT,
        update_point,
        vol.Schema({
            vol.Required("point_id"): cv.string,
            "brick_type": cv.string,
            "fdd_input": cv.string,
            "unit": cv.string,
            "description": cv.string,
            "equipment_id": cv.string,
            "bacnet_device_id": cv.string,
            "object_identifier": cv.string,
            "object_name": cv.string,
            "polling": cv.boolean,
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_POINT,
        delete_point,
        vol.Schema({vol.Required("point_id"): cv.string}),
    )

    hass.services.async_register(DOMAIN, SERVICE_DATA_MODEL_SERIALIZE, data_model_serialize)
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DATA_MODEL_TTL,
        get_data_model_ttl,
        vol.Schema({"site_id": cv.string, "save": cv.boolean}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DATA_MODEL_EXPORT,
        get_data_model_export,
        vol.Schema({"site_id": cv.string, "bacnet_only": cv.boolean}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PUT_DATA_MODEL_IMPORT,
        put_data_model_import,
        vol.Schema({
            vol.Required("points"): list,
            "equipment": list,
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN_SPARQL,
        run_sparql,
        vol.Schema({vol.Required("query"): cv.string}),
    )
    hass.services.async_register(DOMAIN, SERVICE_GET_DATA_MODEL_CHECK, get_data_model_check)

    hass.services.async_register(
        DOMAIN,
        SERVICE_BACNET_SERVER_HELLO,
        bacnet_server_hello,
        vol.Schema({"url": cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_BACNET_WHOIS_RANGE,
        bacnet_whois_range,
        vol.Schema({
            "start_instance": cv.positive_int,
            "end_instance": cv.positive_int,
            "url": cv.string,
            "gateway": cv.string,
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_BACNET_POINT_DISCOVERY_TO_GRAPH,
        bacnet_point_discovery_to_graph,
        vol.Schema({
            vol.Required("device_instance"): cv.positive_int,
            "update_graph": cv.boolean,
            "write_file": cv.boolean,
            "url": cv.string,
            "gateway": cv.string,
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DOWNLOAD_CSV,
        get_download_csv,
        vol.Schema({
            vol.Required("site_id"): cv.string,
            vol.Required("start_date"): cv.string,
            vol.Required("end_date"): cv.string,
            "format": cv.string,
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_POST_DOWNLOAD_CSV,
        post_download_csv,
        vol.Schema({
            vol.Required("site_id"): cv.string,
            vol.Required("start_date"): cv.string,
            vol.Required("end_date"): cv.string,
            "format": cv.string,
            "point_ids": list,
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DOWNLOAD_FAULTS,
        get_download_faults,
        vol.Schema({
            vol.Required("start_date"): cv.string,
            vol.Required("end_date"): cv.string,
            "site_id": cv.string,
            "format": cv.string,
        }),
    )

    hass.services.async_register(DOMAIN, SERVICE_GET_HEALTH, get_health)
    hass.services.async_register(DOMAIN, SERVICE_RUN_FDD, run_fdd)
    _LOGGER.debug("Open-FDD services registered")
