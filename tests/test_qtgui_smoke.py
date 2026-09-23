"""
Smoke tests for the Qt GUI, rendered offscreen.
Skipped automatically when PySide6 or a display (real/offscreen) is missing.
"""

import os
import types

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp(tmp_path_factory):
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    import vf.core.server as srv_mod
    from vf.core.config import Config
    from vf.core.database import Database

    # The throw-away home comes from the autouse isolated_home fixture in
    # tests/conftest.py; here the singleton only gets deterministic values.
    # The defaults splat goes first so the two overrides below actually win.
    cfg = Config()
    original = dict(cfg._config_data)
    cfg._config_data.clear()
    cfg._config_data.update({
        **cfg.defaults,
        "download_dir": str(tmp_path / "downloads"),
        "language": "tr",
    })
    monkeypatch.setattr(cfg, "save", lambda: None)

    os.makedirs(tmp_path / "downloads", exist_ok=True)

    monkeypatch.setattr(
        "vf.qtgui.main_window.Database",
        lambda db_file: Database(tmp_path / "db.sqlite"),
    )
    monkeypatch.setattr(
        srv_mod.VeloFetchServer, "start", lambda self: False,
    )
    monkeypatch.setattr(
        srv_mod.VeloFetchServer, "stop", lambda self: None,
    )

    from vf.qtgui.main_window import MainWindow
    win = MainWindow()
    # Deterministic cards: the 300 ms refresh timer evicts every card whose
    # task the engine has never seen (the _fake() tasks below), so a slow CI
    # machine would otherwise turn these tests into KeyErrors. Tests that want
    # a refresh call win._refresh_ui() themselves.
    win._timer.stop()
    win.show()
    yield win
    win.engine.shutdown()
    win.close()
    cfg._config_data.clear()
    cfg._config_data.update(original)


def _fake(status, prog=0.5, speed=100, fname="file.iso", err=None):
    return types.SimpleNamespace(
        id=abs(hash(fname)) % 100000, filename=fname, save_path="/tmp/" + fname,
        url="https://example.com/" + fname,
        total_size=1000, downloaded_size=int(1000 * prog), status=status,
        supports_resume=True, error_message=err, retry_count=0, cookies=None,
        current_speed=speed, progress=prog * 100, eta=1,
        checksum=None, checksum_ok=None,
    )


def test_main_window_builds(window, qapp):
    qapp.processEvents()
    assert window.windowTitle() == "VeloFetch"
    assert len(window._chips) == 5


def test_cards_add_and_filter(window, qapp):
    window._add_card(_fake("downloading", 0.5, 100, "a.iso"))
    window._add_card(_fake("completed", 1.0, 0, "b.zip"))
    qapp.processEvents()

    assert len(window._cards) == 2
    assert not window._empty_label.isVisible()

    # Filter: completed only hides the downloading card
    window._on_filter("completed")
    qapp.processEvents()
    assert not window._cards[abs(hash("a.iso")) % 100000].isVisible()
    assert window._cards[abs(hash("b.zip")) % 100000].isVisible()

    window._on_filter("all")
    qapp.processEvents()
    assert window._cards[abs(hash("a.iso")) % 100000].isVisible()


def test_card_added_under_filter_stays_in_list(window, qapp):
    """A card added while a non-matching filter is active must live in the
    list layout, not become a stray top-level window when it is shown."""
    window._on_filter("completed")
    task = _fake("downloading", 0.3, 100, "filtered.iso")
    window._add_card(task)
    qapp.processEvents()

    card = window._cards[task.id]
    assert window._list_layout.indexOf(card) != -1
    assert not card.isVisible()

    window._on_filter("all")
    qapp.processEvents()
    assert card.isWindow() is False
    assert window._list_layout.indexOf(card) != -1
    assert card.isVisible()


