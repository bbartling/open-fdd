"""Rule binding merge/unbind helpers."""

from openfdd_bridge.rule_bindings import apply_bind_op, build_assignments_view, merge_bind, unbind_target


def test_merge_bind_point():
    b = merge_bind({}, "point", "5007-analog-input-1168")
    assert "5007-analog-input-1168" in b["point_ids"]
    assert "5007-analog-input-1168" in b["direct_point_ids"]


def test_apply_bind_op_remove():
    rule = {
        "id": "r1",
        "bindings": merge_bind({}, "point", "p1"),
    }
    b = apply_bind_op(rule, op="remove", kind="point", target_id="p1")
    assert b["point_ids"] == []


def test_build_assignments_view_devices():
    model = {
        "sites": [{"id": "demo", "name": "Demo"}],
        "equipment": [{"id": "bench-1", "site_id": "demo", "name": "Bench"}],
        "points": [
            {
                "id": "5007-analog-input-1168",
                "site_id": "demo",
                "equipment_id": "bench-1",
                "name": "OA-H",
                "bacnet_device_id": 5007,
                "bacnet_device_address": "2000:7",
            }
        ],
    }
    rules = [
        {
            "id": "r1",
            "name": "humidity flatline",
            "enabled": True,
            "bindings": {"point_ids": ["5007-analog-input-1168"]},
        }
    ]
    view = build_assignments_view(model, rules, site_id="demo")
    assert len(view["devices"]) == 1
    assert view["devices"][0]["bacnet_device_id"] == 5007
    assert view["points"][0]["bound_rules"][0]["rule_name"] == "humidity flatline"
