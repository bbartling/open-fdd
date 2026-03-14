"""LLM tagging service: build canonical prompt, call OpenAI, parse and validate response.

Workflow: export rows (list[dict]) → OpenAI → parse JSON → validate DataModelImportBody.
The caller (POST /data-model/tag-with-openai) passes the user-supplied API key per request.
Keys are NEVER stored or logged here.
"""

from __future__ import annotations

import json
import logging
from importlib import import_module
from typing import Any

from pydantic import ValidationError

logger = logging.getLogger(__name__)


class LlmTaggerError(Exception):
    """Service-layer error with HTTP-like status/details, translated by API layer."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail

# ---------------------------------------------------------------------------
# Canonical system prompt — matches README.md § "Canonical prompt"
# Keep in sync with docs/modeling/ai_assisted_tagging.md
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """\
I use Open-FDD. I will paste JSON from GET /data-model/export (optionally filtered with ?site_id=YourSiteName).

Your job is to convert that export into CLEAN Open-FDD import JSON.

Return ONLY valid JSON with exactly two top-level keys:

{
  "points": [...],
  "equipment": [...]
}

Do not return markdown or explanations.

---------------------------------------------------------------------

POINT RULES

For each point:

Preserve all existing fields from the export including:

- point_id
- bacnet_device_id
- object_identifier
- object_name
- external_id
- site_id
- site_name
- equipment_id (preserve but DO NOT use for relationships)

Then add or fill these fields:

- brick_type
- rule_input
- polling
- unit
- equipment_name

Equipment must be referenced by NAME only.

Example:

"equipment_name": "AHU-1"

Never use equipment UUIDs for relationships.

---------------------------------------------------------------------

SITE ID

Use the exact site_id from the export rows.

Do not invent or modify site_id values.

If site_id is null in the export, leave it null.

---------------------------------------------------------------------

EQUIPMENT ARRAY

Return an "equipment" array describing system relationships.

Each item must include:

- equipment_name
- site_id

Example:

{
  "equipment_name": "AHU-1",
  "site_id": "<site_id>",
  "feeds": ["VAV-1"]
}

If a VAV is served by an AHU:

AHU:

"feeds": ["VAV-1"]

VAV:

"fed_by": ["AHU-1"]

Prefer:

"feeds"
"fed_by"

Only use:

"feeds_equipment_id"
"fed_by_equipment_id"

if required by the source export.

---------------------------------------------------------------------

BRICK TYPES

Use appropriate Brick classes when possible.

Examples:

brick:Supply_Air_Temperature_Sensor
brick:Return_Air_Temperature_Sensor
brick:Mixed_Air_Temperature_Sensor
brick:Outside_Air_Temperature_Sensor
brick:Zone_Air_Temperature_Sensor
brick:Supply_Fan_Status
brick:Supply_Fan_Command
brick:Cooling_Valve_Command
brick:Heating_Valve_Command
brick:Damper_Position_Command
brick:Discharge_Air_Flow_Sensor
brick:Discharge_Air_Flow_Setpoint
brick:Supply_Air_Temperature_Setpoint

If a point cannot be confidently mapped:

"brick_type": null

---------------------------------------------------------------------

RULE INPUTS

Set rule_input to short reusable slugs.

Examples:

ahu_sat
ahu_sat_sp
rat
mat
oat
zone_temp
sf_status
sf_cmd
clg_cmd
htg_cmd
damper_cmd
airflow
airflow_sp

If unknown:

rule_input = null

---------------------------------------------------------------------

POLLING

Set polling=true for points useful for FDD or trending:

temperatures
humidity
flow
pressures
fan status
commands
setpoints
valves
dampers
power

Set polling=false for:

network ports
metadata objects
housekeeping points

---------------------------------------------------------------------

UNITS

Use consistent engineering units.

Examples:

degF or degC
%
cfm
mph
W/m2
0/1 (binary)

If unknown:

unit = null

---------------------------------------------------------------------

DUPLICATES

Do not rename external_id values.

If duplicates exist, keep them unchanged.

Open-FDD import logic uses:

(site_id + external_id)

with last row winning.

---------------------------------------------------------------------

OUTPUT

Return full JSON only.

No markdown
No explanation
"""


def tag_with_openai(
    export_rows: list[dict[str, Any]],
    api_key: str,
    model: str = "gpt-4o",
    timeout: float = 120.0,
) -> tuple[Any, dict[str, Any] | None]:
    """Call OpenAI to tag *export_rows* with Brick types and return (DataModelImportBody, usage_dict).

    Raises LlmTaggerError on all error conditions so the API endpoint can propagate
    a clean status code without leaking internal details or the API key.
    """
    # Late import: openai is optional; surfaces a clear 500 when not installed.
    try:
        openai_mod = import_module("openai")
    except ImportError:
        raise LlmTaggerError(
            500,
            "openai package is not installed. Add it with: pip install 'openai>=1.0'",
        )

    OpenAI = getattr(openai_mod, "OpenAI", None)
    AuthenticationError = getattr(openai_mod, "AuthenticationError", Exception)
    RateLimitError = getattr(openai_mod, "RateLimitError", Exception)
    APITimeoutError = getattr(openai_mod, "APITimeoutError", Exception)
    BadRequestError = getattr(openai_mod, "BadRequestError", Exception)
    if OpenAI is None:
        raise LlmTaggerError(500, "openai package is present but OpenAI client is unavailable.")

    # Inline import avoids circular dependency at module load time.
    from open_fdd.platform.api.data_model import DataModelImportBody

    if not api_key or not api_key.strip():
        raise LlmTaggerError(400, "openai_api_key is required.")

    export_json = json.dumps(export_rows, indent=2)
    user_message = f"Here is the export JSON:\n\n{export_json}"

    try:
        client = OpenAI(api_key=api_key.strip(), timeout=timeout)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
    except AuthenticationError:
        raise LlmTaggerError(401, "Invalid OpenAI API key. Check your key and try again.")
    except RateLimitError:
        raise LlmTaggerError(429, "OpenAI rate limit exceeded. Wait a moment and try again.")
    except APITimeoutError:
        raise LlmTaggerError(504, f"OpenAI API timed out after {int(timeout)}s.")
    except BadRequestError as exc:
        raise LlmTaggerError(400, f"OpenAI rejected the request: {exc}")
    except Exception as exc:
        # Log the exception type only — never log the key or payload.
        logger.error("OpenAI call failed: %s", type(exc).__name__, exc_info=False)
        raise LlmTaggerError(502, f"OpenAI API error: {type(exc).__name__}")

    content = (response.choices[0].message.content or "").strip()
    usage: dict[str, Any] | None = None
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LlmTaggerError(
            422,
            f"OpenAI returned non-JSON content ({exc}). "
            f"Raw response (first 500 chars): {content[:500]}",
        )

    # Ensure the two required top-level keys are present before validation.
    if "points" not in raw:
        raw["points"] = []
    if "equipment" not in raw:
        raw["equipment"] = []

    try:
        body = DataModelImportBody.model_validate(raw)
    except ValidationError as exc:
        raise LlmTaggerError(
            422,
            f"OpenAI response failed schema validation: {exc.error_count()} error(s). "
            f"First: {exc.errors()[0]}",
        )

    return body, usage
