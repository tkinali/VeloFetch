"""
Thread bridge: engine and HTTP-server callbacks arrive on worker threads;
Qt widgets may only be touched from the GUI thread. Signal emissions are
queued to the receiving (main) thread automatically.
"""

from PySide6.QtCore import QObject, Signal


class EngineBridge(QObject):
    """Marshals engine task updates onto the Qt main thread."""

    task_updated = Signal(object)   # carries a DownloadTask (or fake)
    show_requested = Signal()

    def engine_on_update(self, task):
        """Pass as DownloadEngine(on_update=...)."""
        self.task_updated.emit(task)

    def server_on_show(self):
        """Pass as VeloFetchServer(on_show=...)."""
        self.show_requested.emit()