def test_add_card_twice_keeps_one_card(window, qapp):
    """Re-adding the same task updates its card instead of orphaning it."""
    task = _fake("downloading", 0.2, 100, "dup.iso")
    window._add_card(task)
    first = window._cards[task.id]
    window._add_card(_fake("completed", 1.0, 0, "dup.iso"))
    qapp.processEvents()

    assert window._cards[task.id] is first
    assert len(window._cards) == 1
    assert window._list_layout.indexOf(first) != -1


def test_empty_label_follows_visible_cards(window, qapp):
    """A filter or a search that matches nothing explains itself instead of
    leaving a blank pane behind."""
    from vf.i18n import t

    assert window._empty_label.isVisible()   # nothing downloaded yet

    window._on_filter("completed")
    window._add_card(_fake("downloading", 0.3, 100, "only.iso"))
    qapp.processEvents()
    assert not any(c.isVisible() for c in window._cards.values())
    assert window._empty_label.isVisible()
    assert t("empty_filtered_title") in window._empty_label.text()

    window._on_filter("all")
    qapp.processEvents()
    assert window._empty_label.isHidden()

    window._search.setText("nomatch")
    qapp.processEvents()
    assert window._empty_label.isVisible()

    window._search.setText("")
    qapp.processEvents()
    assert window._empty_label.isHidden()


def test_card_remove_button_does_not_strand_the_card(window, qapp):
    """The card's own remove button goes through the window, so no dead
    widget is left in _cards to break the next filter."""
    from PySide6.QtCore import QEvent

    task = window.engine.add_download("https://example.com/gone.iso")
    window.db.update_status(task.id, "completed")
    task.status = "completed"
    window._add_card(task)
    qapp.processEvents()
    card = window._cards[task.id]

    card._buttons["remove"].click()
    qapp.processEvents()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)   # actually destroy it

    assert window._cards == {}
    assert task.id not in {t.id for t in window.engine.get_all_tasks()}
    # Completed downloads are archived, not deleted
    assert [r["id"] for r in window.db.get_history()] == [task.id]
    # Filtering still works: a stranded card would raise RuntimeError here
    window._apply_filter()
    window._on_filter("completed")
    assert "0" in window._chips["all"].text()


def test_card_states_and_buttons(window, qapp):
    from vf.qtgui.download_card import DownloadCard
    card = DownloadCard(_fake("paused"), window.engine)
    card.update_task(_fake("downloading"))
    assert not card._buttons["pause"].isHidden()
    assert card._buttons["folder"].isHidden()
    card.update_task(_fake("completed"))
    assert card._buttons["folder"].isHidden() is False
    assert card._buttons["pause"].isHidden()


def test_settings_dialog_persists(window, qapp):
    from vf.qtgui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window, window.config, on_save=window._on_settings_saved)
    dlg._max_concurrent.setValue(6)
    dlg._segmented.setChecked(False)
    dlg._on_save()
    assert window.config.get("max_concurrent") == 6
    assert window.config.get("segmented") is False


def test_add_dialog_validates_url(window, qapp, monkeypatch):
    from vf.qtgui.add_dialog import AddDownloadDialog
    shown = []
    monkeypatch.setattr(
        "PySide6.QtWidgets.QMessageBox.warning",
        lambda *a, **k: shown.append(a),
    )
    dlg = AddDownloadDialog(window, window.engine)
    dlg._url.setText("not-a-url")
    dlg._on_add()
    assert shown  # warning was raised, no task added
    assert dlg.result_task is None


def test_history_page_cards(window, qapp):
    """History shows card-style entries with details data available."""
    rec_id = window.db.add_download(
        "https://example.com/hist.iso", "hist.iso", "/tmp/hist.iso", 1024
    )
    window.db.update_status(rec_id, "completed")
    window.db.archive_download(rec_id)

    window._toggle_history()   # open history page
    qapp.processEvents()
    assert window._stack.currentIndex() == 1
    assert len(window._history_cards) == 1
    card = window._history_cards[0]
    assert card.record["filename"] == "hist.iso"
    assert not window._history_empty.isVisible()

    # Toggle button reflects the open state
    assert window._history_btn.isChecked()

    window._toggle_history()   # back to downloads
    qapp.processEvents()
    assert window._stack.currentIndex() == 0
    assert not window._history_btn.isChecked()


