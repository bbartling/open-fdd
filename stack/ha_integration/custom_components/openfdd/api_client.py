"""Open-FDD REST API client. Full coverage: health, config, CRUD, data-model, BACnet, download."""

import aiohttp

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
LONG_TIMEOUT = aiohttp.ClientTimeout(total=60)


class OpenFDDClient:
    """Client for Open-FDD API. All endpoints used by graph_and_crud_test.py."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = (api_key or "").strip()

    def _request_headers(self):
        """Headers for every request: Accept, and Authorization when api_key is set."""
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
        return_text: bool = False,
        timeout: aiohttp.ClientTimeout = DEFAULT_TIMEOUT,
    ):
        url = f"{self.base_url}{path}"
        headers = self._request_headers()
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method, url, headers=headers, json=json_body, params=params
            ) as resp:
                resp.raise_for_status()
                if return_text:
                    return await resp.text()
                if resp.content_length == 0:
                    return None
                return await resp.json()

    # --- Health & capabilities (existing) ---
    async def get_health(self):
        return await self._request("GET", "/health")

    async def get_capabilities(self):
        return await self._request("GET", "/capabilities")

    async def get_faults_active(self, site_id=None, equipment_id=None):
        params = {}
        if site_id is not None:
            params["site_id"] = site_id
        if equipment_id is not None:
            params["equipment_id"] = equipment_id
        return await self._request("GET", "/faults/active", params=params or None)

    async def get_faults_state(self, site_id=None, equipment_id=None):
        """GET /faults/state — all fault state rows (active and cleared) for history/log."""
        params = {}
        if site_id is not None:
            params["site_id"] = site_id
        if equipment_id is not None:
            params["equipment_id"] = equipment_id
        return await self._request("GET", "/faults/state", params=params or None)

    async def get_faults_definitions(self):
        """GET /faults/definitions — fault_id, name, severity, category for labels."""
        return await self._request("GET", "/faults/definitions")

    async def get_entities_suggested(self):
        """GET /entities/suggested — Brick-tagged points -> suggested HA entity mappings."""
        return await self._request("GET", "/entities/suggested")

    async def post_job_fdd_run(self):
        return await self._request("POST", "/jobs/fdd/run", json_body={})

    async def post_job_bacnet_discovery(self, device_instance: int = 3456789, gateway_id: str | None = None):
        """POST /jobs/bacnet/discovery — async BACnet point discovery; returns job_id."""
        body = {"device_instance": device_instance}
        if gateway_id is not None:
            body["gateway_id"] = gateway_id
        return await self._request("POST", "/jobs/bacnet/discovery", json_body=body)

    async def get_run_fdd_status(self):
        """GET /run-fdd/status — last FDD run for summary sensor."""
        return await self._request("GET", "/run-fdd/status")

    def ws_url(self):
        """WebSocket URL; when api_key is set, token is in query param (server accepts this or Authorization)."""
        url = f"{self.base_url.replace('http', 'ws')}/ws/events"
        if self.api_key:
            url += f"?token={self.api_key}"
        return url

    def ws_headers(self):
        """Headers for WebSocket handshake (use with aiohttp session.ws_connect(url, headers=client.ws_headers()))."""
        return self._request_headers()

    # --- Config ---
    async def get_config(self):
        return await self._request("GET", "/config")

    async def put_config(self, body: dict):
        return await self._request("PUT", "/config", json_body=body)

    # --- Sites ---
    async def list_sites(self):
        return await self._request("GET", "/sites")

    async def create_site(self, name: str, description: str | None = None, metadata: dict | None = None):
        body = {"name": name}
        if description is not None:
            body["description"] = description
        if metadata is not None:
            body["metadata"] = metadata
        return await self._request("POST", "/sites", json_body=body)

    async def get_site(self, site_id: str):
        return await self._request("GET", f"/sites/{site_id}")

    async def update_site(self, site_id: str, name: str | None = None, description: str | None = None, metadata: dict | None = None):
        body = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if metadata is not None:
            body["metadata"] = metadata
        return await self._request("PATCH", f"/sites/{site_id}", json_body=body)

    async def delete_site(self, site_id: str):
        return await self._request("DELETE", f"/sites/{site_id}")

    # --- Equipment ---
    async def list_equipment(self, site_id: str | None = None):
        params = {"site_id": site_id} if site_id else None
        return await self._request("GET", "/equipment", params=params)

    async def create_equipment(
        self,
        site_id: str,
        name: str,
        description: str | None = None,
        equipment_type: str | None = None,
        feeds_equipment_id: str | None = None,
        fed_by_equipment_id: str | None = None,
        metadata: dict | None = None,
    ):
        body = {"site_id": site_id, "name": name}
        if description is not None:
            body["description"] = description
        if equipment_type is not None:
            body["equipment_type"] = equipment_type
        if feeds_equipment_id is not None:
            body["feeds_equipment_id"] = feeds_equipment_id
        if fed_by_equipment_id is not None:
            body["fed_by_equipment_id"] = fed_by_equipment_id
        if metadata is not None:
            body["metadata"] = metadata
        return await self._request("POST", "/equipment", json_body=body)

    async def get_equipment(self, equipment_id: str):
        return await self._request("GET", f"/equipment/{equipment_id}")

    async def update_equipment(
        self,
        equipment_id: str,
        name: str | None = None,
        description: str | None = None,
        equipment_type: str | None = None,
        feeds_equipment_id: str | None = None,
        fed_by_equipment_id: str | None = None,
        metadata: dict | None = None,
    ):
        body = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if equipment_type is not None:
            body["equipment_type"] = equipment_type
        if feeds_equipment_id is not None:
            body["feeds_equipment_id"] = feeds_equipment_id
        if fed_by_equipment_id is not None:
            body["fed_by_equipment_id"] = fed_by_equipment_id
        if metadata is not None:
            body["metadata"] = metadata
        return await self._request("PATCH", f"/equipment/{equipment_id}", json_body=body)

    async def delete_equipment(self, equipment_id: str):
        return await self._request("DELETE", f"/equipment/{equipment_id}")

    # --- Points ---
    async def list_points(self, site_id: str | None = None, equipment_id: str | None = None):
        params = {}
        if site_id is not None:
            params["site_id"] = site_id
        if equipment_id is not None:
            params["equipment_id"] = equipment_id
        return await self._request("GET", "/points", params=params or None)

    async def create_point(
        self,
        site_id: str,
        external_id: str,
        brick_type: str | None = None,
        fdd_input: str | None = None,
        unit: str | None = None,
        description: str | None = None,
        equipment_id: str | None = None,
        bacnet_device_id: str | None = None,
        object_identifier: str | None = None,
        object_name: str | None = None,
        polling: bool | None = None,
    ):
        body = {"site_id": site_id, "external_id": external_id}
        if brick_type is not None:
            body["brick_type"] = brick_type
        if fdd_input is not None:
            body["fdd_input"] = fdd_input
        if unit is not None:
            body["unit"] = unit
        if description is not None:
            body["description"] = description
        if equipment_id is not None:
            body["equipment_id"] = equipment_id
        if bacnet_device_id is not None:
            body["bacnet_device_id"] = bacnet_device_id
        if object_identifier is not None:
            body["object_identifier"] = object_identifier
        if object_name is not None:
            body["object_name"] = object_name
        if polling is not None:
            body["polling"] = polling
        return await self._request("POST", "/points", json_body=body)

    async def get_point(self, point_id: str):
        return await self._request("GET", f"/points/{point_id}")

    async def update_point(
        self,
        point_id: str,
        brick_type: str | None = None,
        fdd_input: str | None = None,
        unit: str | None = None,
        description: str | None = None,
        equipment_id: str | None = None,
        bacnet_device_id: str | None = None,
        object_identifier: str | None = None,
        object_name: str | None = None,
        polling: bool | None = None,
    ):
        body = {}
        if brick_type is not None:
            body["brick_type"] = brick_type
        if fdd_input is not None:
            body["fdd_input"] = fdd_input
        if unit is not None:
            body["unit"] = unit
        if description is not None:
            body["description"] = description
        if equipment_id is not None:
            body["equipment_id"] = equipment_id
        if bacnet_device_id is not None:
            body["bacnet_device_id"] = bacnet_device_id
        if object_identifier is not None:
            body["object_identifier"] = object_identifier
        if object_name is not None:
            body["object_name"] = object_name
        if polling is not None:
            body["polling"] = polling
        return await self._request("PATCH", f"/points/{point_id}", json_body=body)

    async def delete_point(self, point_id: str):
        return await self._request("DELETE", f"/points/{point_id}")

    # --- Data model ---
    async def data_model_serialize(self):
        return await self._request("POST", "/data-model/serialize")

    async def get_data_model_ttl(self, site_id: str | None = None, save: bool = True):
        params = {"save": save}
        if site_id is not None:
            params["site_id"] = site_id
        return await self._request(
            "GET", "/data-model/ttl", params=params, return_text=True
        )

    async def get_data_model_export(self, site_id: str | None = None, bacnet_only: bool = False):
        params = {}
        if site_id is not None:
            params["site_id"] = site_id
        if bacnet_only:
            params["bacnet_only"] = True
        return await self._request("GET", "/data-model/export", params=params or None)

    async def put_data_model_import(self, points: list, equipment: list | None = None):
        body = {"points": points}
        if equipment is not None:
            body["equipment"] = equipment
        return await self._request(
            "PUT", "/data-model/import", json_body=body, timeout=LONG_TIMEOUT
        )

    async def post_data_model_sparql(self, query: str):
        return await self._request("POST", "/data-model/sparql", json_body={"query": query})

    async def get_data_model_check(self):
        return await self._request("GET", "/data-model/check")

    # --- BACnet ---
    async def bacnet_server_hello(self, url: str | None = None):
        body = {} if url is None else {"url": url}
        return await self._request("POST", "/bacnet/server_hello", json_body=body)

    async def bacnet_whois_range(
        self,
        start_instance: int = 1,
        end_instance: int = 3456799,
        url: str | None = None,
        gateway: str | None = None,
    ):
        params = {}
        if gateway is not None:
            params["gateway"] = gateway
        body = {"request": {"start_instance": start_instance, "end_instance": end_instance}}
        if url is not None:
            body["url"] = url
        return await self._request(
            "POST",
            "/bacnet/whois_range",
            json_body=body,
            params=params or None,
            timeout=LONG_TIMEOUT,
        )

    async def bacnet_point_discovery_to_graph(
        self,
        device_instance: int,
        update_graph: bool = True,
        write_file: bool = True,
        url: str | None = None,
        gateway: str | None = None,
    ):
        params = {}
        if gateway is not None:
            params["gateway"] = gateway
        body = {
            "instance": {"device_instance": device_instance},
            "update_graph": update_graph,
            "write_file": write_file,
        }
        if url is not None:
            body["url"] = url
        return await self._request(
            "POST",
            "/bacnet/point_discovery_to_graph",
            json_body=body,
            params=params or None,
            timeout=LONG_TIMEOUT,
        )

    # --- Download ---
    async def get_download_csv(
        self,
        site_id: str,
        start_date: str,
        end_date: str,
        format: str = "wide",
    ):
        params = {
            "site_id": site_id,
            "start_date": start_date,
            "end_date": end_date,
            "format": format,
        }
        return await self._request(
            "GET", "/download/csv", params=params, return_text=True
        )

    async def post_download_csv(
        self,
        site_id: str,
        start_date: str,
        end_date: str,
        format: str = "wide",
        point_ids: list | None = None,
    ):
        body = {
            "site_id": site_id,
            "start_date": start_date,
            "end_date": end_date,
            "format": format,
        }
        if point_ids is not None:
            body["point_ids"] = point_ids
        return await self._request(
            "POST", "/download/csv", json_body=body, return_text=True
        )

    async def get_download_faults(
        self,
        start_date: str,
        end_date: str,
        site_id: str | None = None,
        format: str = "json",
    ):
        params = {"start_date": start_date, "end_date": end_date, "format": format}
        if site_id is not None:
            params["site_id"] = site_id
        if format == "csv":
            return await self._request(
                "GET", "/download/faults", params=params, return_text=True
            )
        return await self._request("GET", "/download/faults", params=params)

    # --- Timeseries (latest value per point for HA / dashboards) ---
    async def get_timeseries_latest(
        self,
        site_id: str | None = None,
        equipment_id: str | None = None,
    ):
        """GET /timeseries/latest — latest reading per point from DB (BACnet scraper data)."""
        params = {}
        if site_id is not None:
            params["site_id"] = site_id
        if equipment_id is not None:
            params["equipment_id"] = equipment_id
        return await self._request(
            "GET", "/timeseries/latest", params=params or None
        )
