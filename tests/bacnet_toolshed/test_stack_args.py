from __future__ import annotations

from bacnet_toolshed.stack_args import bacnet_argv_from_cfg


def test_bacnet_argv_from_cfg(monkeypatch):
    monkeypatch.setenv("OFDD_BACNET_BIND_STRICT", "1")
    argv = bacnet_argv_from_cfg(
        {
            "BACNET_NAME": "OpenFddEdge",
            "BACNET_INSTANCE": "599999",
            "BACNET_BIND": "192.168.204.12/24",
        }
    )
    assert argv == [
        "--name",
        "OpenFddEdge",
        "--instance",
        "599999",
        "--address",
        "192.168.204.12/24:47808",
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
    assert "--router-ip" in argv
    assert "192.168.1.1" in argv
