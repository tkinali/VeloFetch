"""
Application bootstrap: QApplication, theme, main window, event loop.
"""

import sys


def run():
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow
    from .theme import app_icon, apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName("VeloFetch")
    app.setOrganizationName("VeloFetch")
    app.setDesktopFileName("velofetch")  # Wayland taskbar/desktop matching
    app.setQuitOnLastWindowClosed(True)
    app.setWindowIcon(app_icon())
    apply_theme(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
