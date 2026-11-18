#!/usr/bin/env python3
"""Translation support for the TuxBox user interface

Strings are translated with gettext, so adding a language needs no code change:
drop ``tuxbox/locale/<code>/LC_MESSAGES/tuxbox.po`` next to this module,
compile it to ``.mo`` (``msgfmt``) and it shows up in the language picker.

Catalogs are plain PO files, which every translation platform understands
(Poedit, Weblate, Crowdin, Lokalise), and the source strings are extracted
from the code with ``xgettext`` (see ``docs/TRANSLATING.md``).

English is the source language and is never translated through a catalog: it
is what the code says, so an untranslated string falls back to it.
"""

import gettext
import locale
import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Catalog location. Kept inside the package so an installed copy carries its
# translations with it.
LOCALE_DIR = Path(__file__).resolve().parent / 'locale'
DOMAIN = 'tuxbox'

SOURCE_LANGUAGE = 'en'

# Native names, so the picker reads the way each user expects regardless of the
# language the app is currently in. A catalog without an entry here still
# appears, under its bare code, so adding a language never edits this mapping.
LANGUAGE_NAMES = {
    'en': 'English',
    'fr': 'Français',
}

# Config values that mean "follow the system", rather than naming a language.
AUTOMATIC_VALUES = ('', 'auto', 'system', 'default')

# Highest priority first: the desktop sets these for the user's session.
_LOCALE_ENV_VARS = ('LC_ALL', 'LC_MESSAGES', 'LANG', 'LANGUAGE')

_active_language = SOURCE_LANGUAGE
_translation = gettext.NullTranslations()


def _has_catalog(code: str) -> bool:
    """Check whether a compiled catalog exists for `code`"""
    return (LOCALE_DIR / code / 'LC_MESSAGES' / f'{DOMAIN}.mo').is_file()


def language_code(value: Optional[str]) -> Optional[str]:
    """Reduce a config value or a locale name to a language code

    ``fr_FR.UTF-8``, ``fr-FR`` and ``fr`` all become ``fr``. Returns None for
    values that do not name a language (``auto``, ``C``, ``POSIX``, empty).
    """
    if not value:
        return None
    raw = value.strip()
    if raw.lower() in AUTOMATIC_VALUES:
        return None
    # Drop encoding and modifier, then the region: fr_FR.UTF-8@euro -> fr
    raw = raw.split('.')[0].split('@')[0].replace('-', '_')
    code = raw.split('_')[0].lower()
    if not code or code in ('c', 'posix'):
        return None
    return code


def system_language() -> Optional[str]:
    """Best guess at the language of the user's session

    The environment wins over the C library: on a desktop the variables are
    what the session actually selected, while ``locale`` can still report the
    system-wide default.
    """
    for name in _LOCALE_ENV_VARS:
        code = language_code(os.environ.get(name))
        if code:
            return code
    try:
        code = language_code(locale.getlocale(locale.LC_MESSAGES)[0])
    except (AttributeError, ValueError, TypeError):
        code = None
    return code


def available_languages() -> List[Tuple[str, str]]:
    """Return ``[(code, native name)]`` for the languages that can be shown

    English always comes first because it is the source language, then every
    language with a compiled catalog, alphabetically.
    """
    codes = [SOURCE_LANGUAGE]
    if LOCALE_DIR.is_dir():
        for entry in sorted(LOCALE_DIR.iterdir(), key=lambda p: p.name):
            if entry.is_dir() and entry.name != SOURCE_LANGUAGE and _has_catalog(entry.name):
                codes.append(entry.name)
    return [(code, LANGUAGE_NAMES.get(code, code)) for code in codes]


def setup(language: Optional[str] = None) -> str:
    """Load the catalog for `language` and return the language in use

    `language` is a config value: a language code, or None/'auto' to follow the
    system. An unknown code or a missing catalog falls back to English without
    raising, so a bad config value cannot keep the GUI from starting.
    """
    global _active_language, _translation

    requested = language_code(language) or system_language() or SOURCE_LANGUAGE
    if requested != SOURCE_LANGUAGE and not _has_catalog(requested):
        # Configured for a language whose catalog is not installed (a leftover
        # setting after an upgrade, a hand-edited config).
        logger.warning("No translation catalog for '%s'; using %s",
                       requested, SOURCE_LANGUAGE)
        requested = SOURCE_LANGUAGE

    _translation = gettext.translation(
        DOMAIN, localedir=str(LOCALE_DIR), languages=[requested], fallback=True
    )
    _active_language = requested
    logger.debug("UI language: %s", requested)
    return requested


def active_language() -> str:
    """Language currently in use, as a language code"""
    return _active_language


def N_(message: str) -> str:
    """Mark a string as translatable without translating it now

    Module-level tables (control names, key names, choice labels) must keep
    their English text: it doubles as the value stored in the profile, so it
    cannot change with the interface language. Marking those entries with N_()
    still puts them in the catalog, and the display code passes the same string
    to _() when it shows it.

    Args:
        message: English source string

    Returns:
        The string, unchanged
    """
    return message


def _(message: str) -> str:
    """Translate `message` into the active language

    The lookup is done on every call, so the translation installed by
    :func:`setup` applies to modules that imported this function long before.
    """
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Translate a message whose wording depends on a count"""
    return _translation.ngettext(singular, plural, n)
