from __future__ import annotations

from bacnet_toolshed.stack_args import bacnet_argv_from_cfg, route_discovery_kwargs


def test_bacnet_argv_from_cfg(monkeypatch):
    monkeypatch.setenv("OFDD_BACNET_BIND_STRICT", "1")
    argv = bacnet_argv_from_cfg(
        {
            "BACNET_NAME": "OpenFddEdge",
            "BACNET_INSTANCE": "599999",
            "BACNET_BIND": "192.168.204.12/24",
            "BACNET_VENDOR_ID": "1234",
        }
    )
    assert argv == [
        "--name",
        "OpenFddEdge",
        "--instance",
        "599999",
        "--address",
        "192.168.204.12/24:47808",
        "--vendoridentifier",
        "1234",
    ]


def test_bacnet_argv_route_aware(monkeypatch):
    monkeypatch.setenv("OFDD_BACNET_BIND_STRICT", "1")
    argv = bacnet_argv_from_cfg(
        {
            "BACNET_NAME": "OpenFddEdge",
            "BACNET_INSTANCE": "599999",
            "BACNET_BIND": "192.168.1.50/24:47808",
            "ROUTER_IP": "192.168.1.1",
            "MSTP_NET": "2000",
            "BACNET_NETWORK": "1",
        }
    )
    assert "--route-aware" in argv
    assert "--network" in argv
    assert "1" in argv
    kwargs = route_discovery_kwargs(
        {
            "ROUTER_IP": "192.168.1.1",
            "MSTP_NET": "2000",
        }
    )
    assert kwargs == {"router_ip": "192.168.1.1", "mstp_net": 2000, "local_too": False}