def test_history_remove_and_clear(window, qapp):
    rec_id = window.db.add_download(
        "https://example.com/x.iso", "x.iso", "/tmp/x.iso", 10
    )
    window.db.update_status(rec_id, "completed")
    window.db.archive_download(rec_id)

    window._toggle_history()   # open the history page first
    qapp.processEvents()
    assert len(window._history_cards) == 1
    window._delete_history_record(window._history_cards[0].record)
    qapp.processEvents()
    assert len(window._history_cards) == 0
    assert not window._history_empty.isHidden()

    window._on_clear_history()
    assert window.db.get_history() == []


def test_history_delete_unarchived_drops_main_list_card(window, qapp):
    """A completed download shown in both views disappears from both when
    its history row is deleted."""
    task = window.engine.add_download("https://example.com/live.iso")
    window.db.update_status(task.id, "completed")
    task.status = "completed"
    window._add_card(task)
    qapp.processEvents()
    assert task.id in window._cards

    window._toggle_history()
    qapp.processEvents()
    assert len(window._history_cards) == 1

    window._delete_history_record(window._history_cards[0].record)
    qapp.processEvents()

    assert window._history_cards == []
    assert task.id not in window._cards
    assert window.db.get_download(task.id) is None
    assert task.id not in {t.id for t in window.engine.get_all_tasks()}


def test_clear_history_drops_unarchived_main_list_cards(window, qapp):
    """Clear History also clears the completed cards it was listing."""
    done = window.engine.add_download("https://example.com/done.iso")
    window.db.update_status(done.id, "completed")
    done.status = "completed"
    window._add_card(done)

    paused = window.engine.add_download("https://example.com/paused.iso")
    window.db.update_status(paused.id, "paused")
    paused.status = "paused"
    window._add_card(paused)
    qapp.processEvents()

    window._toggle_history()
    qapp.processEvents()
    window._on_clear_history()
    qapp.processEvents()

    assert window.db.get_history() == []
    assert done.id not in window._cards
    # An unfinished download is not history and must stay in the list
    assert paused.id in window._cards
    assert window.db.get_download(paused.id) is not None


def test_history_delete_updates_counts_immediately(window, qapp):
    """Status bar and chips are recomputed after the task is gone, not
    before — an idle app never runs _refresh_ui() to repair them."""
    from vf.i18n import t

    task = window.engine.add_download("https://example.com/counted.iso")
    window.db.update_status(task.id, "completed")
    task.status = "completed"
    window._add_card(task)
    qapp.processEvents()
    assert window._count_label.text() == t("status_counts", active=0, total=1)
    assert window._chips["all"].text().endswith("1")

    window._toggle_history()
    qapp.processEvents()
    window._delete_history_record(window._history_cards[0].record)
    qapp.processEvents()

    # No _refresh_ui() in between: the counts must already be right
    assert window._count_label.text() == t("status_counts", active=0, total=0)
    assert window._chips["all"].text().endswith("0")
    assert window._chips["completed"].text().endswith("0")


def test_clear_history_updates_counts_immediately(window, qapp):
    """Clear History leaves the counts on the tasks that survived it."""
    from vf.i18n import t

    for name in ("one.iso", "two.iso"):
        done = window.engine.add_download("https://example.com/" + name)
        window.db.update_status(done.id, "completed")
        done.status = "completed"
        window._add_card(done)
    paused = window.engine.add_download("https://example.com/held.iso")
    window.db.update_status(paused.id, "paused")
    paused.status = "paused"
    window._add_card(paused)
    qapp.processEvents()

    window._toggle_history()
    qapp.processEvents()
    window._on_clear_history()
    qapp.processEvents()

    assert len(window.engine.get_all_tasks()) == 1
    assert window._count_label.text() == t("status_counts", active=0, total=1)
    assert window._chips["all"].text().endswith("1")
    assert window._chips["completed"].text().endswith("0")
    assert window._chips["paused"].text().endswith("1")


