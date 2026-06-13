"""Callbacks for Edge Connections (site registry drives Dashboard dropdown)."""

from __future__ import annotations

import json
import os
from urllib import error, request

from dash import ALL, Input, Output, State, ctx, html, no_update

CENTRAL_API = os.environ.get("OPENFDD_CENTRAL_API_URL", "http://127.0.0.1:8060").rstrip("/")


def _api(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{CENTRAL_API}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _edges_local() -> list[dict]:
    try:
        from portfolio.central.edge_registry import list_edges_public

        return list_edges_public()
    except Exception:
        return []


def _dash_options(edges: list[dict]) -> tuple[list[dict], str | None]:
    opts = [
        {"label": str(e.get("name") or e.get("site_id")), "value": e.get("site_id")}
        for e in edges
        if e.get("site_id")
    ]
    default = opts[0]["value"] if opts else None
    return opts, default


def _api_or_local_edges() -> tuple[list[dict], str | None]:
    try:
        data = _api("GET", "/api/central/edges")
        return data.get("edges") or [], None
    except Exception as exc:
        return _edges_local(), str(exc)


def _save_edge_local(site_id: str, name: str, url: str, user: str, password: str) -> str:
    from portfolio.central.edge_registry import add_or_update_edge

    add_or_update_edge(
        site_id=site_id.strip(),
        name=(name or site_id).strip(),
        base_url=url.strip(),
        auth_type="password",
        username=(user or "integrator").strip(),
        password=password or "",
    )
    return f"Saved {name or site_id} — open Dashboard to view data."


def _remove_edge_local(site_id: str) -> str:
    from portfolio.central.edge_registry import delete_edge

    delete_edge(site_id.strip())
    return f"Removed connection."


def _test_edge_local(url: str, user: str, password: str, site_id: str | None = None) -> dict:
    from portfolio.central.edge_registry import test_edge_connection

    if site_id:
        return test_edge_connection(site_id=site_id.strip())
    return test_edge_connection(
        base_url=url.strip(),
        auth_type="password",
        username=(user or "integrator").strip(),
        password=password or "",
    )


def _resolve_site_id(url: str, name: str) -> str:
    from portfolio.central.site_resolve import resolve_site_id

    return resolve_site_id(base_url=url, name=name)


def register_edge_callbacks(app) -> None:
    @app.callback(
        Output("edge-list", "children"),
        Output("overview-site", "options"),
        Output("overview-site", "value"),
        Output("edge-registry-revision", "data"),
        Input("main-tabs", "value"),
        Input("edge-save-btn", "n_clicks"),
        Input({"type": "edge-remove-btn", "site_id": ALL}, "n_clicks"),
        Input("refresh-interval", "n_intervals"),
        State("overview-site", "value"),
        State("edge-name", "value"),
        State("edge-url", "value"),
        State("edge-registry-revision", "data"),
        prevent_initial_call=False,
    )
    def refresh_edges(_tab, save_n, _remove_clicks, _interval_n, current_site, form_name, form_url, revision):
        edges, api_err = _api_or_local_edges()
        opts, default = _dash_options(edges)
        valid = {o["value"] for o in opts}
        dash_value = current_site if current_site in valid else default

        rev = int(revision or 0)
        if ctx.triggered_id == "edge-save-btn" and save_n and form_url:
            try:
                dash_value = _resolve_site_id(form_url, form_name or "")
            except ValueError:
                pass
            rev += 1

        if isinstance(ctx.triggered_id, dict) and ctx.triggered_id.get("type") == "edge-remove-btn":
            rev += 1
            if dash_value not in valid:
                dash_value = default

        if not edges:
            hint = html.P("No Edge connections yet — add your URL below.", style={"color": "#b45309"})
            return hint, opts, dash_value, rev

        rows = []
        for e in edges:
            cred = "ready" if e.get("has_password") or e.get("has_token") else "needs password"
            rows.append(
                html.Div(
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "gap": "10px",
                        "padding": "10px 12px",
                        "marginBottom": "8px",
                        "border": "1px solid #e2e8f0",
                        "borderRadius": "8px",
                        "background": "#fff",
                        "flexWrap": "wrap",
                    },
                    children=[
                        html.Div(
                            style={"flex": "1", "minWidth": "200px"},
                            children=[
                                html.Strong(str(e.get("name") or e.get("site_id"))),
                                html.Div(
                                    f"{e.get('base_url')} · {cred}",
                                    style={"fontSize": "12px", "color": "#475569", "marginTop": "2px"},
                                ),
                            ],
                        ),
                        html.Button(
                            "Edit",
                            id={"type": "edge-edit-btn", "site_id": e.get("site_id")},
                            n_clicks=0,
                            style={
                                "background": "#1d4ed8",
                                "color": "#fff",
                                "border": "none",
                                "padding": "6px 14px",
                                "borderRadius": "6px",
                                "cursor": "pointer",
                                "fontSize": "13px",
                            },
                        ),
                        html.Button(
                            "Remove",
                            id={"type": "edge-remove-btn", "site_id": e.get("site_id")},
                            n_clicks=0,
                            style={
                                "background": "#b91c1c",
                                "color": "#fff",
                                "border": "none",
                                "padding": "6px 14px",
                                "borderRadius": "6px",
                                "cursor": "pointer",
                                "fontSize": "13px",
                            },
                        ),
                    ],
                )
            )
        return html.Div(rows), opts, dash_value, rev

    @app.callback(
        Output("edge-name", "value"),
        Output("edge-url", "value"),
        Output("edge-user", "value"),
        Input({"type": "edge-edit-btn", "site_id": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def prefill_edge_form(_clicks):
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict) or triggered.get("type") != "edge-edit-btn":
            return no_update, no_update, no_update
        site_id = str(triggered.get("site_id") or "")
        for e in _edges_local():
            if e.get("site_id") == site_id:
                return e.get("name") or site_id, e.get("base_url") or "", e.get("username") or ""
        return no_update, no_update, no_update

    @app.callback(
        Output("edge-test-result", "children"),
        Input("edge-test-btn", "n_clicks"),
        Input("edge-save-btn", "n_clicks"),
        Input({"type": "edge-remove-btn", "site_id": ALL}, "n_clicks"),
        State("edge-name", "value"),
        State("edge-url", "value"),
        State("edge-user", "value"),
        State("edge-password", "value"),
        prevent_initial_call=True,
    )
    def edge_actions(test_n, save_n, _remove_clicks, name, url, user, password):
        triggered = ctx.triggered_id
        if not triggered:
            return no_update

        if isinstance(triggered, dict) and triggered.get("type") == "edge-remove-btn":
            rid = str(triggered.get("site_id") or "")
            if not rid:
                return "Could not remove — unknown site."
            try:
                _api("DELETE", f"/api/central/edges/{rid}")
                return "Connection removed."
            except Exception:
                try:
                    return _remove_edge_local(rid)
                except Exception as exc:
                    return str(exc)

        if triggered == "edge-save-btn":
            if not url:
                return "Edge URL required."
            try:
                site_id = _resolve_site_id(url, name or "")
            except ValueError as exc:
                return str(exc)
            body = {
                "site_id": site_id,
                "name": (name or site_id).strip(),
                "base_url": url.strip(),
                "username": (user or "integrator").strip(),
                "password": password or "",
                "auth_type": "password",
            }
            try:
                _api("POST", "/api/central/edges", body)
                return f"Saved {body['name']} — switch to Dashboard (data refreshes automatically)."
            except Exception:
                try:
                    return _save_edge_local(site_id, name or site_id, url, user or "integrator", password or "")
                except Exception as exc:
                    return str(exc)

        if triggered == "edge-test-btn":
            if not url:
                return "Enter Edge URL first."
            try:
                site_id = _resolve_site_id(url, name or "")
            except ValueError:
                site_id = None
            try:
                out = _api(
                    "POST",
                    "/api/central/edges/test",
                    {
                        "site_id": site_id or "",
                        "base_url": url.strip(),
                        "username": user or "integrator",
                        "password": password or "",
                        "auth_type": "password",
                    },
                )
                return json.dumps(out, indent=2)
            except Exception:
                try:
                    out = _test_edge_local(url, user or "integrator", password or "", site_id=site_id)
                    return json.dumps(out, indent=2)
                except Exception as exc:
                    return str(exc)

        return no_update
