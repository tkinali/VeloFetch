"""
Utility functions for formatting and file operations.
"""

import os
import re

from ..i18n import t


def format_size(size_bytes):
    """Format byte count to human-readable string."""
    if size_bytes is None or size_bytes < 0:
        return "0 B"
    if size_bytes == 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(size_bytes)

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(size)} B"
    return f"{size:.2f} {units[unit_index]}"


def format_speed(speed_bytes):
    """Format speed in bytes/sec to human-readable string."""
    if speed_bytes is None or speed_bytes < 0:
        return "0 B/s"
    return f"{format_size(speed_bytes)}/s"


def format_time(seconds):
    """Format seconds to human-readable time string, in the active language."""
    if seconds is None or seconds < 0:
        return "--:--"

    seconds = int(seconds)
    sec, minute, hour = t("unit_second"), t("unit_minute"), t("unit_hour")

    if seconds < 60:
        return f"{seconds}{sec}"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}{minute} {secs:02d}{sec}"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}{hour} {minutes:02d}{minute}"


def format_eta(task):
    """Build the whole ETA line for a task, in the active language.

    The unknown case is its own sentence — feeding it into the "{eta} left"
    template would compose "Calculating… left".
    """
    if task.eta is None or task.total_size == 0:
        return t("eta_calculating")
    return t("eta_remaining", eta=format_time(task.eta))


def sanitize_filename(filename):
    """Remove or replace characters that are invalid in filenames."""
    # Replace problematic characters
    invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
    sanitized = re.sub(invalid_chars, "_", filename)

    # Remove trailing dots and spaces (Windows compatibility)
    sanitized = sanitized.rstrip(". ")

    # Ensure it's not empty
    if not sanitized:
        sanitized = "download"

    return sanitized


def get_free_space(path):
    """Get free disk space in bytes for the given path."""
    try:
        stat = os.statvfs(path)
        return stat.f_bavail * stat.f_frsize
    except OSError:
        return 0


def open_file_manager(path):
    """Open the file manager at the given path."""
    import subprocess
    directory = os.path.dirname(path) if os.path.isfile(path) else path
    try:
        subprocess.Popen(["xdg-open", directory])
    except FileNotFoundError:
        pass


def open_file(path):
    """Open a file with the default application."""
    import subprocess
    try:
        subprocess.Popen(["xdg-open", path])
    except FileNotFoundError:
        pass


def send_notification(title, message):
    """Send a desktop notification via notify-send, if available."""
    import subprocess
    try:
        subprocess.run(
            ["notify-send", "-a", "VeloFetch", title, message],
            timeout=5,
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
