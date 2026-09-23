"""
Registered language packs. To add a language, create <code>.py with a
STRINGS dict and register it here.
"""

from .. import i18n
from . import en, tr

i18n.register("en", "English", en.STRINGS)
i18n.register("tr", "Türkçe", tr.STRINGS)
