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

Return a MINIMAL payload required for import.

For existing rows (point_id present), include:

- point_id
- brick_type
- rule_input
- polling
- unit
- equipment_name

For new rows (point_id is null), include:

- site_id
- external_id
- bacnet_device_id
- object_identifier
- object_name
- brick_type
- rule_input
- polling
- unit
- equipment_name

Do not include extra keys unless they are required for correct import behavior.

Then add or fill these fields when known:

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

_CHUNK_SIZE = 120


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
        raise LlmTaggerError(
            500, "openai package is present but OpenAI client is unavailable."
        )

    # Inline import avoids circular dependency at module load time.
    from open_fdd.platform.api.data_model import DataModelImportBody

    if not api_key or not api_key.strip():
        raise LlmTaggerError(400, "openai_api_key is required.")

    def _compact_export_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keep = {
            "point_id",
            "bacnet_device_id",
            "object_identifier",
            "object_name",
            "external_id",
            "site_id",
            "site_name",
            "equipment_id",
            "equipment_name",
            "brick_type",
            "rule_input",
            "unit",
            "polling",
        }
        compact: list[dict[str, Any]] = []
        for row in rows:
            compact.append({k: row.get(k) for k in keep if k in row})
        return compact

    def _call_openai_once(
        rows: list[dict[str, Any]],
    ) -> tuple[Any, dict[str, Any] | None]:
        export_json = json.dumps(_compact_export_rows(rows), indent=2)
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
            raise LlmTaggerError(
                401, "Invalid OpenAI API key. Check your key and try again."
            )
        except RateLimitError:
            raise LlmTaggerError(
                429, "OpenAI rate limit exceeded. Wait a moment and try again."
            )
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

    def _is_non_json_error(exc: LlmTaggerError) -> bool:
        return exc.status_code == 422 and "non-JSON" in exc.detail

    def _merge_usage(
        base: dict[str, int],
        extra: dict[str, Any] | None,
    ) -> None:
        if not extra:
            return
        base["prompt_tokens"] += int(extra.get("prompt_tokens") or 0)
        base["completion_tokens"] += int(extra.get("completion_tokens") or 0)
        base["total_tokens"] += int(extra.get("total_tokens") or 0)

    def _tag_rows_resilient(
        rows: list[dict[str, Any]],
    ) -> tuple[list[Any], list[Any], dict[str, int]]:
        try:
            body, usage = _call_openai_once(rows)
            usage_totals = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
            _merge_usage(usage_totals, usage)
            return body.points, body.equipment, usage_totals
        except LlmTaggerError as exc:
            if _is_non_json_error(exc) and len(rows) > 1:
                mid = len(rows) // 2
                left = rows[:mid]
                right = rows[mid:]
                logger.warning(
                    "LLM tagging non-JSON for chunk size %d; splitting into %d and %d",
                    len(rows),
                    len(left),
                    len(right),
                )
                left_points, left_equipment, left_usage = _tag_rows_resilient(left)
                right_points, right_equipment, right_usage = _tag_rows_resilient(right)
                merged_usage = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                }
                _merge_usage(merged_usage, left_usage)
                _merge_usage(merged_usage, right_usage)
                return (
                    left_points + right_points,
                    left_equipment + right_equipment,
                    merged_usage,
                )
            if _is_non_json_error(exc) and len(rows) == 1:
                raise LlmTaggerError(
                    422,
                    f"OpenAI returned non-JSON even for a single-row chunk. {exc.detail}",
                )
            raise

    # Fast path: single request.
    try:
        return _call_openai_once(export_rows)
    except LlmTaggerError as exc:
        # If the model output is truncated/non-JSON for large payloads, retry in chunks.
        if not (_is_non_json_error(exc) and len(export_rows) > 1):
            raise
        logger.warning(
            "LLM tagging returned non-JSON for %d rows; retrying in chunks of %d",
            len(export_rows),
            _CHUNK_SIZE,
        )

    all_points: list[Any] = []
    all_equipment: list[Any] = []
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for i in range(0, len(export_rows), _CHUNK_SIZE):
        chunk = export_rows[i : i + _CHUNK_SIZE]
        points_chunk, equipment_chunk, usage_chunk = _tag_rows_resilient(chunk)
        all_points.extend(points_chunk)
        all_equipment.extend(equipment_chunk)
        _merge_usage(usage_totals, usage_chunk)

    # De-duplicate equipment rows from chunked responses.
    seen_equipment: set[tuple[str, str, str]] = set()
    deduped_equipment: list[Any] = []
    for eq in all_equipment:
        eq_id = str(getattr(eq, "equipment_id", "") or "")
        site_id = str(getattr(eq, "site_id", "") or "")
        eq_name = str(getattr(eq, "equipment_name", "") or "")
        key = (eq_id, site_id, eq_name)
        if key in seen_equipment:
            continue
        seen_equipment.add(key)
        deduped_equipment.append(eq)

    merged_raw = {
        "points": [p.model_dump() for p in all_points],
        "equipment": [e.model_dump() for e in deduped_equipment],
    }
    merged_body = DataModelImportBody.model_validate(merged_raw)
    return merged_body, usage_totals
