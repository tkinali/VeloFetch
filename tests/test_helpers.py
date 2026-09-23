"""Tests for utility functions."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vf.i18n import set_language
from vf.utils.helpers import (
    format_eta,
    format_size,
    format_speed,
    format_time,
    sanitize_filename,
)


class _Task:
    """Just the two attributes format_eta() reads."""

    def __init__(self, eta, total_size):
        self.eta = eta
        self.total_size = total_size


class TestFormatSize:
    def test_bytes(self):
        assert format_size(0) == "0 B"
        assert format_size(100) == "100 B"

    def test_kilobytes(self):
        assert format_size(1024) == "1.00 KB"
        assert format_size(1536) == "1.50 KB"

    def test_megabytes(self):
        assert format_size(1048576) == "1.00 MB"
        assert format_size(5242880) == "5.00 MB"

    def test_gigabytes(self):
        assert format_size(1073741824) == "1.00 GB"

    def test_terabytes(self):
        assert format_size(1099511627776) == "1.00 TB"

    def test_negative(self):
        assert format_size(-1) == "0 B"
        assert format_size(None) == "0 B"


class TestFormatSpeed:
    def test_zero(self):
        assert format_speed(0) == "0 B/s"

    def test_kilobytes(self):
        assert format_speed(1024) == "1.00 KB/s"

    def test_megabytes(self):
        assert format_speed(1048576) == "1.00 MB/s"

    def test_negative(self):
        assert format_speed(-1) == "0 B/s"
        assert format_speed(None) == "0 B/s"


class TestFormatTime:
    """format_time() renders its units through t(), so pin the language."""

    @pytest.fixture(autouse=True)
    def english(self):
        set_language("en")
        yield
        set_language("en")

    def test_zero(self):
        assert format_time(0) == "0s"

    def test_seconds(self):
        assert format_time(30) == "30s"
        assert format_time(59) == "59s"

    def test_minutes(self):
        assert format_time(60) == "1m 00s"
        assert format_time(90) == "1m 30s"
        assert format_time(3599) == "59m 59s"

    def test_hours(self):
        assert format_time(3600) == "1h 00m"
        assert format_time(7200) == "2h 00m"

    def test_negative(self):
        assert format_time(-1) == "--:--"
        assert format_time(None) == "--:--"

    def test_units_follow_the_active_language(self):
        set_language("tr")
        assert format_time(30) == "30sn"
        assert format_time(125) == "2dk 05sn"
        assert format_time(3600) == "1sa 00dk"
        # The placeholder for "no estimate yet" stays language-neutral.
        assert format_time(None) == "--:--"


class TestFormatEta:
    """The ETA label is a whole sentence, never a fragment in a template."""

    @pytest.fixture(autouse=True)
    def restore_english(self):
        yield
        set_language("en")

    def test_estimate_available(self):
        set_language("en")
        assert format_eta(_Task(125, 1000)) == "2m 05s left"
        set_language("tr")
        assert format_eta(_Task(125, 1000)) == "2dk 05sn kaldı"

    def test_no_estimate_yet_is_its_own_sentence(self):
        # Before the first speed sample there is no eta…
        set_language("en")
        assert format_eta(_Task(None, 1000)) == "Calculating…"
        set_language("tr")
        assert format_eta(_Task(None, 1000)) == "Hesaplanıyor…"

    def test_unknown_length_is_its_own_sentence(self):
        # …and a chunked response never reports a total size.
        set_language("en")
        assert format_eta(_Task(125, 0)) == "Calculating…"
        set_language("tr")
        assert format_eta(_Task(125, 0)) == "Hesaplanıyor…"


class TestSanitizeFilename:
    def test_normal(self):
        assert sanitize_filename("test.txt") == "test.txt"

    def test_special_chars(self):
        result = sanitize_filename('test<>:"/\\|?*.txt')
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result

    def test_empty(self):
        assert sanitize_filename("") == "download"
        assert sanitize_filename("   ") == "download"

    def test_trailing_dots(self):
        assert sanitize_filename("test...") == "test"
