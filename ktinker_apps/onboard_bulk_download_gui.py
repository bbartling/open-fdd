#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import queue
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import BOTH, END, LEFT, TOP, W, X, filedialog, messagebox, scrolledtext, ttk
import urllib.error
import urllib.parse
import urllib.request


STATE_PATH = Path.home() / ".openfdd-onboard-bulk-gui.json"
DEFAULT_FONT_PT = 14


@dataclass
class BuildingRow:
    id: str
    name: str
    point_count: int | None = None


def _request_json(base_url: str, api_key: str, path: str, *, method: str = "GET", payload: dict | None = None) -> list[dict]:
    url = f"{base_url.rstrip('/')}{path}"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Invalid base URL scheme: {parsed.scheme!r}")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        method=method,
        headers={"X-OB-Api": api_key, "Content-Type": "application/json"},
        data=data,
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = (exc.read() or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail[:400]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed for {path}: {exc}") from exc
    if isinstance(body, list):
        return [row for row in body if isinstance(row, dict)]
    return []


def _safe_metric_name(row: dict) -> str:
    raw = str(row.get("topic") or row.get("name") or f"point_{row.get('id')}")
    return raw.strip().replace(" ", "_") or f"point_{row.get('id')}"


class OnboardBulkGui:
    def __init__(self) -> None:
        import tkinter as tk

        self.tk = tk
        self.root = tk.Tk()
        self.root.title("Open-FDD - Onboard Bulk Download (CSV)")
        self.root.geometry("1020x760")
        self.root.minsize(820, 580)
        self.log_q: queue.Queue[str | None] = queue.Queue()
        self._busy = False
        self._font_widgets: list = []
        self._buildings: list[BuildingRow] = []
        self._building_choices: dict[str, str] = {}
        self._last_detected_range: tuple[str, str] | None = None

        style = ttk.Style()
        style.configure("TLabel", font=("Segoe UI", 11))
        style.configure("TButton", font=("Segoe UI", 11))
        style.configure("TLabelframe.Label", font=("Segoe UI", 11))
        style.configure("TNotebook.Tab", font=("Segoe UI", 11), padding=(10, 4))

        self._build_top()
        self._build_tabs()
        self._apply_fonts()
        self._load_state()
        self.root.after(200, self._drain_log_queue)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _mono(self) -> str:
        return "Consolas"

    def _entry(self, parent, **kwargs):
        w = self.tk.Entry(parent, font=(self._mono(), DEFAULT_FONT_PT), relief=self.tk.SOLID, bd=1, **kwargs)
        self._font_widgets.append(w)
        return w

    def _build_top(self) -> None:
        tk = self.tk
        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill=X, side=TOP)
        row = ttk.Frame(top)
        row.pack(fill=X)
        ttk.Label(row, text="Text size").pack(side=LEFT, padx=(0, 6))
        self.var_font_pt = tk.IntVar(value=DEFAULT_FONT_PT)
        sp = tk.Spinbox(row, from_=10, to=24, width=5, textvariable=self.var_font_pt, command=self._apply_fonts)
        sp.pack(side=LEFT)
        self._font_widgets.append(sp)
        ttk.Label(row, text="pt").pack(side=LEFT, padx=(6, 12))
        self.var_font_pt.trace_add("write", lambda *_: self._apply_fonts())
        ttk.Label(
            top,
            text=(
                "Standalone Onboard bulk downloader for CSV workflow. "
                "Download time-series to CSV here, then import into Open-FDD via the CSV Import page."
            ),
        ).pack(anchor=W, pady=(6, 0))

    def _build_tabs(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        self.tab_download = ttk.Frame(nb, padding=8)
        self.tab_buildings = ttk.Frame(nb, padding=8)
        nb.add(self.tab_download, text="Bulk Download")
        nb.add(self.tab_buildings, text="Browse Buildings")
        self._build_download_tab()
        self._build_buildings_tab()

    def _build_download_tab(self) -> None:
        tk = self.tk
        f = self.tab_download
        ttk.Label(f, text="API base URL").grid(row=0, column=0, sticky=W, pady=4, padx=(0, 8))
        self.ent_base = self._entry(f, width=56)
        self.ent_base.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(f, text="API key").grid(row=1, column=0, sticky=W, pady=4, padx=(0, 8))
        self.ent_key = self._entry(f, width=56, show="*")
        self.ent_key.grid(row=1, column=1, sticky="ew", pady=4)
        self.var_show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            f,
            text="Show API key",
            variable=self.var_show_key,
            command=self._toggle_api_key_visibility,
        ).grid(row=1, column=2, sticky=W, padx=(8, 0))

        ttk.Label(f, text="Building ID").grid(row=2, column=0, sticky=W, pady=4, padx=(0, 8))
        self.var_building = tk.StringVar(value="")
        self.cmb_building = ttk.Combobox(f, textvariable=self.var_building, width=52, state="normal")
        self.cmb_building.grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(f, text="Start date (YYYY-MM-DD)").grid(row=3, column=0, sticky=W, pady=4, padx=(0, 8))
        self.ent_start = self._entry(f, width=20)
        self.ent_start.grid(row=3, column=1, sticky=W, pady=4)
        ttk.Label(f, text="End date (YYYY-MM-DD)").grid(row=4, column=0, sticky=W, pady=4, padx=(0, 8))
        self.ent_end = self._entry(f, width=20)
        self.ent_end.grid(row=4, column=1, sticky=W, pady=4)
        preset_row = ttk.Frame(f)
        preset_row.grid(row=4, column=2, sticky=W, padx=(8, 0))
        ttk.Label(preset_row, text="Quick range").pack(side=LEFT, padx=(0, 6))
        self.var_preset = tk.StringVar(value="Custom")
        self.cmb_preset = ttk.Combobox(
            preset_row,
            textvariable=self.var_preset,
            state="readonly",
            width=12,
            values=["Custom", "Last 7 days", "Last 30 days", "Last 90 days"],
        )
        self.cmb_preset.pack(side=LEFT)
        self.cmb_preset.bind("<<ComboboxSelected>>", self._on_preset_selected)

        folder_row = ttk.Frame(f)
        folder_row.grid(row=5, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(folder_row, text="Output folder").pack(side=LEFT, padx=(0, 8))
        self.ent_out_dir = self._entry(folder_row, width=62)
        self.ent_out_dir.pack(side=LEFT, fill=X, expand=True)
        ttk.Button(folder_row, text="Browse folder…", command=self._pick_output_dir).pack(side=LEFT, padx=(8, 0))

        file_row = ttk.Frame(f)
        file_row.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Label(file_row, text="CSV filename").pack(side=LEFT, padx=(0, 8))
        self.ent_out_name = self._entry(file_row, width=28)
        self.ent_out_name.pack(side=LEFT, padx=(0, 8))
        ttk.Label(file_row, text="(example: onboard_bulk_export.csv)").pack(side=LEFT)

        btn_row = ttk.Frame(f)
        btn_row.grid(row=7, column=0, columnspan=3, sticky=W, pady=8)
        self.btn_download = tk.Button(
            btn_row,
            text="  DOWNLOAD CSV  ",
            command=self._on_download_click,
            bg="#0b57d0",
            fg="white",
            activebackground="#0842a0",
            activeforeground="white",
            font=("Segoe UI", 13, "bold"),
            padx=18,
            pady=10,
            relief=tk.FLAT,
        )
        self.btn_download.pack(side=LEFT, padx=(0, 8))
        self.btn_fetch_buildings = ttk.Button(btn_row, text="Fetch buildings", command=self._on_fetch_buildings)
        self.btn_fetch_buildings.pack(side=LEFT, padx=(0, 8))
        self.btn_prefill_dates = ttk.Button(btn_row, text="Prefill dates from available data", command=self._on_prefill_dates)
        self.btn_prefill_dates.pack(side=LEFT, padx=(0, 8))
        self.btn_copy_detected = ttk.Button(btn_row, text="Copy detected date range", command=self._copy_detected_date_range)
        self.btn_copy_detected.pack(side=LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Copy log", command=self._copy_log).pack(side=LEFT)

        logf = ttk.LabelFrame(f, text="Console output", padding=6)
        logf.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=8)
        self.txt_log = scrolledtext.ScrolledText(logf, wrap="word", height=15, font=(self._mono(), DEFAULT_FONT_PT))
        self.txt_log.pack(fill=BOTH, expand=True)

        f.columnconfigure(1, weight=1)
        f.rowconfigure(8, weight=1)

    def _build_buildings_tab(self) -> None:
        f = self.tab_buildings
        ttk.Label(f, text="Use Fetch buildings to list available buildings from Onboard. Double-click a row to copy its ID.").pack(anchor=W)
        self.lst_buildings = scrolledtext.ScrolledText(f, wrap="none", height=24, font=(self._mono(), max(10, DEFAULT_FONT_PT - 1)))
        self.lst_buildings.pack(fill=BOTH, expand=True, pady=(8, 0))

    def _apply_fonts(self) -> None:
        try:
            pt = int(self.var_font_pt.get())
        except Exception:
            pt = DEFAULT_FONT_PT
        pt = max(10, min(24, pt))
        style = ttk.Style()
        style.configure("TLabel", font=("Segoe UI", max(9, pt - 2)))
        style.configure("TButton", font=("Segoe UI", max(9, pt - 2)))
        style.configure("TLabelframe.Label", font=("Segoe UI", max(9, pt - 2)))
        style.configure("TNotebook.Tab", font=("Segoe UI", max(9, pt - 2)))
        mono = (self._mono(), pt)
        for w in self._font_widgets:
            try:
                w.configure(font=mono)
            except Exception:
                pass
        self.txt_log.configure(font=mono)
        self.lst_buildings.configure(font=(self._mono(), max(10, pt - 1)))

    def _toggle_api_key_visibility(self) -> None:
        self.ent_key.configure(show="" if self.var_show_key.get() else "*")

    def _pick_output_dir(self) -> None:
        p = filedialog.askdirectory()
        if p:
            self.ent_out_dir.delete(0, END)
            self.ent_out_dir.insert(0, p)

    def _copy_log(self) -> None:
        body = self.txt_log.get("1.0", END)
        if not body.strip():
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(body)
        self.root.update_idletasks()

    def _log(self, msg: str) -> None:
        self.log_q.put(msg.rstrip("\n") + "\n")

    def _drain_log_queue(self) -> None:
        try:
            while True:
                item = self.log_q.get_nowait()
                if item is None:
                    self.txt_log.insert(END, "\n--- finished ---\n")
                    self.txt_log.see(END)
                    self._set_busy(False)
                    break
                self.txt_log.insert(END, item)
                self.txt_log.see(END)
        except queue.Empty:
            pass
        self.root.after(200, self._drain_log_queue)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.btn_download.configure(state=("disabled" if busy else "normal"))
        self.btn_fetch_buildings.configure(state=("disabled" if busy else "normal"))
        self.btn_prefill_dates.configure(state=("disabled" if busy else "normal"))
        self.btn_copy_detected.configure(state=("disabled" if busy else "normal"))

    def _set_date_fields(self, start_ymd: str, end_ymd: str) -> None:
        self.ent_start.delete(0, END)
        self.ent_start.insert(0, start_ymd)
        self.ent_end.delete(0, END)
        self.ent_end.insert(0, end_ymd)

    def _on_preset_selected(self, _event=None) -> None:
        val = self.var_preset.get().strip()
        now = datetime.now(timezone.utc).date()
        if val == "Last 7 days":
            start = now - timedelta(days=6)
            self._set_date_fields(start.isoformat(), now.isoformat())
        elif val == "Last 30 days":
            start = now - timedelta(days=29)
            self._set_date_fields(start.isoformat(), now.isoformat())
        elif val == "Last 90 days":
            start = now - timedelta(days=89)
            self._set_date_fields(start.isoformat(), now.isoformat())

    def _copy_detected_date_range(self) -> None:
        if not self._last_detected_range:
            messagebox.showinfo("No detected range", "Run 'Prefill dates from available data' first.")
            return
        start_ymd, end_ymd = self._last_detected_range
        payload = f"{start_ymd} to {end_ymd}"
        self.root.clipboard_clear()
        self.root.clipboard_append(payload)
        self.root.update_idletasks()
        self._log(f"Copied detected date range: {payload}")

    def _resolve_building_id(self) -> str:
        raw = self.var_building.get().strip()
        if not raw:
            return ""
        if raw in self._building_choices:
            return self._building_choices[raw]
        return raw.split("|", 1)[0].strip()

    def _output_csv_path(self) -> Path:
        out_dir = self.ent_out_dir.get().strip()
        out_name = self.ent_out_name.get().strip()
        if not out_name.lower().endswith(".csv"):
            out_name = f"{out_name}.csv"
        return Path(out_dir).expanduser() / out_name

    def _cfg(self) -> dict[str, str]:
        return {
            "base_url": self.ent_base.get().strip(),
            "api_key": self.ent_key.get().strip(),
            "building_id": self._resolve_building_id(),
            "start_date": self.ent_start.get().strip(),
            "end_date": self.ent_end.get().strip(),
            "output_dir": self.ent_out_dir.get().strip(),
            "output_name": self.ent_out_name.get().strip(),
        }

    def _validate_range(self, start_ymd: str, end_ymd: str) -> tuple[str, str]:
        a = datetime.fromisoformat(f"{start_ymd}T00:00:00").replace(tzinfo=timezone.utc)
        b = datetime.fromisoformat(f"{end_ymd}T23:59:59").replace(tzinfo=timezone.utc)
        if b < a:
            raise ValueError("End date must be on or after start date.")
        return a.isoformat(), b.isoformat()

    def _fetch_buildings_worker(self) -> None:
        cfg = self._cfg()
        rows = _request_json(cfg["base_url"], cfg["api_key"], "/buildings")
        parsed: list[BuildingRow] = []
        for row in rows:
            parsed.append(
                BuildingRow(
                    id=str(row.get("id", "")),
                    name=str(row.get("name", "")).strip() or f"building-{row.get('id', '')}",
                    point_count=(int(row["point_count"]) if str(row.get("point_count", "")).isdigit() else None),
                )
            )
        parsed.sort(key=lambda b: (b.name.lower(), b.id))
        self._log(f"Fetched buildings: {len(parsed)}")
        self.root.after(0, lambda: self._set_buildings(parsed))
        lines = []
        for b in parsed:
            lines.append(f"id={b.id:>6}  points={str(b.point_count) if b.point_count is not None else '?':>4}  name={b.name}")
        self.root.after(0, lambda: self._set_buildings_text("\n".join(lines) if lines else "No buildings returned."))

    def _set_buildings(self, buildings: list[BuildingRow]) -> None:
        self._buildings = buildings
        self._building_choices = {f"{b.id} | {b.name}": b.id for b in buildings}
        choices = list(self._building_choices.keys())
        self.cmb_building.configure(values=choices)
        if not self.var_building.get().strip() and choices:
            self.var_building.set(choices[0])

    def _set_buildings_text(self, text: str) -> None:
        self.lst_buildings.delete("1.0", END)
        self.lst_buildings.insert("1.0", text)

    def _on_fetch_buildings(self) -> None:
        if self._busy:
            return
        cfg = self._cfg()
        if not cfg["base_url"] or not cfg["api_key"]:
            messagebox.showerror("Missing config", "Base URL and API key are required.")
            return
        self._set_busy(True)
        self.txt_log.delete("1.0", END)

        def worker() -> None:
            try:
                self._fetch_buildings_worker()
            except Exception as exc:  # noqa: BLE001
                self._log(f"ERROR: {exc}")
            finally:
                self.log_q.put(None)

        threading.Thread(target=worker, daemon=True).start()

    def _extract_bounds(self, rows: list[dict]) -> tuple[datetime | None, datetime | None]:
        earliest: datetime | None = None
        latest: datetime | None = None
        for row in rows:
            vals = row.get("values") if isinstance(row, dict) else None
            if not isinstance(vals, list):
                continue
            for sample in vals:
                if not isinstance(sample, list) or not sample:
                    continue
                raw_ts = str(sample[0] or "").strip()
                if not raw_ts:
                    continue
                if raw_ts.endswith("Z"):
                    raw_ts = raw_ts[:-1] + "+00:00"
                try:
                    ts = datetime.fromisoformat(raw_ts).astimezone(timezone.utc)
                except ValueError:
                    continue
                if earliest is None or ts < earliest:
                    earliest = ts
                if latest is None or ts > latest:
                    latest = ts
        return earliest, latest

    def _set_dates_from_probe(self, earliest: datetime, latest: datetime) -> None:
        start_ymd = earliest.date().isoformat()
        end_ymd = latest.date().isoformat()
        self._set_date_fields(start_ymd, end_ymd)
        self._last_detected_range = (start_ymd, end_ymd)
        self.var_preset.set("Custom")

    def _prefill_dates_worker(self) -> None:
        cfg = self._cfg()
        building_id = int(cfg["building_id"])
        now = datetime.now(timezone.utc)
        search_back_days = 365
        window_days = 7
        sample_points = 12

        self._log(f"Probing date availability for building_id={building_id} ...")
        points = _request_json(cfg["base_url"], cfg["api_key"], f"/buildings/{building_id}/points")
        sampled_ids: list[int] = []
        for row in points:
            pid = row.get("id")
            if pid is None:
                continue
            try:
                pid_i = int(pid)
            except (TypeError, ValueError):
                continue
            if pid_i not in sampled_ids:
                sampled_ids.append(pid_i)
            if len(sampled_ids) >= sample_points:
                break
        if not sampled_ids:
            raise RuntimeError("No points found for this building.")

        earliest: datetime | None = None
        cursor = now - timedelta(days=search_back_days)
        while cursor < now:
            window_end = min(cursor + timedelta(days=window_days), now)
            rows = _request_json(
                cfg["base_url"],
                cfg["api_key"],
                "/query-v2",
                method="POST",
                payload={"start": cursor.isoformat(), "end": window_end.isoformat(), "point_ids": sampled_ids},
            )
            win_earliest, _ = self._extract_bounds(rows)
            if win_earliest is not None:
                earliest = win_earliest
                break
            cursor = window_end

        latest: datetime | None = None
        cursor_end = now
        floor = now - timedelta(days=search_back_days)
        while cursor_end > floor:
            window_start = max(cursor_end - timedelta(days=window_days), floor)
            rows = _request_json(
                cfg["base_url"],
                cfg["api_key"],
                "/query-v2",
                method="POST",
                payload={"start": window_start.isoformat(), "end": cursor_end.isoformat(), "point_ids": sampled_ids},
            )
            _, win_latest = self._extract_bounds(rows)
            if win_latest is not None:
                latest = win_latest
                break
            cursor_end = window_start

        if earliest is None or latest is None:
            raise RuntimeError("Could not detect available date range from sampled points.")
        self._log(f"Detected availability: {earliest.date().isoformat()} to {latest.date().isoformat()}")
        self.root.after(0, lambda: self._set_dates_from_probe(earliest, latest))

    def _on_prefill_dates(self) -> None:
        if self._busy:
            return
        cfg = self._cfg()
        for key in ("base_url", "api_key", "building_id"):
            if not cfg[key]:
                messagebox.showerror("Missing input", f"Field '{key}' is required.")
                return
        self._set_busy(True)
        self.txt_log.delete("1.0", END)

        def worker() -> None:
            try:
                self._prefill_dates_worker()
            except Exception as exc:  # noqa: BLE001
                self._log(f"ERROR: {exc}")
            finally:
                self.log_q.put(None)

        threading.Thread(target=worker, daemon=True).start()

    def _download_worker(self) -> None:
        cfg = self._cfg()
        start_iso, end_iso = self._validate_range(cfg["start_date"], cfg["end_date"])
        out_path = self._output_csv_path()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        building_id = int(cfg["building_id"])

        self._log(f"Loading points for building_id={building_id} ...")
        points = _request_json(cfg["base_url"], cfg["api_key"], f"/buildings/{building_id}/points")
        points_by_id: dict[int, dict] = {}
        point_ids: list[int] = []
        for row in points:
            pid = row.get("id")
            if pid is None:
                continue
            try:
                pid_i = int(pid)
            except (TypeError, ValueError):
                continue
            points_by_id[pid_i] = row
            point_ids.append(pid_i)
        if not point_ids:
            raise RuntimeError("No points found for this building.")
        self._log(f"Point count: {len(point_ids)}")

        self._log(f"Running query-v2 from {start_iso} to {end_iso} ...")
        rows = _request_json(
            cfg["base_url"],
            cfg["api_key"],
            "/query-v2",
            method="POST",
            payload={"start": start_iso, "end": end_iso, "point_ids": point_ids},
        )
        by_ts: dict[str, dict[str, object]] = {}
        for row in rows:
            point_id = row.get("point_id")
            if point_id is None:
                continue
            try:
                pid_i = int(point_id)
            except (TypeError, ValueError):
                continue
            point_meta = points_by_id.get(pid_i, {})
            metric = _safe_metric_name(point_meta)
            vals = row.get("values")
            if not isinstance(vals, list):
                continue
            for sample in vals:
                if not isinstance(sample, list) or len(sample) < 2:
                    continue
                ts_raw = str(sample[0] or "").strip()
                if not ts_raw:
                    continue
                value_raw = sample[-1] if len(sample) >= 3 else sample[1]
                try:
                    val = float(value_raw)
                except (TypeError, ValueError):
                    continue
                rec = by_ts.setdefault(ts_raw, {"timestamp": ts_raw})
                rec[metric] = val
        if not by_ts:
            raise RuntimeError("No time-series rows returned for this range.")

        fields = ["timestamp"]
        metric_names = sorted({k for row in by_ts.values() for k in row.keys() if k != "timestamp"})
        fields.extend(metric_names)
        ordered_rows = [by_ts[k] for k in sorted(by_ts.keys())]
        with out_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in ordered_rows:
                writer.writerow(row)
        self._log(f"Wrote CSV: {out_path}")
        self._log(f"Rows={len(ordered_rows)}  metrics={len(metric_names)}")

    def _on_download_click(self) -> None:
        if self._busy:
            return
        cfg = self._cfg()
        for key in ("base_url", "api_key", "building_id", "start_date", "end_date", "output_dir", "output_name"):
            if not cfg[key]:
                messagebox.showerror("Missing input", f"Field '{key}' is required.")
                return
        self._set_busy(True)
        self.txt_log.delete("1.0", END)

        def worker() -> None:
            try:
                self._download_worker()
            except Exception as exc:  # noqa: BLE001
                self._log(f"ERROR: {exc}")
            finally:
                self.log_q.put(None)

        threading.Thread(target=worker, daemon=True).start()

    def _load_state(self) -> None:
        defaults = {
            "base_url": "https://api.onboarddata.io",
            "api_key": "",
            "building_id": "",
            "start_date": datetime.now().strftime("%Y-%m-01"),
            "end_date": datetime.now().strftime("%Y-%m-%d"),
            "output_dir": str(Path.home() / "Downloads"),
            "output_name": "onboard_bulk_export.csv",
            "ui_font_size": DEFAULT_FONT_PT,
        }
        if STATE_PATH.exists():
            try:
                saved = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    defaults.update({k: v for k, v in saved.items() if k in defaults})
            except Exception:
                pass
        legacy_out = defaults.get("output_csv")
        if legacy_out and isinstance(legacy_out, str):
            try:
                legacy_path = Path(legacy_out).expanduser()
                defaults["output_dir"] = str(legacy_path.parent)
                defaults["output_name"] = legacy_path.name or "onboard_bulk_export.csv"
            except Exception:
                pass
        self.ent_base.insert(0, str(defaults["base_url"]))
        self.ent_key.insert(0, str(defaults["api_key"]))
        self.var_building.set(str(defaults["building_id"]))
        self.ent_start.insert(0, str(defaults["start_date"]))
        self.ent_end.insert(0, str(defaults["end_date"]))
        self.ent_out_dir.insert(0, str(defaults["output_dir"]))
        self.ent_out_name.insert(0, str(defaults["output_name"]))
        self.var_font_pt.set(int(defaults["ui_font_size"]))
        self._apply_fonts()

    def _save_state(self) -> None:
        out = self._cfg()
        out["ui_font_size"] = int(self.var_font_pt.get())
        STATE_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")

    def _on_close(self) -> None:
        try:
            self._save_state()
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    app = OnboardBulkGui()
    app.root.mainloop()


if __name__ == "__main__":
    main()
