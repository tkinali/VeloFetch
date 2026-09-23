"""Tests for database module."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vf.core.database import Database


class TestDatabase:
    def setup_method(self):
        """Create a temporary database for each test."""
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db = Database(self.tmp.name)

    def teardown_method(self):
        """Clean up temporary database."""
        self.tmp.close()
        os.unlink(self.tmp.name)

    def test_add_download(self):
        dl_id = self.db.add_download(
            "http://example.com/file.zip", "file.zip", "/tmp/file.zip", 1024
        )
        assert dl_id is not None
        assert dl_id > 0

    def test_get_download(self):
        dl_id = self.db.add_download(
            "http://example.com/file.zip", "file.zip", "/tmp/file.zip", 1024
        )
        record = self.db.get_download(dl_id)
        assert record is not None
        assert record["url"] == "http://example.com/file.zip"
        assert record["filename"] == "file.zip"
        assert record["status"] == "pending"

    def test_update_status(self):
        dl_id = self.db.add_download(
            "http://example.com/file.zip", "file.zip", "/tmp/file.zip", 1024
        )
        self.db.update_status(dl_id, "downloading")
        record = self.db.get_download(dl_id)
        assert record["status"] == "downloading"

    def test_update_progress(self):
        dl_id = self.db.add_download(
            "http://example.com/file.zip", "file.zip", "/tmp/file.zip", 1024
        )
        self.db.update_progress(dl_id, 512)
        record = self.db.get_download(dl_id)
        assert record["downloaded_size"] == 512

    def test_increment_retry(self):
        dl_id = self.db.add_download(
            "http://example.com/file.zip", "file.zip", "/tmp/file.zip", 1024
        )
        self.db.increment_retry(dl_id)
        self.db.increment_retry(dl_id)
        count = self.db.get_retry_count(dl_id)
        assert count == 2

    def test_remove_download(self):
        dl_id = self.db.add_download(
            "http://example.com/file.zip", "file.zip", "/tmp/file.zip", 1024
        )
        self.db.remove_download(dl_id)
        record = self.db.get_download(dl_id)
        assert record is None

    def test_get_active_downloads(self):
        id1 = self.db.add_download("http://a.com/1", "1.zip", "/tmp/1", 100)
        id2 = self.db.add_download("http://a.com/2", "2.zip", "/tmp/2", 200)
        self.db.update_status(id1, "downloading")
        self.db.update_status(id2, "completed")
        # Completed (not yet archived) stays in the main list alongside active
        active = self.db.get_active_downloads()
        assert {d["id"] for d in active} == {id1, id2}

        # Archiving moves it out of the main list
        self.db.archive_download(id2)
        active = self.db.get_active_downloads()
        assert [d["id"] for d in active] == [id1]

    def test_reset_for_resume(self):
        dl_id = self.db.add_download(
            "http://example.com/file.zip", "file.zip", "/tmp/file.zip", 1024
        )
        self.db.update_status(dl_id, "failed", "Connection error")
        self.db.reset_for_resume(dl_id)
        record = self.db.get_download(dl_id)
        assert record["status"] == "pending"
        assert record["error_message"] is None


    def test_history_includes_unarchived_completed(self):
        """History must show completed downloads immediately, before clearing."""
        id1 = self.db.add_download("http://a.com/x", "x.iso", "/tmp/x", 10)
        self.db.update_status(id1, "completed")
        history = self.db.get_history()
        assert [d["id"] for d in history] == [id1]
        assert history[0]["archived"] == 0  # still in the main list

    def test_completed_restored_on_startup(self):
        """Completed, non-archived downloads load with the active set."""
        id1 = self.db.add_download("http://a.com/y", "y.iso", "/tmp/y", 10)
        id2 = self.db.add_download("http://a.com/z", "z.iso", "/tmp/z", 10)
        self.db.update_status(id1, "completed")
        self.db.update_status(id2, "paused")

        active = self.db.get_active_downloads()
        assert {d["id"] for d in active} == {id1, id2}

        # After archiving, it leaves the main list but stays in history
        self.db.archive_download(id1)
        active = self.db.get_active_downloads()
        assert [d["id"] for d in active] == [id2]
        assert [d["id"] for d in self.db.get_history()] == [id1]

    def test_clear_finished(self):
        id1 = self.db.add_download("http://a.com/1", "1.zip", "/tmp/1", 100)
        id2 = self.db.add_download("http://a.com/2", "2.zip", "/tmp/2", 200)
        id3 = self.db.add_download("http://a.com/3", "3.zip", "/tmp/3", 300)
        self.db.update_status(id1, "completed")
        self.db.update_status(id2, "failed")
        self.db.update_status(id3, "downloading")
        self.db.clear_finished()

        # Completed is archived (still in history), failed is deleted,
        # downloading stays in the main list.
        main_list = self.db.get_active_downloads()
        assert [d["id"] for d in main_list] == [id3]

        history = self.db.get_history()
        assert [d["id"] for d in history] == [id1]
        assert history[0]["archived"] == 1
        assert history[0]["completed_at"]

    def test_delete_history_entry_unarchived(self):
        """A completed download still in the main list is deletable."""
        dl_id = self.db.add_download("http://a.com/u", "u.iso", "/tmp/u", 10)
        self.db.update_status(dl_id, "completed")
        assert [d["id"] for d in self.db.get_history()] == [dl_id]

        self.db.delete_history_entry(dl_id)
        assert self.db.get_history() == []
        assert self.db.get_download(dl_id) is None
        assert self.db.get_active_downloads() == []

    def test_delete_history_entry_archived(self):
        dl_id = self.db.add_download("http://a.com/a", "a.iso", "/tmp/a", 10)
        self.db.update_status(dl_id, "completed")
        self.db.archive_download(dl_id)

        self.db.delete_history_entry(dl_id)
        assert self.db.get_history() == []
        assert self.db.get_download(dl_id) is None

    def test_delete_history_entry_scoped_to_id(self):
        """Deleting one row leaves the other history rows untouched."""
        id1 = self.db.add_download("http://a.com/1", "1.iso", "/tmp/1", 10)
        id2 = self.db.add_download("http://a.com/2", "2.iso", "/tmp/2", 20)
        self.db.update_status(id1, "completed")
        self.db.update_status(id2, "completed")
        self.db.archive_download(id2)

        self.db.delete_history_entry(id1)
        assert [d["id"] for d in self.db.get_history()] == [id2]

    def test_clear_history_removes_archived_and_unarchived(self):
        """Clear History empties exactly what the history page lists."""
        id1 = self.db.add_download("http://a.com/1", "1.iso", "/tmp/1", 10)
        id2 = self.db.add_download("http://a.com/2", "2.iso", "/tmp/2", 20)
        id3 = self.db.add_download("http://a.com/3", "3.iso", "/tmp/3", 30)
        id4 = self.db.add_download("http://a.com/4", "4.iso", "/tmp/4", 40)
        self.db.update_status(id1, "completed")
        self.db.archive_download(id1)
        self.db.update_status(id2, "completed")      # completed, still in list
        self.db.update_status(id3, "downloading")
        self.db.update_status(id4, "failed", "boom")

        self.db.clear_history()

        assert self.db.get_history() == []
        assert self.db.get_download(id1) is None
        assert self.db.get_download(id2) is None
        # Unfinished and failed downloads are not history and must survive
        assert [d["id"] for d in self.db.get_active_downloads()] == [id3]
        assert self.db.get_download(id4) is not None
