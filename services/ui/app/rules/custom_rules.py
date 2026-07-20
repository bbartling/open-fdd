"""Agent-authored custom rules live here.

Copy a worked example from ``app/rules/custom_boilerplate.py``, adapt it, and
append the ``CookbookRule`` to ``CUSTOM_RULES`` below. Ids must start with
``CUSTOM-``.

Leave this list empty to run only the 50 canonical cookbook rules.
Set env ``VIBE19_INCLUDE_EXAMPLE_CUSTOM_RULES=1`` to also load the boilerplate
examples without editing this file.
"""

from __future__ import annotations

from app.rules.cookbook_catalog import CookbookRule

# Agents append CookbookRule instances here, e.g.:
# from app.rules.custom_boilerplate import EXAMPLE_SAT_HIGH
# CUSTOM_RULES = [EXAMPLE_SAT_HIGH]
CUSTOM_RULES: list[CookbookRule] = []
