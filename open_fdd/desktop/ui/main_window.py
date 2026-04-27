from __future__ import annotations

from pathlib import Path

import pandas as pd

from open_fdd.desktop.drivers.csv_driver import ingest_csv_to_feather
from open_fdd.desktop.rules.rule_loop import RuleLoopConfig, run_rule_loop_batched
from open_fdd.desktop.services.model_service import ModelService
from open_fdd.desktop.services.ttl_service import TtlService
from open_fdd.desktop.storage.feather_store import FeatherStore
from open_fdd.desktop.storage.paths import model_ttl_path


class DesktopMainWindow:
    """
    Wrapper to keep import-time dependency on PySide6 optional.
    """

    def __init__(self) -> None:
        from PySide6.QtWidgets import (
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QPushButton,
            QTabWidget,
            QTextEdit,
            QVBoxLayout,
            QWidget,
            QFileDialog,
        )

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
            "QFileDialog": QFileDialog,
        }
        self.window = QMainWindow()
        self.window.setWindowTitle("Open-FDD Desktop")
        self.window.resize(1200, 760)
        self.model_service = ModelService()
        self.ttl_service = TtlService()
        self.feather_store = FeatherStore()
        self._build()

    def _build(self) -> None:
        QWidget = self._qt["QWidget"]
        QVBoxLayout = self._qt["QVBoxLayout"]
        QTabWidget = self._qt["QTabWidget"]
        tabs = QTabWidget()
        tabs.addTab(self._build_model_tab(), "Data Model")
        tabs.addTab(self._build_ingest_tab(), "Ingest")
        tabs.addTab(self._build_rules_tab(), "Rules")
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.addWidget(tabs)
        self.window.setCentralWidget(root)

    def _build_model_tab(self):
        QWidget = self._qt["QWidget"]
        QVBoxLayout = self._qt["QVBoxLayout"]
        QHBoxLayout = self._qt["QHBoxLayout"]
        QPushButton = self._qt["QPushButton"]
        QLabel = self._qt["QLabel"]
        QLineEdit = self._qt["QLineEdit"]
        QTextEdit = self._qt["QTextEdit"]

        panel = QWidget()
        lay = QVBoxLayout(panel)
        row = QHBoxLayout()
        self.site_name = QLineEdit()
        self.site_name.setPlaceholderText("Site name")
        add_btn = QPushButton("Add Site")
        add_btn.clicked.connect(self._on_add_site)
        sync_btn = QPushButton("Sync BRICK TTL")
        sync_btn.clicked.connect(self._on_sync_ttl)
        row.addWidget(QLabel("Site"))
        row.addWidget(self.site_name)
        row.addWidget(add_btn)
        row.addWidget(sync_btn)
        lay.addLayout(row)
        self.model_out = QTextEdit()
        self.model_out.setReadOnly(True)
        lay.addWidget(self.model_out)
        self._refresh_model_output()
        return panel

    def _build_ingest_tab(self):
        QWidget = self._qt["QWidget"]
        QVBoxLayout = self._qt["QVBoxLayout"]
        QHBoxLayout = self._qt["QHBoxLayout"]
        QPushButton = self._qt["QPushButton"]
        QLabel = self._qt["QLabel"]
        QLineEdit = self._qt["QLineEdit"]
        QTextEdit = self._qt["QTextEdit"]

        panel = QWidget()
        lay = QVBoxLayout(panel)
        row = QHBoxLayout()
        self.site_id_input = QLineEdit()
        self.site_id_input.setPlaceholderText("site id")
        pick_btn = QPushButton("Import CSV -> Feather")
        pick_btn.clicked.connect(self._on_import_csv)
        row.addWidget(QLabel("Site ID"))
        row.addWidget(self.site_id_input)
        row.addWidget(pick_btn)
        lay.addLayout(row)
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
        QTextEdit = self._qt["QTextEdit"]

        panel = QWidget()
        lay = QVBoxLayout(panel)
        row = QHBoxLayout()
        self.rules_path = QLineEdit()
        self.rules_path.setPlaceholderText("path to YAML rules directory")
        self.source_input = QLineEdit()
        self.source_input.setPlaceholderText("source name (csv/weather/onboard)")
        run_btn = QPushButton("Run Rules")
        run_btn.clicked.connect(self._on_run_rules)
        row.addWidget(QLabel("Rules"))
        row.addWidget(self.rules_path)
        row.addWidget(QLabel("Source"))
        row.addWidget(self.source_input)
        row.addWidget(run_btn)
        lay.addLayout(row)
        self.rules_out = QTextEdit()
        self.rules_out.setReadOnly(True)
        lay.addWidget(self.rules_out)
        return panel

    def _refresh_model_output(self) -> None:
        model = self.model_service.load()
        self.model_out.setPlainText(str(model))

    def _on_add_site(self) -> None:
        name = self.site_name.text().strip() or "Site"
        site = self.model_service.create_site(name)
        self.site_id_input.setText(site["id"])
        self._refresh_model_output()

    def _on_sync_ttl(self) -> None:
        path = self.ttl_service.sync()
        self._refresh_model_output()
        self.model_out.append(f"\nSynced TTL: {path}")

    def _on_import_csv(self) -> None:
        QFileDialog = self._qt["QFileDialog"]
        picked, _ = QFileDialog.getOpenFileName(self.window, "Select CSV", "", "CSV Files (*.csv)")
        if not picked:
            return
        site_id = self.site_id_input.text().strip()
        if not site_id:
            self.ingest_out.setPlainText("Set a site id first.")
            return
        result = ingest_csv_to_feather(csv_path=picked, source="csv", site_id=site_id, store=self.feather_store)
        self.ingest_out.setPlainText(
            f"Rows: {result.rows}\nFeather: {result.file_path}\nTimestamp: {result.timestamp_column}\nMetrics: {result.metric_columns}"
        )

    def _on_run_rules(self) -> None:
        site_id = self.site_id_input.text().strip()
        source = self.source_input.text().strip() or "csv"
        if not site_id:
            self.rules_out.setPlainText("Set a site id first.")
            return
        frame = self.feather_store.read_site_frames(source=source, site_id=site_id)
        if frame.empty:
            self.rules_out.setPlainText("No Feather data found for site/source.")
            return
        rules_path = self.rules_path.text().strip()
        if not rules_path:
            self.rules_out.setPlainText("Provide rules path.")
            return
        out = run_rule_loop_batched(frame, RuleLoopConfig(rules_path=rules_path))
        self.rules_out.setPlainText(
            f"Input rows: {len(frame.index)}\nOutput rows: {len(out.index)}\nColumns: {list(out.columns)}\nTTL: {model_ttl_path()}"
        )

