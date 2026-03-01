"""
Helper/utils tests mirroring node-red-contrib-home-assistant-websocket helpers/utils.test.ts.
Topic filtering, parse_value_to_boolean, entity id validation for robust integration.
"""

import pytest

from open_fdd.platform.integration_helpers import (
    topic_matches,
    should_include,
    parse_value_to_boolean,
    valid_entity_id,
    valid_suggested_ha_id,
)


class TestTopicMatches:
    """Wildcard topic matching (like shouldInclude with single pattern)."""

    def test_matches_exact(self):
        assert topic_matches("fault.raised", "fault.raised") is True
        assert topic_matches("crud.point.created", "crud.point.created") is True

    def test_matches_wildcard_one_segment(self):
        assert topic_matches("fault.*", "fault.raised") is True
        assert topic_matches("fault.*", "fault.cleared") is True
        assert topic_matches("fault.*", "fault.other") is True
        assert topic_matches("fault.*", "crud.point.created") is False

    def test_matches_wildcard_multiple_segments(self):
        assert topic_matches("crud.point.*", "crud.point.created") is True
        assert topic_matches("crud.point.*", "crud.point.updated") is True
        assert topic_matches("crud.point.*", "crud.equipment.created") is False

    def test_empty_returns_false(self):
        assert topic_matches("", "fault.raised") is False
        assert topic_matches("fault.*", "") is False


class TestShouldInclude:
    """Include/exclude pattern filtering (like NR HA shouldInclude)."""

    def test_include_everything_if_no_include_pattern(self):
        assert should_include("test", None, None) is True
        assert should_include("anything", None, "exclude.*") is True

    def test_exclude_if_matches_exclude(self):
        assert should_include("fault.raised", "fault.*", "fault.raised") is False
        assert should_include("test", "t.*", "test") is False

    def test_include_if_matches_include_and_not_exclude(self):
        assert should_include("fault.raised", "fault.*", "other.*") is True
        assert should_include("crud.point.created", "crud.*", "fault.*") is True


class TestParseValueToBoolean:
    """Parse common values to bool (HA/Node-RED style)."""

    def test_boolean(self):
        assert parse_value_to_boolean(True) is True
        assert parse_value_to_boolean(False) is False

    def test_number(self):
        assert parse_value_to_boolean(1) is True
        assert parse_value_to_boolean(0) is False
        assert parse_value_to_boolean(42) is True

    def test_string_true_case_insensitive(self):
        assert parse_value_to_boolean("true") is True
        assert parse_value_to_boolean("TRUE") is True
        assert parse_value_to_boolean(" True ") is True
        assert parse_value_to_boolean("yes") is True
        assert parse_value_to_boolean("on") is True

    def test_string_false_case_insensitive(self):
        assert parse_value_to_boolean("false") is False
        assert parse_value_to_boolean("FALSE") is False
        assert parse_value_to_boolean(" False ") is False
        assert parse_value_to_boolean("no") is False

    def test_numeric_strings(self):
        assert parse_value_to_boolean("1") is True
        assert parse_value_to_boolean("42") is True
        assert parse_value_to_boolean("0") is False
        assert parse_value_to_boolean(" 0 ") is False

    def test_unrecognized_strings_false(self):
        assert parse_value_to_boolean("foo") is False
        assert parse_value_to_boolean("") is False
        assert parse_value_to_boolean("yes") is True  # we support yes
        assert parse_value_to_boolean("random") is False

    def test_none_and_undefined(self):
        assert parse_value_to_boolean(None) is False


class TestValidEntityId:
    """HA entity_id format: domain.entity_name (like NR HA validEntityId)."""

    def test_valid_entity_ids(self):
        assert valid_entity_id("binary_sensor.openfdd_ahu1_occupied") is True
        assert valid_entity_id("sensor.temp_1") is True
        assert valid_entity_id("domain_1.entity_1") is True

    def test_invalid_entity_ids(self):
        assert valid_entity_id("domain..entity") is False
        assert valid_entity_id("domain.entity.") is False
        assert valid_entity_id(".domain.entity") is False
        assert valid_entity_id("Domain.entity") is False  # domain must be lowercase
        assert valid_entity_id("") is False
        assert valid_entity_id("domain._entity") is False


class TestValidSuggestedHaId:
    """Open-FDD suggested_ha_id format (e.g. openfdd_ahu1_occupied)."""

    def test_valid_suggested_ids(self):
        assert valid_suggested_ha_id("openfdd_ahu1_occupied") is True
        assert valid_suggested_ha_id("openfdd_equipment_1") is True
        assert valid_suggested_ha_id("a") is True

    def test_invalid_suggested_ids(self):
        assert valid_suggested_ha_id("") is False
        assert valid_suggested_ha_id("OpenFDD_ahu") is False  # no uppercase
        assert valid_suggested_ha_id("a" * 65) is False  # max 64 chars
