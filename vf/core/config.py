"""
Configuration management for VeloFetch.
Handles application settings and defaults.
"""

import json
import os
import secrets
import stat
from pathlib import Path


class Config:
    """Application configuration with persistent storage."""

    DEFAULT_DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
    DEFAULT_MAX_CONCURRENT = 3
    DEFAULT_RETRY_COUNT = 5
    DEFAULT_RETRY_DELAY = 3
    DEFAULT_CHUNK_SIZE = 8192
    DEFAULT_TIMEOUT = 30
    DEFAULT_SEGMENTED = True
    DEFAULT_DOWNLOAD_SEGMENTS = 4
    DEFAULT_SEGMENTED_MIN_SIZE = 8 * 1024 * 1024  # 8 MB
    API_TOKEN_BYTES = 32
    USER_AGENT = "VeloFetch/1.0"

    # config.json holds the API token, so neither it nor the directory around
    # it may be readable by anyone but its owner.
    FILE_MODE = 0o600
    DIR_MODE = 0o700

    _instance = None
    _config_data = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # True once load() found a config file it could not parse: everything
        # that writes has to treat the file on disk as precious until then.
        self._unreadable = False

        self.config_dir = Path.home() / ".config" / "velofetch"
        self.config_file = self.config_dir / "config.json"
        self.db_file = self.config_dir / "downloads.db"

        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.defaults = {
            "download_dir": self.DEFAULT_DOWNLOAD_DIR,
            "max_concurrent": self.DEFAULT_MAX_CONCURRENT,
            "retry_count": self.DEFAULT_RETRY_COUNT,
            "retry_delay": self.DEFAULT_RETRY_DELAY,
            "chunk_size": self.DEFAULT_CHUNK_SIZE,
            "timeout": self.DEFAULT_TIMEOUT,
            "auto_rename": True,
            "overwrite_existing": False,
            "minimize_to_tray": True,
            "language": "auto",
            "speed_limit_kbps": 0,
            "api_token": "",
            "segmented": self.DEFAULT_SEGMENTED,
            "download_segments": self.DEFAULT_DOWNLOAD_SEGMENTS,
            "segmented_min_size": self.DEFAULT_SEGMENTED_MIN_SIZE,
        }

        self.load()

    def load(self):
        """Load configuration from file, falling back to defaults.

        A file that exists but cannot be parsed is left strictly alone. Most
        often it is another process' save() caught mid-write, and rewriting it
        with defaults here would silently destroy every setting the user has
        (download_dir, language, speed limit, and the live API token).
        """
        self._config_data = dict(self.defaults)
        self._unreadable = False
        self._loaded_from_file = False
        self._harden_permissions()

        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    saved = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self._unreadable = True
                print(f"Warning: Could not read {self.config_file}: {e}")
                print("Warning: Running on defaults; the file is left untouched.")
                return
            if not isinstance(saved, dict):
                self._unreadable = True
                print(f"Warning: {self.config_file} is not a JSON object; leaving it alone.")
                return
            self._config_data.update(saved)
            self._loaded_from_file = True

        # The local HTTP API is token-protected, so the token is mandatory:
        # mint one on first load and persist it immediately. After a clean
        # load() returns, "api_token" is never empty.
        self._ensure_api_token()

    def _ensure_api_token(self):
        """Mint and persist an API token when the config carries none.

        When there was no config file to read, this one is created exclusively,
        so two first runs starting at the same moment cannot persist two
        different tokens: the loser adopts the winner's file rather than
        overwriting it. Testing "does the file exist now?" instead would lose
        that race, because the winner can create it at any point in between.
        """
        if str(self._config_data.get("api_token") or "").strip():
            return
        self._config_data["api_token"] = secrets.token_urlsafe(self.API_TOKEN_BYTES)

        if self._loaded_from_file:
            # The file is ours to update: it was read a moment ago, so the
            # settings in memory are the ones it holds.
            self.save()
            return
        if self._atomic_write(exclusive=True):
            return
        self._adopt_persisted_token()

    def _adopt_persisted_token(self):
        """Take over the config another process wrote while we were minting."""
        minted = self._config_data["api_token"]
        try:
            with open(self.config_file, "r") as f:
                saved = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # It exists but we cannot read it, so it is not ours to replace.
            # Carry on without a token: the server then denies every request
            # instead of answering to one the file does not know about.
            self._unreadable = True
            self._config_data["api_token"] = ""
            print(f"Warning: Could not read {self.config_file}: {e}")
            return
        if not isinstance(saved, dict):
            self._unreadable = True
            self._config_data["api_token"] = ""
            print(f"Warning: {self.config_file} is not a JSON object; leaving it alone.")
            return
        self._config_data.update(saved)
        self._loaded_from_file = True
        if not str(self._config_data.get("api_token") or "").strip():
            self._config_data["api_token"] = minted
            self.save()

    def save(self):
        """Persist the configuration atomically, readable by its owner only.

        The data goes to a sibling temp file created with mode 0600 and is
        then renamed over config.json, so a concurrent reader always sees a
        complete file — either the previous one or the new one — instead of
        the empty window an open(..., "w") truncate leaves behind.
        """
        if self._unreadable and not self._clear_unreadable_file():
            return
        self._atomic_write()

    def _atomic_write(self, exclusive=False):
        """Write the config through a temp file moved into place. True on success.

        With exclusive=True the temp file is hard-linked instead of renamed,
        which fails when config.json already exists. That is how two first
        runs settle on a single token without either of them ever publishing a
        half-written file.
        """
        payload = json.dumps(self._config_data, indent=2)
        tmp_file = self.config_file.with_name(
            f".{self.config_file.name}.{os.getpid()}-{secrets.token_hex(4)}.tmp"
        )
        written = False
        try:
            fd = os.open(
                tmp_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, self.FILE_MODE
            )
            with os.fdopen(fd, "w") as f:
                f.write(payload)
            if not exclusive:
                os.replace(tmp_file, self.config_file)
                written = True
            else:
                try:
                    os.link(tmp_file, self.config_file)
                    written = True
                except FileExistsError:
                    pass  # another first run got there; the caller adopts it
                except OSError:
                    # No hard links on this filesystem: still atomic, just no
                    # longer exclusive.
                    os.replace(tmp_file, self.config_file)
                    written = True
        except OSError as e:
            print(f"Warning: Could not save config: {e}")
        finally:
            try:
                os.unlink(tmp_file)
            except OSError:
                pass  # already renamed into place, or never created
        return written

    def _clear_unreadable_file(self):
        """Move an unparsable config aside so an explicit save may proceed.

        Returns True when writing config.json is safe again. Only explicit
        saves reach this: load() never rewrites a file it could not read.
        """
        if not self.config_file.exists():
            self._unreadable = False
            return True
        backup = self.config_file.with_name(self.config_file.name + ".corrupt")
        try:
            os.replace(self.config_file, backup)
        except OSError as e:
            print(f"Warning: Could not save config: {e}")
            return False
        # The backup may still hold a token, so it inherits the same 0600.
        try:
            os.chmod(backup, self.FILE_MODE)
        except OSError:
            pass
        print(f"Warning: Unreadable config kept as {backup}")
        self._unreadable = False
        return True

    def _harden_permissions(self):
        """Narrow the config dir and file to their owner.

        save() creates the file 0600, but an install that predates that (or a
        stray chmod) would otherwise keep its world-readable token forever —
        exactly the machines the hardening is for. Bits are only ever removed,
        never added.
        """
        for path, allowed in (
            (self.config_dir, self.DIR_MODE),
            (self.config_file, self.FILE_MODE),
        ):
            try:
                current = stat.S_IMODE(os.stat(path).st_mode)
            except OSError:
                continue
            if current & ~allowed:
                try:
                    os.chmod(path, current & allowed)
                except OSError:
                    pass

    def regenerate_api_token(self):
        """Mint a fresh API token, persist it and return the new value."""
        token = secrets.token_urlsafe(self.API_TOKEN_BYTES)
        self._config_data["api_token"] = token
        self.save()
        return token

    def get(self, key, default=None):
        """Get a configuration value."""
        return self._config_data.get(key, default)

    def set(self, key, value):
        """Set a configuration value and save."""
        self._config_data[key] = value
        self.save()

    @property
    def download_dir(self):
        return self._config_data["download_dir"]

    @property
    def max_concurrent(self):
        return int(self._config_data["max_concurrent"])

    @property
    def retry_count(self):
        return int(self._config_data["retry_count"])

    @property
    def retry_delay(self):
        return int(self._config_data["retry_delay"])

    @property
    def chunk_size(self):
        return int(self._config_data["chunk_size"])

    @property
    def timeout(self):
        return int(self._config_data["timeout"])

    @property
    def segmented(self):
        return bool(self._config_data["segmented"])

    @property
    def download_segments(self):
        return max(1, int(self._config_data["download_segments"]))

    @property
    def segmented_min_size(self):
        return int(self._config_data["segmented_min_size"])

    @property
    def auto_rename(self):
        """Rename a colliding download instead of refusing it."""
        return bool(self._config_data.get("auto_rename", True))

    @property
    def overwrite_existing(self):
        """Replace an existing file on completion instead of writing a new name."""
        return bool(self._config_data.get("overwrite_existing", False))

    @property
    def api_token(self):
        """Token guarding the local HTTP API; never empty after load()."""
        return str(self._config_data.get("api_token") or "")

    @property
    def speed_limit_bytes(self):
        """Global speed limit in bytes/sec; 0 means unlimited."""
        return int(self._config_data.get("speed_limit_kbps", 0)) * 1024