def test_forget_task_does_not_join_finished_worker(window, qapp):
    """A finished download's worker is only winding down (it still owes a
    desktop notification); joining it would freeze the GUI thread."""
    task = window.engine.add_download("https://example.com/fast.iso")
    window.db.update_status(task.id, "completed")
    task.status = "completed"
    window._add_card(task)

    class _Worker:
        """Stand-in for a worker thread that has not returned yet."""
        joined = False

        def join(self, timeout=None):
            _Worker.joined = True

        def is_alive(self):
            return True

    window.engine._threads[task.id] = _Worker()
    window._forget_task(task.id)

    assert _Worker.joined is False
    assert task.id not in window._cards
    assert task.id not in {t.id for t in window.engine.get_all_tasks()}
    assert task.id not in window.engine._threads


def test_details_dialog_fields(window, qapp):
    from vf.qtgui.details_dialog import DetailsDialog, _duration
    rec = window.db.add_download(
        "https://example.com/d.iso", "d.iso", "/tmp/d.iso", 2048
    )
    window.db.update_status(rec, "completed")
    record = window.db.get_download(rec)

    dlg = DetailsDialog(window, record)
    labels = dlg.findChildren(type(dlg))  # noqa — keep dialog alive briefly
    text = " ".join(
        w.text() for w in dlg.findChildren(
            __import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel
        )
    )
    assert "d.iso" in text
    assert "2.00 KB" in text
    # duration parses cleanly for a fresh record
    assert _duration(record) is None or _duration(record) >= 0
    dlg.deleteLater()


def test_card_context_menus_unified(window, qapp):
    """One context menu per card: filename labels route their menu to the
    card, and both menus offer copy-filename."""
    from PySide6.QtCore import Qt

    from vf.i18n import t
    from vf.qtgui.download_card import DownloadCard

    task = _fake("completed", 1.0, 0, "a.iso")
    card = DownloadCard(task, window.engine)
    # Label no longer opens the built-in Copy/Select-All menu
    assert card._name.contextMenuPolicy() == Qt.PreventContextMenu
    texts = [a.text() for a in card._build_context_menu().actions()]
    assert t("ctx_copy_name") in texts
    assert t("ctx_copy_url") in texts

    rec = {
        "id": 1, "filename": "h.iso", "save_path": "/tmp/h", "url": "u",
        "total_size": 10, "created_at": "2026-01-01T10:00:00",
        "completed_at": None,
    }
    from vf.qtgui.history_card import HistoryCard
    hcard = HistoryCard(rec, lambda r: None, lambda r: None)
    assert hcard._name.contextMenuPolicy() == Qt.PreventContextMenu
    htexts = [a.text() for a in hcard._build_menu().actions()]
    assert t("ctx_copy_name") in htexts
    assert t("btn_details") in htexts
    card.deleteLater()
    hcard.deleteLater()


def test_theme_combobox_arrow_renders(qapp):
    """The language combo arrow must be a drawn triangle, not a square."""
    import os

    from PySide6.QtWidgets import QComboBox

    from vf.qtgui.theme import apply_theme
    apply_theme(qapp)

    arrow = os.path.expanduser("~/.cache/velofetch/arrow-down.png")
    assert os.path.exists(arrow)
    assert "__ARROW_DOWN__" not in qapp.styleSheet()

    combo = QComboBox()
    combo.addItems(["Türkçe", "English"])
    combo.resize(160, 32)
    combo.show()
    qapp.processEvents()
    img = combo.grab().toImage()
    arrow_px = sum(
        1
        for y in range(img.height())
        for x in range(img.width() - 24, img.width())
        if img.pixelColor(x, y).name() == "#a9a9bd"
    )
    assert arrow_px >= 6, f"arrow did not render ({arrow_px}px)"
    combo.deleteLater()
