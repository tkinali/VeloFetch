"""
SQLite database for persistent download state management.
Stores download metadata and enables resume-after-restart.
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path


class Database:
    """Thread-safe SQLite database for download state."""

    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self):
        """Get a thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, timeout=10)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self):
        """Initialize the database schema."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                filename TEXT NOT NULL,
                save_path TEXT NOT NULL,
                total_size INTEGER DEFAULT 0,
                downloaded_size INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error_message TEXT DEFAULT NULL,
                retry_count INTEGER DEFAULT 0,
                supports_resume INTEGER DEFAULT 0,
                temp_file TEXT DEFAULT NULL,
                cookies TEXT DEFAULT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_downloads_status
            ON downloads(status);
        """)

        # Migrations for existing databases
        migrations = {
            "cookies": "ALTER TABLE downloads ADD COLUMN cookies TEXT DEFAULT NULL",
            "archived": "ALTER TABLE downloads ADD COLUMN archived INTEGER DEFAULT 0",
            "completed_at": "ALTER TABLE downloads ADD COLUMN completed_at TEXT DEFAULT NULL",
            "checksum": "ALTER TABLE downloads ADD COLUMN checksum TEXT DEFAULT NULL",
            "use_yt_dlp": "ALTER TABLE downloads ADD COLUMN use_yt_dlp INTEGER DEFAULT 0",
        }
        for column, ddl in migrations.items():
            try:
                conn.execute(f"SELECT {column} FROM downloads LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute(ddl)
        conn.commit()

    def add_download(self, url, filename, save_path, total_size=0,
                     cookies=None, checksum=None, use_yt_dlp=False):
        """Insert a new download record and return its ID."""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO downloads
               (url, filename, save_path, total_size, status, cookies,
                checksum, use_yt_dlp, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)""",
            (url, filename, save_path, total_size, cookies, checksum,
             int(use_yt_dlp), now, now),
        )
        conn.commit()
        return cursor.lastrowid

    def get_download(self, download_id):
        """Retrieve a single download by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM downloads WHERE id = ?", (download_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_downloads(self):
        """Retrieve all downloads ordered by creation date."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM downloads ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_active_downloads(self):
        """Downloads shown in the main list: in-progress/paused plus
        completed ones not yet archived to history."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM downloads
               WHERE status IN ('downloading', 'paused', 'pending')
                  OR (status = 'completed' AND archived = 0)
               ORDER BY created_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def update_progress(self, download_id, downloaded_size):
        """Update the downloaded byte count."""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            "UPDATE downloads SET downloaded_size = ?, updated_at = ? WHERE id = ?",
            (downloaded_size, now, download_id),
        )
        conn.commit()

    def update_status(self, download_id, status, error_message=None):
        """Update download status and optionally set an error message."""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            """UPDATE downloads
               SET status = ?, error_message = ?, updated_at = ?,
                   completed_at = CASE WHEN ? = 'completed' THEN ? ELSE completed_at END
               WHERE id = ?""",
            (status, error_message, now, status, now, download_id),
        )
        conn.commit()

    def update_resume_info(self, download_id, downloaded_size, total_size, supports_resume):
        """Update resume-related metadata."""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            """UPDATE downloads
               SET downloaded_size = ?, total_size = ?,
                   supports_resume = ?, updated_at = ?
               WHERE id = ?""",
            (downloaded_size, total_size, int(supports_resume), now, download_id),
        )
        conn.commit()

    def update_task_file(self, download_id, filename, save_path, total_size):
        """Update file identity/size (used by yt-dlp when the name changes)."""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            "UPDATE downloads SET filename = ?, save_path = ?, total_size = ?, "
            "updated_at = ? WHERE id = ?",
            (filename, save_path, total_size, now, download_id),
        )
        conn.commit()

    def increment_retry(self, download_id):
        """Increment the retry counter for a download."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE downloads SET retry_count = retry_count + 1 WHERE id = ?",
            (download_id,),
        )
        conn.commit()

    def get_retry_count(self, download_id):
        """Get the current retry count."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT retry_count FROM downloads WHERE id = ?", (download_id,)
        ).fetchone()
        return row["retry_count"] if row else 0

    def remove_download(self, download_id):
        """Delete a download record from the database."""
        conn = self._get_conn()
        conn.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
        conn.commit()

    def clear_finished(self):
        """Archive completed downloads; delete failed/cancelled ones."""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE downloads SET archived = 1, completed_at = COALESCE(completed_at, ?) "
            "WHERE status = 'completed'",
            (now,),
        )
        conn.execute(
            "DELETE FROM downloads WHERE status IN ('failed', 'cancelled')"
        )
        conn.commit()

    def get_history(self):
        """All completed downloads (in-list and archived), newest first."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM downloads WHERE status = 'completed' "
            "ORDER BY COALESCE(completed_at, updated_at) DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def archive_download(self, download_id):
        """Move a completed download out of the main list, keeping history."""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            "UPDATE downloads SET archived = 1, "
            "completed_at = COALESCE(completed_at, ?), updated_at = ? "
            "WHERE id = ? AND status = 'completed'",
            (now, now, download_id),
        )
        conn.commit()

    def delete_history_entry(self, download_id):
        """Permanently remove one history record.

        History lists every completed download (see get_history), archived
        or not, so deletion must not be restricted to archived rows.
        """
        conn = self._get_conn()
        conn.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
        conn.commit()

    def clear_history(self):
        """Permanently remove every record the history page lists."""
        conn = self._get_conn()
        conn.execute("DELETE FROM downloads WHERE status = 'completed'")
        conn.commit()

    def reset_for_resume(self, download_id):
        """Reset a failed download to pending for manual retry."""
        now = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            """UPDATE downloads
               SET status = 'pending', error_message = NULL, updated_at = ?
               WHERE id = ?""",
            (now, download_id),
        )
        conn.commit()
