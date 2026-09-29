#!/usr/bin/env python3
"""Writer for the [device] section of config.conf

Global device settings live in config.conf alongside hand-written comments,
and may include keys this version of TuxBox knows nothing about. So the
section is edited line by line rather than regenerated: a rewrite from a
fixed set of keys (the way profile_io._write_device_config builds a fresh
file during migration) would drop the user's comments and any key it does
not recognise.
"""

import os
import re
import logging
import shutil
from typing import Dict, Optional, Tuple
from datetime import datetime

from tuxbox.config_loader import get_config_path

logger = logging.getLogger(__name__)

DEVICE_SECTION = 'device'

# Settings this dialog owns, in the order they are written into a section that
# does not have them yet. Anything else in [device] is left untouched.
DEVICE_KEYS = (
    'controller_model',
    'connection',
    'usb_port',
    'force_haptics',
    'modifier_delay',
    'window_poll_interval',
)


def _is_section_header(line: str, name: str = None) -> bool:
    """Check whether a line is a section header, optionally a specific one"""
    stripped = line.strip()
    if not (stripped.startswith('[') and stripped.endswith(']')):
        return False
    if name is None:
        return True
    return stripped[1:-1].strip().lower() == name.lower()


def _find_section(lines, name: str) -> Tuple[int, int]:
    """Locate a section's body within the file

    Returns:
        (start, end) where start is the index of the header line and end is
        the index one past the section's last line. (-1, -1) if not found.
    """
    start = -1
    for i, line in enumerate(lines):
        if start < 0:
            if _is_section_header(line, name):
                start = i
        elif _is_section_header(line):
            return start, i
    if start < 0:
        return -1, -1
    return start, len(lines)


def _key_line_match(line: str, key: str) -> Optional[bool]:
    """Classify a line with respect to `key`

    Returns True for an active `key = value` line, False for a commented-out
    placeholder such as "# usb_port = /dev/ttyACM0", and None if the line is
    about something else.
    """
    stripped = line.strip()
    if not stripped:
        return None
    active = re.match(rf'^{re.escape(key)}\s*=', stripped)
    if active:
        return True
    commented = re.match(rf'^#\s*{re.escape(key)}\s*=', stripped)
    if commented:
        return False
    return None


def _key_line_match_any(line: str) -> bool:
    """Check whether a line sets any key at all (not a comment or blank)"""
    stripped = line.strip()
    if not stripped or stripped.startswith('#') or _is_section_header(stripped):
        return False
    return '=' in stripped


def _inline_comment(line: str) -> str:
    """Return the trailing inline comment of a value line, including its '#'"""
    # Only the part after the '=' can hold an inline comment for our purposes.
    _, _, value = line.partition('=')
    idx = value.find('#')
    if idx < 0:
        return ''
    return '  ' + value[idx:].rstrip('\n').strip()


def _format_value(value) -> str:
    """Render a Python value the way the config file expects it"""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def _apply_settings(lines, start: int, end: int, settings: Dict) -> int:
    """Apply settings within [start, end), returning the new section end

    A value of None removes the setting, so the driver falls back to its
    documented default rather than being pinned to it.
    """
    for key in DEVICE_KEYS:
        if key not in settings:
            continue

        value = settings[key]
        active_idx = None
        placeholder_idx = None

        for i in range(start + 1, end):
            match = _key_line_match(lines[i], key)
            if match is True and active_idx is None:
                active_idx = i
            elif match is False and placeholder_idx is None:
                placeholder_idx = i

        if value is None:
            # Remove the setting. A commented placeholder is left alone: it is
            # documentation, and removing it loses the hint about the default.
            if active_idx is not None:
                del lines[active_idx]
                end -= 1
            continue

        new_line = f"{key} = {_format_value(value)}"

        if active_idx is not None:
            # Keep any inline comment the user wrote next to the value.
            lines[active_idx] = new_line + _inline_comment(lines[active_idx]) + "\n"
        elif placeholder_idx is not None:
            # Uncomment the template line in place instead of appending a
            # duplicate below it.
            lines[placeholder_idx] = new_line + "\n"
        else:
            # Add after the last setting that is actually in force, falling
            # back to the top of the section. Appending at the very end would
            # park the new line under whatever trailing comment block the
            # section ends with, reading as if it belonged to it.
            insert_at = start + 1
            for i in range(start + 1, end):
                if _key_line_match_any(lines[i]):
                    insert_at = i + 1
            lines.insert(insert_at, new_line + "\n")
            end += 1

    return end


def save_device_settings(settings: Dict, config_path: Optional[str] = None) -> Tuple[bool, str]:
    """Save global [device] settings, preserving comments and unknown keys

    Args:
        settings: Setting name -> value. None removes the setting.
        config_path: Config file to edit (default location if None)

    Returns:
        (success, message)
    """
    if config_path is None:
        config_path = get_config_path()

    if not config_path or not os.path.exists(config_path):
        logger.error("No config file found to save device settings to")
        return False, "No configuration file was found."

    unknown = set(settings) - set(DEVICE_KEYS)
    if unknown:
        # A caller bug: silently writing keys the loader ignores would look
        # like the setting had been saved.
        return False, f"Unsupported device settings: {', '.join(sorted(unknown))}"

    backup_path = f"{config_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    try:
        shutil.copy2(config_path, backup_path)
        logger.info(f"Created backup: {backup_path}")

        with open(config_path, 'r') as f:
            lines = f.readlines()

        start, end = _find_section(lines, DEVICE_SECTION)

        if start < 0:
            # No [device] section yet - add one above the first section so it
            # stays at the top of the file, where the template puts it.
            insert_at = next(
                (i for i, line in enumerate(lines) if _is_section_header(line)),
                len(lines)
            )
            if insert_at > 0 and lines[insert_at - 1].strip():
                lines.insert(insert_at, "\n")
                insert_at += 1
            lines.insert(insert_at, f"[{DEVICE_SECTION}]\n")
            start = insert_at
            end = insert_at + 1
            if end < len(lines) and lines[end].strip():
                lines.insert(end, "\n")

        _apply_settings(lines, start, end, settings)

        # Atomic replace, so an interrupted write cannot truncate the config.
        temp_path = f"{config_path}.tmp"
        with open(temp_path, 'w') as f:
            f.writelines(lines)
        os.replace(temp_path, config_path)

        logger.info(f"Saved device settings: {sorted(settings)}")
        return True, "Settings saved."

    except Exception as ex:
        logger.error(f"Error saving device settings: {ex}", exc_info=True)
        if os.path.exists(backup_path):
            try:
                shutil.copy2(backup_path, config_path)
                logger.info("Restored config from backup after error")
            except Exception as restore_error:
                logger.error(f"Failed to restore backup: {restore_error}")
        return False, f"Could not save settings: {ex}"
