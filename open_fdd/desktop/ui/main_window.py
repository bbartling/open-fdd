from __future__ import annotations

from pathlib import Path
import traceback

from open_fdd.desktop.rules.rule_loop import RuleLoopConfig, run_rule_loop_batched
from open_fdd.desktop.services.brick_service import BrickService
from open_fdd.desktop.services.ingest_service import IngestService
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.services.ttl_service import TtlService
from open_fdd.desktop.storage.paths import model_ttl_path
from open_fdd.engine.column_map_from_model import build_column_map_from_model_points


class DesktopMainWindow:
    """
    Wrapper to keep import-time dependency on PySide6 optional.
    """

    def __init__(self) -> None:
        from PySide6.QtWidgets import (
            QCheckBox,
            QDateTimeEdit,
            QFileDialog,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QPushButton,
            QComboBox,
            QSplitter,
            QTabWidget,
            QTableWidget,
            QTableWidgetItem,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
        from PySide6.QtCore import Qt, QDateTime, QEvent, QObject, QRunnable, QThreadPool, Signal
        from PySide6.QtGui import QFont

        self._qt = {
            "QMainWindow": QMainWindow,
            "QWidget": QWidget,
            "QVBoxLayout": QVBoxLayout,
            "QHBoxLayout": QHBoxLayout,
            "QTabWidget": QTabWidget,
            "QTextEdit": QTextEdit,
            "QPushButton": QPushButton,
            "QLabel": QLabel,
            "QLineEdit": QLineEdit,
            "QComboBox": QComboBox,
            "QSplitter": QSplitter,
            "QTableWidget": QTableWidget,
            "QTableWidgetItem": QTableWidgetItem,
            "QFileDialog": QFileDialog,
            "QCheckBox": QCheckBox,
            "QDateTimeEdit": QDateTimeEdit,
            "Qt": Qt,
            "QDateTime": QDateTime,
            "QEvent": QEvent,
            "QObject": QObject,
            "QRunnable": QRunnable,
            "QThreadPool": QThreadPool,
            "Signal": Signal,
            "QFont": QFont,
        }
        self._thread_pool = QThreadPool.globalInstance()
        self._active_jobs = 0
        self._run_weather_button = None
        self._run_onboard_button = None
        self._run_ml_button = None
        self._run_rules_button = None
        self.window = QMainWindow()
        self.window.setWindowTitle("Open-FDD Desktop")
        self.window.resize(1400, 860)
        self._apply_theme()
        self.model_service = ModelService()
        self.ttl_service = TtlService()
        self.ingest_service = IngestService(model_service=self.model_service)
        self._last_selected_site_id: str | None = None
        self._build()

    class _DropEventFilterProxy:
        def __init__(self, owner, qobject_cls):
            class _Proxy(qobject_cls):
                def __init__(self, parent_owner):
                    super().__init__()
                    self._owner = parent_owner

                def eventFilter(self, watched, event):
                    return self._owner.eventFilter(watched, event)

            self.instance = _Proxy(owner)

    def _apply_theme(self) -> None:
        self.window.setStyleSheet(
            """
            QMainWindow { background: #111319; color: #e8edf6; }
            QWidget { font-family: "Inter","Segoe UI",Arial,sans-serif; font-size: 14px; color: #e8edf6; }
            QTabWidget::pane { border: 1px solid #2f3746; border-radius: 12px; top: -1px; background: #1a1e27; }
            QTabBar::tab { background: #202632; color: #aeb8c7; min-height: 52px; padding: 14px 24px; margin-right: 8px; border-top-left-radius: 12px; border-top-right-radius: 12px; font-size: 17px; font-weight: 700; }
            QTabBar::tab:selected { background: #4b70dc; color: #ffffff; }
            QLineEdit, QTextEdit, QTableWidget, QComboBox { background: #0f131b; border: 1px solid #2f3746; border-radius: 10px; padding: 7px; selection-background-color: #4b70dc; }
            QPushButton { background: #4b70dc; border: 0; border-radius: 10px; padding: 9px 13px; color: #f3f7ff; font-weight: 600; }
            QPushButton:hover { background: #5a7ae0; }
            QPushButton:pressed { background: #3f64d0; }
            QHeaderView::section { background: #202632; color: #d4deec; padding: 7px; border: 0; font-weight: 600; }
            """
        )

    def _build(self) -> None:
        QWidget = self._qt["QWidget"]
        QVBoxLayout = self._qt["QVBoxLayout"]
        QTabWidget = self._qt["QTabWidget"]
        tabs = QTabWidget()
        tabs.addTab(self._build_overview_tab(), "Overview")
        tabs.addTab(self._build_placeholder_tab("OpenFDD Config", "Desktop config editor coming next."), "OpenFDD Config")
        tabs.addTab(self._build_ingest_tab(), "CSV Import")
        tabs.addTab(self._build_placeholder_tab("BACnet tools", "BACnet discovery tooling is being ported to desktop view."), "BACnet tools")
        tabs.addTab(self._build_model_tab(), "Data Model BRICK")
        tabs.addTab(self._build_placeholder_tab("Energy Engineering", "Energy calculations and engineering workflows tab."), "Energy Engineering")
        tabs.addTab(self._build_placeholder_tab("Data Model Testing", "SPARQL testing and graph diagnostics tab."), "Data Model Testing")
        tabs.addTab(self._build_placeholder_tab("Points", "Point inventory and filtering view."), "Points")
        tabs.addTab(self._build_rules_tab(), "Faults")
        tabs.addTab(self._build_placeholder_tab("Plots", "Trend and chart plotting workspace."), "Plots")
        tabs.addTab(self._build_placeholder_tab("Weather data", "Weather timeseries diagnostics and import status."), "Weather data")
        tabs.addTab(self._build_placeholder_tab("Analytics", "Fault analytics dashboard summary panel."), "Analytics")
        tabs.addTab(self._build_placeholder_tab("System resources", "Runtime status and system resource metrics."), "System resources")
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.addWidget(tabs)
        self.window.setCentralWidget(root)

    def _build_overview_tab(self):
        return self._build_placeholder_tab(
            "Open-FDD Desktop Overview",
            "Use CSV Import, Data Model BRICK, and Faults tabs for the full desktop workflow. Remaining tabs mirror the web stack layout.",
        )

    def _build_placeholder_tab(self, title: str, message: str):
        QWidget = self._qt["QWidget"]
        QVBoxLayout = self._qt["QVBoxLayout"]
        QLabel = self._qt["QLabel"]
        panel = QWidget()
        lay = QVBoxLayout(panel)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:18px;font-weight:700;color:#e8edf6;")
        desc = QLabel(message)
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size:14px;color:#aeb8c7;")
        lay.addWidget(heading)
        lay.addWidget(desc)
        lay.addStretch(1)
        return panel

    def _build_model_tab(self):
        QWidget = self._qt["QWidget"]
        QVBoxLayout = self._qt["QVBoxLayout"]
        QHBoxLayout = self._qt["QHBoxLayout"]
        QPushButton = self._qt["QPushButton"]
        QLabel = self._qt["QLabel"]
        QLineEdit = self._qt["QLineEdit"]
        QTableWidget = self._qt["QTableWidget"]
        QTextEdit = self._qt["QTextEdit"]
        QCheckBox = self._qt["QCheckBox"]
        QSplitter = self._qt["QSplitter"]
        Qt = self._qt["Qt"]

        panel = QWidget()
        lay = QVBoxLayout(panel)

        actions_row = QHBoxLayout()
        self.site_name = QLineEdit()
        self.site_name.setPlaceholderText("Site name")
        self.eq_name = QLineEdit()
        self.eq_name.setPlaceholderText("Equipment name")
        self.eq_type = QLineEdit()
        self.eq_type.setPlaceholderText("Equipment type (AHU, VAV, ...)")
        self.point_name = QLineEdit()
        self.point_name.setPlaceholderText("Point external id")
        self.point_brick = QLineEdit()
        self.point_brick.setPlaceholderText("Brick type")
        self.point_rule_input = QLineEdit()
        self.point_rule_input.setPlaceholderText("Rule input key (optional)")

        add_site_btn = QPushButton("Add Site")
        add_site_btn.clicked.connect(self._on_add_site)
        add_eq_btn = QPushButton("Add Equipment")
        add_eq_btn.clicked.connect(self._on_add_equipment)
        add_point_btn = QPushButton("Add Point")
        add_point_btn.clicked.connect(self._on_add_point)
        del_site_btn = QPushButton("Delete Site")
        del_site_btn.clicked.connect(self._on_delete_site)
        del_eq_btn = QPushButton("Delete Equipment")
        del_eq_btn.clicked.connect(self._on_delete_equipment)
        del_point_btn = QPushButton("Delete Point")
        del_point_btn.clicked.connect(self._on_delete_point)
        sync_btn = QPushButton("Sync BRICK TTL")
        sync_btn.clicked.connect(self._on_sync_ttl)
        export_btn = QPushButton("Export JSON")
        export_btn.clicked.connect(self._on_export_model_json)
        import_btn = QPushButton("Import JSON")
        import_btn.clicked.connect(self._on_import_model_json)
        self.import_replace_checkbox = QCheckBox("Replace model on import")
        self.import_replace_checkbox.setChecked(True)

        actions_row.addWidget(QLabel("Site"))
        actions_row.addWidget(self.site_name)
        actions_row.addWidget(add_site_btn)
        actions_row.addWidget(del_site_btn)
        actions_row.addSpacing(12)
        actions_row.addWidget(QLabel("Equipment"))
        actions_row.addWidget(self.eq_name)
        actions_row.addWidget(self.eq_type)
        actions_row.addWidget(add_eq_btn)
        actions_row.addWidget(del_eq_btn)
        actions_row.addSpacing(12)
        actions_row.addWidget(QLabel("Point"))
        actions_row.addWidget(self.point_name)
        actions_row.addWidget(self.point_brick)
        actions_row.addWidget(self.point_rule_input)
        actions_row.addWidget(add_point_btn)
        actions_row.addWidget(del_point_btn)
        actions_row.addWidget(sync_btn)
        actions_row.addWidget(export_btn)
        actions_row.addWidget(import_btn)
        actions_row.addWidget(self.import_replace_checkbox)
        lay.addLayout(actions_row)

        splitter = QSplitter(Qt.Horizontal)
        self.site_table = QTableWidget(0, 2)
        self.site_table.setHorizontalHeaderLabels(["Site ID", "Name"])
        self.eq_table = QTableWidget(0, 4)
        self.eq_table.setHorizontalHeaderLabels(["Equipment ID", "Site ID", "Name", "Type"])
        self.point_table = QTableWidget(0, 6)
        self.point_table.setHorizontalHeaderLabels(["Point ID", "Site ID", "Equipment ID", "External ID", "Brick Type", "Rule Input"])
        splitter.addWidget(self.site_table)
        splitter.addWidget(self.eq_table)
        splitter.addWidget(self.point_table)
        splitter.setSizes([300, 500, 700])
        lay.addWidget(splitter)

        self.model_out = QTextEdit()
        self.model_out.setReadOnly(True)
        self.model_out.setMaximumHeight(170)
        self.model_import_text = QTextEdit()
        self.model_import_text.setPlaceholderText("Paste AI-produced model JSON here ({sites:[], equipment:[], points:[]})")
        self.model_import_text.setMaximumHeight(120)
        apply_paste_btn = QPushButton("Apply Pasted JSON")
        apply_paste_btn.clicked.connect(self._on_apply_pasted_model_json)
        lay.addWidget(self.model_out)
        lay.addWidget(self.model_import_text)
        lay.addWidget(apply_paste_btn)
        self._refresh_model_views()
        return panel

    def _build_ingest_tab(self):
        QWidget = self._qt["QWidget"]
        QVBoxLayout = self._qt["QVBoxLayout"]
        QHBoxLayout = self._qt["QHBoxLayout"]
        QPushButton = self._qt["QPushButton"]
        QLabel = self._qt["QLabel"]
        QLineEdit = self._qt["QLineEdit"]
        QComboBox = self._qt["QComboBox"]
        QFont = self._qt["QFont"]
        Qt = self._qt["Qt"]
        QTextEdit = self._qt["QTextEdit"]

        panel = QWidget()
        self.ingest_drop_host = panel
        lay = QVBoxLayout(panel)

        helper = QLabel("Drag and drop CSV files below or pick with the button.")
        lay.addWidget(helper)

        self.drop_zone = QTextEdit()
        self.drop_zone.setReadOnly(True)
        self.drop_zone.setAcceptDrops(True)
        self.drop_zone.viewport().setAcceptDrops(True)
        self.drop_zone.setPlainText("Drop CSV files here")
        f = QFont()
        f.setPointSize(11)
        self.drop_zone.setFont(f)
        self.drop_zone.setMinimumHeight(120)
        self.drop_zone.setAlignment(Qt.AlignCenter)
        QObject = self._qt["QObject"]
        self._drop_filter_proxy = self._DropEventFilterProxy(self, QObject).instance
        self.drop_zone.installEventFilter(self._drop_filter_proxy)
        self.drop_zone.viewport().installEventFilter(self._drop_filter_proxy)
        panel.setAcceptDrops(True)
        panel.installEventFilter(self._drop_filter_proxy)
        lay.addWidget(self.drop_zone)

        row = QHBoxLayout()
        self.site_selector = QComboBox()
        self.site_selector.setMinimumWidth(280)
        self.site_selector.currentIndexChanged.connect(self._on_site_combo_changed)
        self.site_id_input = QLineEdit()
        self.site_id_input.setPlaceholderText("site id")
        self.source_input_ingest = QLineEdit()
        self.source_input_ingest.setPlaceholderText("source name (default csv)")
        pick_btn = QPushButton("Import CSV -> Feather")
        pick_btn.clicked.connect(self._on_import_csv)
        weather_btn = QPushButton("Run Weather Fetch")
        weather_btn.clicked.connect(self._on_run_weather)
        onboard_btn = QPushButton("Run Onboard Scrape")
        onboard_btn.clicked.connect(self._on_run_onboard)
        ml_btn = QPushButton("Train ML Baseline")
        ml_btn.clicked.connect(self._on_run_ml_baseline)
        self._run_weather_button = weather_btn
        self._run_onboard_button = onboard_btn
        self._run_ml_button = ml_btn
        refresh_sites_btn = QPushButton("Refresh Sites")
        refresh_sites_btn.clicked.connect(self._refresh_site_selector)
        row.addWidget(QLabel("Site"))
        row.addWidget(self.site_selector)
        row.addWidget(QLabel("Site ID"))
        row.addWidget(self.site_id_input)
        row.addWidget(QLabel("Source"))
        row.addWidget(self.source_input_ingest)
        row.addWidget(pick_btn)
        row.addWidget(weather_btn)
        row.addWidget(onboard_btn)
        row.addWidget(ml_btn)
        row.addWidget(refresh_sites_btn)
        lay.addLayout(row)

        ml_row = QHBoxLayout()
        self.ml_target_input = QLineEdit()
        self.ml_target_input.setPlaceholderText("ML target (e.g. SAT (°F))")
        self.ml_features_input = QLineEdit()
        self.ml_features_input.setPlaceholderText("features csv (blank = all numeric)")
        self.ml_lags_input = QLineEdit()
        self.ml_lags_input.setPlaceholderText("lag cols csv (optional)")
        self.ml_rule_flag_input = QLineEdit()
        self.ml_rule_flag_input.setPlaceholderText("rule flag column for overlap (optional)")
        self.ml_quantile_input = QLineEdit()
        self.ml_quantile_input.setPlaceholderText("residual quantile (0.95)")
        self.ml_output_source_input = QLineEdit()
        self.ml_output_source_input.setPlaceholderText("output source (optional)")
        ml_row.addWidget(QLabel("ML target"))
        ml_row.addWidget(self.ml_target_input)
        ml_row.addWidget(QLabel("Features"))
        ml_row.addWidget(self.ml_features_input)
        ml_row.addWidget(QLabel("Lags"))
        ml_row.addWidget(self.ml_lags_input)
        ml_row.addWidget(QLabel("Rule flag"))
        ml_row.addWidget(self.ml_rule_flag_input)
        ml_row.addWidget(QLabel("Q"))
        ml_row.addWidget(self.ml_quantile_input)
        ml_row.addWidget(QLabel("Out source"))
        ml_row.addWidget(self.ml_output_source_input)
        lay.addLayout(ml_row)
        self.ingest_out = QTextEdit()
        self.ingest_out.setReadOnly(True)
        lay.addWidget(self.ingest_out)
        return panel

    def _build_rules_tab(self):
        QWidget = self._qt["QWidget"]
        QVBoxLayout = self._qt["QVBoxLayout"]
        QHBoxLayout = self._qt["QHBoxLayout"]
        QPushButton = self._qt["QPushButton"]
        QLabel = self._qt["QLabel"]
        QLineEdit = self._qt["QLineEdit"]
        QDateTimeEdit = self._qt["QDateTimeEdit"]
        QCheckBox = self._qt["QCheckBox"]
        QDateTime = self._qt["QDateTime"]
        QTextEdit = self._qt["QTextEdit"]

        panel = QWidget()
        lay = QVBoxLayout(panel)
        row = QHBoxLayout()
        self.rules_path = QLineEdit()
        self.rules_path.setPlaceholderText("path to YAML rules directory")
        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText("source name (csv/weather/onboard)")
        self.chunk_size_input = QLineEdit()
        self.chunk_size_input.setPlaceholderText("chunk rows (optional)")
        self.rules_start_dt = QDateTimeEdit()
        self.rules_start_dt.setCalendarPopup(True)
        self.rules_start_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.rules_end_dt = QDateTimeEdit()
        self.rules_end_dt.setCalendarPopup(True)
        self.rules_end_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.rules_use_window = QCheckBox("Use time window")
        self.rules_use_window.setChecked(False)
        bounds_btn = QPushButton("Use Data Bounds")
        bounds_btn.clicked.connect(self._on_rules_use_data_bounds)
        run_btn = QPushButton("Run Rules")
        run_btn.clicked.connect(self._on_run_rules)
        self._run_rules_button = run_btn
        row.addWidget(QLabel("Rules"))
        row.addWidget(self.rules_path)
        row.addWidget(QLabel("Source"))
        row.addWidget(self.source_input)
        row.addWidget(QLabel("Chunk"))
        row.addWidget(self.chunk_size_input)
        row.addWidget(QLabel("Start"))
        row.addWidget(self.rules_start_dt)
        row.addWidget(QLabel("End"))
        row.addWidget(self.rules_end_dt)
        row.addWidget(self.rules_use_window)
        row.addWidget(bounds_btn)
        row.addWidget(run_btn)
        lay.addLayout(row)
        self.rules_out = QTextEdit()
        self.rules_out.setReadOnly(True)
        lay.addWidget(self.rules_out)
        return panel

    def _refresh_model_output(self) -> None:
        model = self.model_service.load()
        self.model_out.setPlainText(str(model))

    def _refresh_model_views(self) -> None:
        QTableWidgetItem = self._qt["QTableWidgetItem"]
        model = self.model_service.load()

        self.site_table.setRowCount(len(model["sites"]))
        for i, row in enumerate(model["sites"]):
            self.site_table.setItem(i, 0, QTableWidgetItem(str(row.get("id", ""))))
            self.site_table.setItem(i, 1, QTableWidgetItem(str(row.get("name", ""))))

        self.eq_table.setRowCount(len(model["equipment"]))
        for i, row in enumerate(model["equipment"]):
            self.eq_table.setItem(i, 0, QTableWidgetItem(str(row.get("id", ""))))
            self.eq_table.setItem(i, 1, QTableWidgetItem(str(row.get("site_id", ""))))
            self.eq_table.setItem(i, 2, QTableWidgetItem(str(row.get("name", ""))))
            self.eq_table.setItem(i, 3, QTableWidgetItem(str(row.get("equipment_type", ""))))

        self.point_table.setRowCount(len(model["points"]))
        for i, row in enumerate(model["points"]):
            self.point_table.setItem(i, 0, QTableWidgetItem(str(row.get("id", ""))))
            self.point_table.setItem(i, 1, QTableWidgetItem(str(row.get("site_id", ""))))
            self.point_table.setItem(i, 2, QTableWidgetItem(str(row.get("equipment_id", ""))))
            self.point_table.setItem(i, 3, QTableWidgetItem(str(row.get("external_id", ""))))
            self.point_table.setItem(i, 4, QTableWidgetItem(str(row.get("brick_type", ""))))
            self.point_table.setItem(i, 5, QTableWidgetItem(str(row.get("fdd_input", ""))))

        self._refresh_model_output()
        self._refresh_site_selector()

    def _on_add_site(self) -> None:
        name = self.site_name.text().strip() or "Site"
        site = self.model_service.create_site(name)
        self._last_selected_site_id = site["id"]
        self.site_id_input.setText(site["id"])
        self._refresh_model_views()

    def _selected_site_id(self) -> str | None:
        idx = self.site_table.currentRow()
        if idx < 0:
            return self._last_selected_site_id
        item = self.site_table.item(idx, 0)
        return item.text().strip() if item else self._last_selected_site_id

    def _selected_equipment_id(self) -> str | None:
        idx = self.eq_table.currentRow()
        if idx < 0:
            return None
        item = self.eq_table.item(idx, 0)
        return item.text().strip() if item else None

    def _selected_point_id(self) -> str | None:
        idx = self.point_table.currentRow()
        if idx < 0:
            return None
        item = self.point_table.item(idx, 0)
        return item.text().strip() if item else None

    def _on_add_equipment(self) -> None:
        site_id = self._selected_site_id() or self.site_id_input.text().strip()
        if not site_id:
            self.model_out.append("\nSelect or create a site first.")
            return
        name = self.eq_name.text().strip() or "Equipment"
        eq_type = self.eq_type.text().strip() or "Equipment"
        self.model_service.create_equipment(site_id=site_id, name=name, equipment_type=eq_type)
        self._refresh_model_views()

    def _on_add_point(self) -> None:
        site_id = self._selected_site_id() or self.site_id_input.text().strip()
        if not site_id:
            self.model_out.append("\nSelect or create a site first.")
            return
        equipment_id = self._selected_equipment_id()
        external_id = self.point_name.text().strip() or "point"
        brick_type = self.point_brick.text().strip() or "Point"
        fdd_input = self.point_rule_input.text().strip() or None
        self.model_service.create_point(
            site_id=site_id,
            equipment_id=equipment_id,
            external_id=external_id,
            brick_type=brick_type,
            fdd_input=fdd_input,
        )
        self._refresh_model_views()

    def _on_delete_site(self) -> None:
        site_id = self._selected_site_id()
        if not site_id:
            return
        self.model_service.delete_site(site_id)
        self._refresh_model_views()

    def _on_delete_equipment(self) -> None:
        eq_id = self._selected_equipment_id()
        if not eq_id:
            return
        self.model_service.delete_device(eq_id)
        self._refresh_model_views()

    def _on_delete_point(self) -> None:
        point_id = self._selected_point_id()
        if not point_id:
            return
        self.model_service.delete_point(point_id)
        self._refresh_model_views()

    def _on_sync_ttl(self) -> None:
        try:
            path = self.ttl_service.sync()
            self._refresh_model_views()
            self.model_out.append(f"\nSynced TTL: {path}")
        except Exception as exc:
            self.model_out.append(f"\nFailed to sync TTL: {exc}\n{traceback.format_exc()}")

    def _on_export_model_json(self) -> None:
        QFileDialog = self._qt["QFileDialog"]
        path, _ = QFileDialog.getSaveFileName(self.window, "Export model JSON", "data-model-export.json", "JSON Files (*.json)")
        if not path:
            return
        try:
            out = self.model_service.export_json(path)
            self.model_out.append(f"\nExported model JSON: {out}")
        except Exception as exc:
            self.model_out.append(f"\nExport failed: {exc}\n{traceback.format_exc()}")

    def _on_import_model_json(self) -> None:
        QFileDialog = self._qt["QFileDialog"]
        path, _ = QFileDialog.getOpenFileName(self.window, "Import model JSON", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            self.model_import_text.setPlainText(text)
            self._on_apply_pasted_model_json()
        except Exception as exc:
            self.model_out.append(f"\nImport file read failed: {exc}\n{traceback.format_exc()}")

    def _on_apply_pasted_model_json(self) -> None:
        import json

        try:
            payload = json.loads(self.model_import_text.toPlainText().strip() or "{}")
            if not isinstance(payload, dict):
                raise ValueError("Model JSON must be an object with sites/equipment/points lists.")
            result = self.model_service.import_json(
                payload,
                replace=bool(self.import_replace_checkbox.isChecked()),
            )
            self._refresh_model_views()
            self.model_out.append(
                f"\nImported JSON -> sites={result['sites']} equipment={result['equipment']} points={result['points']}"
            )
        except Exception as exc:
            self.model_out.append(f"\nImport failed: {exc}\n{traceback.format_exc()}")

    def _refresh_site_selector(self) -> None:
        if not hasattr(self, "site_selector"):
            return
        sites = self.model_service.load().get("sites", [])
        old = self.site_selector.currentData()
        self.site_selector.blockSignals(True)
        self.site_selector.clear()
        for s in sites:
            self.site_selector.addItem(f'{s.get("name","Site")} ({s.get("id","")[:8]})', str(s.get("id", "")))
        if old:
            idx = self.site_selector.findData(old)
            if idx >= 0:
                self.site_selector.setCurrentIndex(idx)
        self.site_selector.blockSignals(False)

    def _on_site_combo_changed(self, _idx: int) -> None:
        site_id = self.site_selector.currentData()
        if site_id:
            self.site_id_input.setText(site_id)
            self._last_selected_site_id = str(site_id)

    def _site_id_for_ingest(self) -> str:
        sid = self.site_id_input.text().strip()
        if sid:
            return sid
        data = self.site_selector.currentData()
        return str(data or "").strip()

    def _on_import_csv(self) -> None:
        QFileDialog = self._qt["QFileDialog"]
        picked, _ = QFileDialog.getOpenFileName(self.window, "Select CSV", "", "CSV Files (*.csv)")
        if not picked:
            return
        site_id = self._site_id_for_ingest()
        if not site_id:
            self.ingest_out.setPlainText("Set a site id first.")
            return
        source = self.source_input_ingest.text().strip() or "csv"
        try:
            result = self.ingest_service.ingest_csv(csv_path=picked, source=source, site_id=site_id)
            self.ingest_out.setPlainText(
                f'Rows: {result["rows"]}\nFeather: {result["feather_path"]}\nMetrics: {result["metrics"]}'
            )
            self._refresh_model_views()
        except Exception as exc:
            self.ingest_out.setPlainText(f"CSV import failed: {exc}\n{traceback.format_exc()}")

    def _on_run_weather(self) -> None:
        site_id = self._site_id_for_ingest()
        if not site_id:
            self.ingest_out.setPlainText("Set a site id first.")
            return
        self.ingest_out.setPlainText("Running weather ingest...")
        self._set_busy(True)
        self._run_in_background(
            lambda: self.ingest_service.ingest_weather(site_id=site_id, days_back=1),
            on_success=lambda result: self._on_ingest_worker_success(f"Weather rows ingested: {result['rows']}"),
            on_error=lambda exc, tb: self.ingest_out.setPlainText(f"Error: {exc}\n{tb}"),
        )

    def _on_run_onboard(self) -> None:
        site_id = self._site_id_for_ingest()
        if not site_id:
            self.ingest_out.setPlainText("Set a site id first.")
            return
        self.ingest_out.setPlainText("Running onboard ingest...")
        self._set_busy(True)
        self._run_in_background(
            lambda: self.ingest_service.ingest_onboard(site_id=site_id),
            on_success=lambda result: (
                self._on_ingest_worker_success(f"Onboard rows ingested: {result['rows']}")
                if result.get("success", True)
                else self.ingest_out.setPlainText(f"Onboard ingest failed: {result.get('error', 'Unknown error')}")
            ),
            on_error=lambda exc, tb: self.ingest_out.setPlainText(f"Error: {exc}\n{tb}"),
        )

    def _on_run_ml_baseline(self) -> None:
        site_id = self._site_id_for_ingest()
        if not site_id:
            self.ingest_out.setPlainText("Set a site id first.")
            return
        target_col = self.ml_target_input.text().strip()
        if not target_col:
            self.ingest_out.setPlainText("Set ML target column first.")
            return
        source = self.source_input_ingest.text().strip() or "csv"
        feature_cols = [c.strip() for c in self.ml_features_input.text().split(",") if c.strip()]
        lag_cols = [c.strip() for c in self.ml_lags_input.text().split(",") if c.strip()]
        rule_flag = self.ml_rule_flag_input.text().strip() or None
        output_source = self.ml_output_source_input.text().strip() or None
        q_text = self.ml_quantile_input.text().strip()
        try:
            q = float(q_text or 0.95)
        except ValueError:
            self.ingest_out.setPlainText("Invalid residual quantile. Enter a number between 0 and 1 (for example 0.95).")
            return
        if not (0.0 < q < 1.0):
            self.ingest_out.setPlainText("Residual quantile must be between 0 and 1 (exclusive).")
            return

        self.ingest_out.setPlainText("Training ML baseline...")
        self._set_busy(True)
        self._run_in_background(
            lambda: self.ingest_service.train_ml_baseline(
                site_id=site_id,
                source=source,
                target_col=target_col,
                feature_cols=feature_cols or None,
                lag_cols=lag_cols or None,
                residual_quantile=q,
                rule_flag_col=rule_flag,
                output_source=output_source,
            ),
            on_success=lambda result: self._on_ml_worker_success(result),
            on_error=lambda exc, tb: self.ingest_out.setPlainText(f"ML run failed: {exc}\n{tb}"),
        )

    def _on_ml_worker_success(self, result: dict) -> None:
        def _f(name: str) -> float:
            val = result.get(name)
            if val is None:
                raise ValueError(f"Missing ML result value: {name}")
            return float(val)

        model_name = str(result.get("model_name") or "unknown")
        rows_train = int(result.get("rows_train") or 0)
        rows_test = int(result.get("rows_test") or 0)
        rows_scored = int(result.get("rows_scored") or 0)
        overlap = int(result.get("overlap_with_rule_flag") or 0)
        output_source = str(result.get("output_source") or "")
        storage_ref = str(result.get("storage_ref") or "")
        self.ingest_out.setPlainText(
            "ML baseline completed\n"
            f"Model: {model_name}\n"
            f"Rows train/test/scored: {rows_train}/{rows_test}/{rows_scored}\n"
            f"R2: {_f('r2'):.4f}  MAE: {_f('mae'):.4f}  RMSE: {_f('rmse'):.4f}\n"
            f"Residual threshold: {_f('residual_threshold'):.4f}\n"
            f"Rule overlap rows: {overlap}\n"
            f"Output source: {output_source}\n"
            f"Storage: {storage_ref}"
        )
        self._refresh_model_views()

    def _on_run_rules(self) -> None:
        site_id = self._site_id_for_ingest()
        source = self.source_input.text().strip() or "csv"
        if not site_id:
            self.rules_out.setPlainText("Set a site id first.")
            return
        try:
            rules_path = self.rules_path.text().strip()
            if not rules_path:
                self.rules_out.setPlainText("Provide rules path.")
                return
            chunk = 0
            try:
                chunk = int(self.chunk_size_input.text().strip() or 0)
            except ValueError:
                chunk = 0
            Qt = self._qt["Qt"]
            if self.rules_use_window.isChecked():
                start_ts = self.rules_start_dt.dateTime().toString(Qt.ISODate)
                end_ts = self.rules_end_dt.dateTime().toString(Qt.ISODate)
            else:
                start_ts = ""
                end_ts = ""
            self.rules_out.setPlainText("Running rule loop...")
            self._set_busy(True)
            self._run_in_background(
                lambda: self._run_rules_job(
                    site_id=site_id,
                    source=source,
                    rules_path=rules_path,
                    chunk=chunk,
                    start_ts=start_ts,
                    end_ts=end_ts,
                ),
                on_success=lambda payload: self.rules_out.setPlainText(str(payload)),
                on_error=lambda exc, tb: self.rules_out.setPlainText(f"Rule run failed: {exc}\n{tb}"),
            )
        except Exception as exc:
            self.rules_out.setPlainText(f"Rule run failed: {exc}\n{traceback.format_exc()}")

    def _on_rules_use_data_bounds(self) -> None:
        site_id = self._site_id_for_ingest()
        source = self.source_input.text().strip() or "csv"
        if not site_id:
            self.rules_out.setPlainText("Set a site id first.")
            return
        self.rules_out.setPlainText("Loading data bounds...")

        def _job() -> dict:
            return self.ingest_service.source_time_bounds(source=source, site_id=site_id)

        def _on_ok(info: dict) -> None:
            Qt = self._qt["Qt"]
            QDateTime = self._qt["QDateTime"]
            if not info.get("rows"):
                self.rules_out.setPlainText(f"No data found for site='{site_id}' source='{source}'.")
                return
            if not info.get("start") or not info.get("end"):
                self.rules_out.setPlainText("Data found, but no parseable timestamp bounds were available.")
                return
            start_dt = QDateTime.fromString(str(info["start"]), Qt.ISODate)
            end_dt = QDateTime.fromString(str(info["end"]), Qt.ISODate)
            if start_dt.isValid():
                self.rules_start_dt.setDateTime(start_dt)
            if end_dt.isValid():
                self.rules_end_dt.setDateTime(end_dt)
            self.rules_use_window.setChecked(True)
            self.rules_out.setPlainText(
                f"Loaded bounds for source '{source}' ({info['rows']} rows)\n"
                f"Start: {self.rules_start_dt.dateTime().toString(Qt.ISODate)}\n"
                f"End: {self.rules_end_dt.dateTime().toString(Qt.ISODate)}"
            )

        def _on_err(exc: str, tb: str) -> None:
            self.rules_out.setPlainText(f"Failed to load data bounds: {exc}\n{tb}")

        self._run_in_background(_job, on_success=_on_ok, on_error=_on_err)

    def _run_rules_job(self, site_id: str, source: str, rules_path: str, chunk: int, start_ts: str, end_ts: str) -> str:
        frame = self.ingest_service.load_source_frame_window(
            source=source,
            site_id=site_id,
            start_ts=start_ts or None,
            end_ts=end_ts or None,
        )
        if frame.empty:
            return "No Feather data found for site/source in selected time window."
        model = self.model_service.load()
        by_model = build_column_map_from_model_points(model, site_id)
        # ``resolve_column_map`` returns {} when rdflib is missing or the TTL file is absent; parse/query
        # failures propagate so corrupt TTL is not silently ignored.
        ttl_map = BrickService(ttl_path=self.ttl_service.ttl_path).resolve_column_map()
        cmap = {**ttl_map, **by_model}
        out = run_rule_loop_batched(
            frame,
            RuleLoopConfig(rules_path=rules_path, chunk_rows=chunk, column_map=cmap or None),
        )
        fault_cols = [c for c in out.columns if c.endswith("_flag")]
        fault_totals = {c: int(out[c].sum()) for c in fault_cols}
        tail_preview = out.tail(10).to_string(index=False)
        return (
            f"Input rows: {len(frame.index)}\nOutput rows: {len(out.index)}\nColumns: {list(out.columns)}\n"
            f"Window: {start_ts} -> {end_ts}\n"
            f"Fault totals: {fault_totals}\nTTL: {model_ttl_path()}\n\nPreview:\n{tail_preview}"
        )

    def _set_busy(self, busy: bool) -> None:
        for btn in (self._run_weather_button, self._run_onboard_button, self._run_ml_button, self._run_rules_button):
            if btn is not None:
                btn.setEnabled(not busy)

    def _on_ingest_worker_success(self, message: str) -> None:
        self.ingest_out.setPlainText(message)
        self._refresh_model_views()

    def _run_in_background(self, fn, on_success, on_error) -> None:
        QObject = self._qt["QObject"]
        Signal = self._qt["Signal"]
        QRunnable = self._qt["QRunnable"]

        class _WorkerSignals(QObject):
            success = Signal(object)
            error = Signal(str, str)
            finished = Signal()

        class _Worker(QRunnable):
            def __init__(self):
                super().__init__()
                self.signals = _WorkerSignals()

            def run(self):
                try:
                    result = fn()
                    self.signals.success.emit(result)
                except Exception as exc:  # noqa: BLE001
                    self.signals.error.emit(str(exc), traceback.format_exc())
                finally:
                    self.signals.finished.emit()

        worker = _Worker()
        worker.signals.success.connect(on_success)
        worker.signals.error.connect(on_error)
        worker.signals.finished.connect(self._on_worker_finished)
        self._active_jobs += 1
        self._thread_pool.start(worker)

    def _on_worker_finished(self) -> None:
        self._active_jobs = max(0, self._active_jobs - 1)
        if self._active_jobs == 0:
            self._set_busy(False)

    def eventFilter(self, watched, event):
        QEvent = self._qt["QEvent"]
        try:
            drop_zone = getattr(self, "drop_zone", None)
            drop_viewport = drop_zone.viewport() if drop_zone is not None else None
        except RuntimeError:
            return False
        if watched is drop_zone or watched is drop_viewport or watched is getattr(self, "ingest_drop_host", None):
            if event.type() == QEvent.Type.DragEnter:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            if event.type() == QEvent.Type.DragMove:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                    return True
            if event.type() == QEvent.Type.Drop:
                site_id = self._site_id_for_ingest()
                if not site_id:
                    self.ingest_out.setPlainText("Set a site id first.")
                    return True
                urls = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
                csvs = [p for p in urls if p.lower().endswith(".csv")]
                if not csvs:
                    self.ingest_out.setPlainText("Drop one or more CSV files.")
                    return True
                lines = []
                source = self.source_input_ingest.text().strip() or "csv"
                for csv in csvs:
                    try:
                        res = self.ingest_service.ingest_csv(csv_path=csv, source=source, site_id=site_id)
                        lines.append(f'{Path(csv).name}: rows={res["rows"]}, metrics={len(res["metrics"])}')
                    except Exception as exc:
                        lines.append(f"{Path(csv).name}: ERROR {exc}")
                self.drop_zone.setPlainText("\n".join(csvs))
                self.ingest_out.setPlainText("\n".join(lines))
                self._refresh_model_views()
                event.acceptProposedAction()
                return True
        return False

