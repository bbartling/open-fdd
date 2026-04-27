from __future__ import annotations

import sys


def launch_desktop() -> int:
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QThread
    except ImportError as exc:
        raise RuntimeError(
            "PySide6 is not installed. Install desktop extras: pip install open-fdd[desktop]"
        ) from exc
    from open_fdd.desktop.ui.main_window import DesktopMainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    win = DesktopMainWindow()
    win.window.show()
    thread = QThread.currentThread()
    if hasattr(thread, "loopLevel") and thread.loopLevel() > 0:
        return 0
    return app.exec()

