#!/usr/bin/env python3
"""Profile file I/O operations

Handles reading/writing individual .profile files and migration from legacy format.
"""

import os
import re
import configparser
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set
from datetime import datetime

from .haptic import HapticConfig, HapticStrength, HapticSpeed

logger = logging.getLogger(__name__)


def _migrate_config_dir_if_needed():
    """Migrate config directory from ~/.config/tourbox/ to ~/.config/tuxbox/

    Called automatically on first access to config paths. Handles:
    - Copying the entire config tree from tourbox/ to tuxbox/
    - Renaming tourbox_gui.profile to tuxbox_gui.profile
    - Updating window_class/app_id inside the GUI profile
    - Renaming the old directory to tourbox.pre-v3-backup

    If ~/.config/tuxbox/ already exists, does nothing (already migrated or fresh).
    """
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        home = os.path.expanduser(f'~{sudo_user}')
    else:
        home = os.path.expanduser('~')

    new_dir = Path(home) / '.config' / 'tuxbox'
    old_dir = Path(home) / '.config' / 'tourbox'

    # Already migrated or fresh install
    if new_dir.exists():
        return

    # Nothing to migrate
    if not old_dir.exists():
        return

    # Copy entire tree
    try:
        shutil.copytree(str(old_dir), str(new_dir))
        logger.info(f"Migrated config directory: {old_dir} -> {new_dir}")
    except Exception as ex:
        logger.error(f"Failed to migrate config directory: {ex}")
        return

    # Migrate the GUI profile if it exists
    profiles_dir = new_dir / 'profiles'
    old_gui_profile = profiles_dir / 'tourbox_gui.profile'
    new_gui_profile = profiles_dir / 'tuxbox_gui.profile'

    if old_gui_profile.exists():
        try:
            if new_gui_profile.exists():
                # New profile already exists, just remove the old one
                old_gui_profile.unlink()
                logger.info(f"Removed stale GUI profile: {old_gui_profile.name}")
            else:
                # Read and update content
                content = old_gui_profile.read_text()
                content = content.replace('name = TourBox GUI', 'name = TuxBox GUI')
                content = content.replace('window_class = tourbox-gui', 'window_class = tuxbox-gui')
                content = content.replace('app_id = tourbox-gui', 'app_id = tuxbox-gui')

                # Write to new filename and remove old
                new_gui_profile.write_text(content)
                old_gui_profile.unlink()
                logger.info(f"Migrated GUI profile: {old_gui_profile.name} -> {new_gui_profile.name}")
        except Exception as ex:
            logger.error(f"Failed to migrate GUI profile: {ex}")

    # Rename old directory so users don't confuse it with the active config
    backup_dir = Path(home) / '.config' / 'tourbox.pre-v3-backup'
    try:
        old_dir.rename(backup_dir)
        logger.info(f"Renamed old config dir: {old_dir} -> {backup_dir}")
    except Exception as ex:
        logger.warning(f"Could not rename old config dir: {ex}")


def get_profiles_dir(config_dir: str = None) -> Path:
    """Get the profiles directory path

    Args:
        config_dir: Base config directory. If None, uses default location.

    Returns:
        Path to the profiles directory
    """
    if config_dir:
        return Path(config_dir) / 'profiles'

    # Check for sudo user
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        home = os.path.expanduser(f'~{sudo_user}')
    else:
        home = os.path.expanduser('~')

    return Path(home) / '.config' / 'tuxbox' / 'profiles'


def get_config_dir() -> Path:
    """Get the main config directory path

    Automatically migrates from ~/.config/tourbox/ on first access.

    Returns:
        Path to the config directory (~/.config/tuxbox/)
    """
    _migrate_config_dir_if_needed()

    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        home = os.path.expanduser(f'~{sudo_user}')
    else:
        home = os.path.expanduser('~')

    return Path(home) / '.config' / 'tuxbox'


def sanitize_profile_filename(name: str) -> str:
    """Convert a profile name to a safe filename

    Args:
        name: Profile name (e.g., "My Custom Profile")

    Returns:
        Safe filename without extension (e.g., "my_custom_profile")
    """
    # Convert to lowercase
    filename = name.lower()

    # Replace spaces and hyphens with underscores
    filename = re.sub(r'[\s\-]+', '_', filename)

    # Remove any characters that aren't alphanumeric or underscore
    filename = re.sub(r'[^a-z0-9_]', '', filename)

    # Collapse multiple underscores
    filename = re.sub(r'_+', '_', filename)

    # Remove leading/trailing underscores
    filename = filename.strip('_')

    # Truncate to 50 characters
    filename = filename[:50]

    # Ensure we have something
    if not filename:
        filename = 'profile'

    return filename


def profile_name_from_filename(filename: str) -> str:
    """Extract profile name from a .profile filename

    This reads the actual name from inside the file, not from the filename.
    The filename is just for identification purposes.

    Args:
        filename: Filename (with or without .profile extension)

    Returns:
        Profile name based on filename (for fallback only)
    """
    # Remove .profile extension if present
    if filename.endswith('.profile'):
        filename = filename[:-8]

    # Convert underscores to spaces and title case
    name = filename.replace('_', ' ').title()

    return name


def is_legacy_config() -> bool:
    """Check if config file uses legacy all-in-one format

    Returns:
        True if legacy format detected (has [profile:*] sections in mappings.conf)
    """
    config_dir = get_config_dir()
    legacy_path = config_dir / 'mappings.conf'

    if not legacy_path.exists():
        return False

    try:
        config = configparser.ConfigParser(inline_comment_prefixes=('#',), interpolation=None)
        config.read(str(legacy_path))

        # Legacy format has [profile:*] sections
        for section in config.sections():
            if section.startswith('profile:'):
                return True
    except Exception as e:
        logger.error(f"Error checking legacy config: {e}")

    return False


def has_profiles_dir() -> bool:
    """Check if the profiles directory exists and has profile files

    Returns:
        True if profiles directory exists with at least one .profile file
    """
    profiles_dir = get_profiles_dir()

    if not profiles_dir.exists():
        return False

    # Check for at least one .profile file
    for f in profiles_dir.iterdir():
        if f.suffix == '.profile':
            return True

    return False


def discover_profiles() -> List[Path]:
    """Find all .profile files in the profiles directory

    Returns:
        List of paths to .profile files, sorted alphabetically
    """
    profiles_dir = get_profiles_dir()

    if not profiles_dir.exists():
        return []

    profiles = []
    for f in profiles_dir.iterdir():
        if f.is_file() and f.suffix == '.profile':
            profiles.append(f)

    # Sort alphabetically, but put 'default' first
    def sort_key(p):
        if p.stem == 'default':
            return ('', p.stem)
        return ('z', p.stem)

    return sorted(profiles, key=sort_key)


def validate_profile_file(filepath: Path) -> Tuple[bool, str]:
    """Validate a .profile file

    Args:
        filepath: Path to the .profile file

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not filepath.exists():
        return False, f"File not found: {filepath}"

    if not filepath.suffix == '.profile':
        return False, "File must have .profile extension"

    try:
        config = configparser.ConfigParser(inline_comment_prefixes=('#',), interpolation=None)
        config.read(str(filepath))

        # Must have [profile] section
        if 'profile' not in config.sections():
            return False, "Missing [profile] section"

        # Must have a name
        if 'name' not in config['profile']:
            return False, "Missing 'name' in [profile] section"

        name = config['profile']['name'].strip()
        if not name:
            return False, "Profile name cannot be empty"

        # Check for invalid characters in name
        if ':' in name or '[' in name or ']' in name:
            return False, "Profile name cannot contain ':', '[', or ']' characters"

        # Validate mappings if present
        if 'mappings' in config.sections():
            from .config_loader import BUTTON_CODES
            for key in config['mappings'].keys():
                # Skip known special keys
                if key == 'modifier':
                    continue
                # Skip .double keys (double-press actions)
                if key.endswith('.double'):
                    continue
                # Skip .on_release keys (on-release toggle)
                if key.endswith('.on_release'):
                    continue
                # Skip .on_release_disabled keys (user explicitly disabled on-release)
                if key.endswith('.on_release_disabled'):
                    continue
                # Skip .base_action keys (modifier base actions)
                if key.endswith('.base_action'):
                    continue
                # Skip modifier combo keys (modifier.control)
                if '.' in key:
                    continue
                if key not in BUTTON_CODES:
                    # Allow unknown keys, just warn
                    logger.warning(f"Unknown button in profile: {key}")

        return True, ""

    except configparser.Error as e:
        return False, f"Invalid INI format: {e}"
    except Exception as e:
        return False, f"Error reading file: {e}"


def load_profile_from_file(filepath: Path):
    """Load a single profile from a .profile file

    Args:
        filepath: Path to the .profile file

    Returns:
        Profile object or None if failed
    """
    from .config_loader import (
        Profile, BUTTON_CODES, parse_action, create_button_mapping,
        get_capabilities_from_mapping, VALID_MODIFIER_BUTTONS,
        INVALID_MODIFIER_CONTROLS
    )
    from evdev import ecodes as e

    is_valid, error = validate_profile_file(filepath)
    if not is_valid:
        logger.error(f"Invalid profile file {filepath}: {error}")
        return None

    try:
        config = configparser.ConfigParser(inline_comment_prefixes=('#',), interpolation=None)
        config.read(str(filepath))

        # Get profile metadata
        profile_section = config['profile']
        name = profile_section.get('name', '').strip()
        app_id = profile_section.get('app_id')
        window_class = profile_section.get('window_class')
        window_title = profile_section.get('window_title')  # deprecated but supported

        # Parse enabled state (defaults to True if not specified)
        enabled = profile_section.get('enabled', 'true').lower() in ('true', 'yes', '1', 'on')

        # Parse double-click timeout (defaults to 300ms if not specified)
        double_click_timeout = 300
        if 'double_click_timeout' in profile_section:
            try:
                double_click_timeout = int(profile_section['double_click_timeout'])
            except ValueError:
                logger.warning(f"Invalid double_click_timeout value, using default 300ms")

        # Parse per-profile modifier_delay (None = use global fallback)
        modifier_delay = None
        if 'modifier_delay' in profile_section:
            try:
                modifier_delay = int(profile_section['modifier_delay'])
            except ValueError:
                logger.warning(f"Invalid modifier_delay value in profile, ignoring")

        # Parse global haptic settings from [profile] section
        haptic_config = HapticConfig()
        if 'haptic' in profile_section:
            haptic_config.global_setting = HapticStrength.from_string(profile_section['haptic'])
        if 'haptic_speed' in profile_section:
            haptic_config.global_speed = HapticSpeed.from_string(profile_section['haptic_speed'])

        # Parse mappings from [mappings] section
        mapping = {}
        double_press_actions = {}
        on_release_controls = set()
        on_release_user_disabled = set()
        if 'mappings' in config.sections():
            for key, action in config['mappings'].items():
                # Skip modifier declarations (handled separately)
                if action.strip() == 'modifier':
                    continue

                # Check for double-press action: control.double = ACTION
                if key.endswith('.double'):
                    control_name = key[:-7]  # Remove '.double' suffix
                    double_press_actions[control_name] = action.strip()
                    continue

                # Check for on-release toggle: control.on_release = true
                if key.endswith('.on_release'):
                    control_name = key[:-11]  # Remove '.on_release' suffix
                    if action.strip().lower() in ('true', '1', 'yes'):
                        on_release_controls.add(control_name)
                    continue

                # Check for on-release user disabled: control.on_release_disabled = true
                if key.endswith('.on_release_disabled'):
                    control_name = key[:-20]  # Remove '.on_release_disabled' suffix
                    if action.strip().lower() in ('true', '1', 'yes'):
                        on_release_user_disabled.add(control_name)
                    continue

                if key in BUTTON_CODES:
                    codes = BUTTON_CODES[key]
                    is_rotary = key in ('scroll_up', 'scroll_down', 'knob_cw', 'knob_ccw', 'dial_cw', 'dial_ccw')

                    if len(codes) == 2:
                        press_code, release_code = codes
                        press_events, release_events = create_button_mapping(action)

                        if is_rotary:
                            mapping[bytes([press_code])] = press_events + release_events
                            mapping[bytes([release_code])] = release_events
                        else:
                            mapping[bytes([press_code])] = press_events
                            mapping[bytes([release_code])] = release_events

        caps = get_capabilities_from_mapping(mapping)

        # Parse modifiers from [modifiers] section
        modifier_buttons = set()
        modifier_mappings = {}
        modifier_base_actions = {}

        if 'modifiers' in config.sections():
            # First pass: find modifier declarations
            for key, value in config['modifiers'].items():
                if value.strip() == 'modifier':
                    control_name = key.strip()
                    if control_name in INVALID_MODIFIER_CONTROLS:
                        logger.error(f"Invalid modifier: {control_name} cannot be a modifier")
                        continue
                    modifier_buttons.add(control_name)

            # Second pass: parse base actions and combos
            for key, value in config['modifiers'].items():
                if '.base_action' in key:
                    parts = key.split('.')
                    if len(parts) == 2:
                        modifier_name = parts[0].strip()
                        if modifier_name in modifier_buttons:
                            modifier_base_actions[modifier_name] = value.strip()

                elif '.' in key and value.strip() != 'modifier':
                    parts = key.split('.')
                    if len(parts) == 2:
                        modifier_name, control_name = parts[0].strip(), parts[1].strip()
                        if modifier_name in modifier_buttons and control_name != 'base_action':
                            modifier_mappings[(modifier_name, control_name)] = value.strip()

        # Add modifier actions to capabilities
        for action_str in list(modifier_mappings.values()) + list(modifier_base_actions.values()):
            events = parse_action(action_str)
            for event_type, event_code, value in events:
                if event_type == e.EV_KEY:
                    if e.EV_KEY not in caps:
                        caps[e.EV_KEY] = []
                    if event_code not in caps[e.EV_KEY]:
                        caps[e.EV_KEY].append(event_code)
                elif event_type == e.EV_REL:
                    if e.EV_REL not in caps:
                        caps[e.EV_REL] = []
                    if event_code not in caps[e.EV_REL]:
                        caps[e.EV_REL].append(event_code)

        # Add double-press actions to capabilities
        for action_str in double_press_actions.values():
            events = parse_action(action_str)
            for event_type, event_code, value in events:
                if event_type == e.EV_KEY:
                    if e.EV_KEY not in caps:
                        caps[e.EV_KEY] = []
                    if event_code not in caps[e.EV_KEY]:
                        caps[e.EV_KEY].append(event_code)
                elif event_type == e.EV_REL:
                    if e.EV_REL not in caps:
                        caps[e.EV_REL] = []
                    if event_code not in caps[e.EV_REL]:
                        caps[e.EV_REL].append(event_code)

        # Parse haptic settings from [haptic] section
        if 'haptic' in config.sections():
            for key, value in config['haptic'].items():
                if key.startswith('haptic.'):
                    parts = key.split('.')
                    if len(parts) == 2:
                        dial = parts[1]
                        haptic_config.dial_settings[dial] = HapticStrength.from_string(value)
                    elif len(parts) == 3:
                        dial, modifier = parts[1], parts[2]
                        haptic_config.combo_settings[(dial, modifier)] = HapticStrength.from_string(value)

                elif key.startswith('haptic_speed.'):
                    parts = key.split('.')
                    if len(parts) == 2:
                        dial = parts[1]
                        haptic_config.dial_speed_settings[dial] = HapticSpeed.from_string(value)
                    elif len(parts) == 3:
                        dial, modifier = parts[1], parts[2]
                        haptic_config.combo_speed_settings[(dial, modifier)] = HapticSpeed.from_string(value)

        # Parse comments from [comments] section
        mapping_comments = {}
        modifier_combo_comments = {}
        double_press_comments = {}

        if 'comments' in config.sections():
            for key, value in config['comments'].items():
                comment_text = value.strip().replace('\\n', '\n')

                if '.' in key:
                    parts = key.split('.')
                    if len(parts) == 2:
                        if parts[1] == 'base_action':
                            # Base action comment
                            mapping_comments[key] = comment_text
                        elif parts[1] == 'double':
                            # Double-press action comment
                            control_name = parts[0].strip()
                            double_press_comments[control_name] = comment_text
                        else:
                            # Combo comment
                            modifier_name, control_name = parts[0].strip(), parts[1].strip()
                            modifier_combo_comments[(modifier_name, control_name)] = comment_text
                else:
                    mapping_comments[key] = comment_text

        profile = Profile(
            name=name,
            window_class=window_class,
            window_title=window_title,
            app_id=app_id,
            mapping=mapping,
            capabilities=caps,
            modifier_buttons=modifier_buttons,
            modifier_mappings=modifier_mappings,
            modifier_base_actions=modifier_base_actions,
            mapping_comments=mapping_comments,
            modifier_combo_comments=modifier_combo_comments,
            haptic_config=haptic_config,
            enabled=enabled,
            double_click_timeout=double_click_timeout,
            double_press_actions=double_press_actions,
            double_press_comments=double_press_comments,
            on_release_controls=on_release_controls,
            on_release_user_disabled=on_release_user_disabled,
            modifier_delay=modifier_delay
        )

        logger.info(f"Loaded profile from file: {profile}")
        return profile

    except Exception as ex:
        logger.error(f"Error loading profile from {filepath}: {ex}")
        return None


def save_profile_to_file(profile, filepath: Path) -> bool:
    """Save a profile to a .profile file

    Args:
        profile: Profile object to save
        filepath: Path to save to

    Returns:
        True if successful
    """
    from .config_loader import BUTTON_CODES

    try:
        # Ensure parent directory exists
        filepath.parent.mkdir(parents=True, exist_ok=True)

        lines = []

        # Header comment
        lines.append(f"# TuxBox Profile")
        lines.append(f"# Profile: {profile.name}")
        lines.append(f"# Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # [profile] section
        lines.append("[profile]")
        lines.append(f"name = {profile.name}")
        if profile.app_id:
            lines.append(f"app_id = {profile.app_id}")
        if profile.window_class:
            lines.append(f"window_class = {profile.window_class}")

        # Only write enabled if False (True is the default)
        if not profile.enabled:
            lines.append("enabled = false")

        # Only write double_click_timeout if non-default (300ms is the default)
        if profile.double_click_timeout != 300:
            lines.append(f"double_click_timeout = {profile.double_click_timeout}")

        # Only write modifier_delay if explicitly set (None = use global)
        if profile.modifier_delay is not None:
            lines.append(f"modifier_delay = {profile.modifier_delay}")

        # Global haptic settings in profile section
        if profile.haptic_config.global_setting is not None:
            lines.append(f"haptic = {profile.haptic_config.global_setting}")
        if profile.haptic_config.global_speed is not None:
            lines.append(f"haptic_speed = {profile.haptic_config.global_speed}")

        lines.append("")

        # [mappings] section
        lines.append("[mappings]")

        # Get action strings from mapping
        action_strings = _get_action_strings_from_mapping(profile)

        # Also include modifier declarations
        for modifier in sorted(profile.modifier_buttons):
            action_strings[modifier] = 'modifier'

        for control in sorted(action_strings.keys()):
            lines.append(f"{control} = {action_strings[control]}")

        # Write double-press actions
        for control in sorted(profile.double_press_actions.keys()):
            lines.append(f"{control}.double = {profile.double_press_actions[control]}")

        # Write on-release controls
        for control in sorted(profile.on_release_controls):
            lines.append(f"{control}.on_release = true")

        # Write user-disabled on-release controls (to prevent auto-enable)
        for control in sorted(profile.on_release_user_disabled):
            lines.append(f"{control}.on_release_disabled = true")

        lines.append("")

        # [modifiers] section (if any modifiers)
        if profile.modifier_buttons:
            lines.append("[modifiers]")

            for modifier in sorted(profile.modifier_buttons):
                lines.append(f"{modifier} = modifier")

                # Base action
                if modifier in profile.modifier_base_actions:
                    lines.append(f"{modifier}.base_action = {profile.modifier_base_actions[modifier]}")

                # Combos for this modifier
                for (mod, control), action in sorted(profile.modifier_mappings.items()):
                    if mod == modifier:
                        lines.append(f"{mod}.{control} = {action}")

            lines.append("")

        # [haptic] section (per-dial and per-combo settings)
        has_haptic_settings = (
            profile.haptic_config.dial_settings or
            profile.haptic_config.dial_speed_settings or
            profile.haptic_config.combo_settings or
            profile.haptic_config.combo_speed_settings
        )

        if has_haptic_settings:
            lines.append("[haptic]")

            # Per-dial strength
            for dial, strength in sorted(profile.haptic_config.dial_settings.items()):
                lines.append(f"haptic.{dial} = {strength}")

            # Per-dial speed
            for dial, speed in sorted(profile.haptic_config.dial_speed_settings.items()):
                lines.append(f"haptic_speed.{dial} = {speed}")

            # Per-combo strength
            for (dial, modifier), strength in sorted(profile.haptic_config.combo_settings.items()):
                lines.append(f"haptic.{dial}.{modifier} = {strength}")

            # Per-combo speed
            for (dial, modifier), speed in sorted(profile.haptic_config.combo_speed_settings.items()):
                lines.append(f"haptic_speed.{dial}.{modifier} = {speed}")

            lines.append("")

        # [comments] section
        has_comments = profile.mapping_comments or profile.modifier_combo_comments or profile.double_press_comments

        if has_comments:
            lines.append("[comments]")

            # Regular comments
            for control, comment in sorted(profile.mapping_comments.items()):
                escaped_comment = comment.replace('\n', '\\n')
                lines.append(f"{control} = {escaped_comment}")

            # Double-press comments
            for control, comment in sorted(profile.double_press_comments.items()):
                escaped_comment = comment.replace('\n', '\\n')
                lines.append(f"{control}.double = {escaped_comment}")

            # Combo comments
            for (modifier, control), comment in sorted(profile.modifier_combo_comments.items()):
                escaped_comment = comment.replace('\n', '\\n')
                lines.append(f"{modifier}.{control} = {escaped_comment}")

            lines.append("")

        # Write atomically
        temp_path = filepath.with_suffix('.tmp')
        with open(temp_path, 'w') as f:
            f.write('\n'.join(lines))

        os.replace(str(temp_path), str(filepath))

        logger.info(f"Saved profile to {filepath}")
        return True

    except Exception as ex:
        logger.error(f"Error saving profile to {filepath}: {ex}")
        return False


def _get_action_strings_from_mapping(profile) -> Dict[str, str]:
    """Convert profile mapping back to action strings

    This is a helper to reverse the mapping from hex codes back to
    human-readable action strings for saving.

    Args:
        profile: Profile object

    Returns:
        Dict mapping control name to action string
    """
    from .config_loader import BUTTON_CODES
    from evdev import ecodes as e

    # Reverse lookup: press_code -> control_name
    code_to_control = {}
    for control, codes in BUTTON_CODES.items():
        if len(codes) == 2:
            press_code = codes[0]
            code_to_control[press_code] = control

    # Key code to name lookup (includes KEY_ and BTN_ codes)
    key_code_to_name = {}
    for name, code in vars(e).items():
        if (name.startswith('KEY_') or name.startswith('BTN_')) and isinstance(code, int):
            key_code_to_name[code] = name

    # Relative code to name lookup
    rel_code_to_name = {}
    for name, code in vars(e).items():
        if name.startswith('REL_') and isinstance(code, int):
            rel_code_to_name[code] = name

    action_strings = {}

    if not profile.mapping:
        return action_strings

    for byte_code, events in profile.mapping.items():
        if len(byte_code) != 1:
            continue

        code = byte_code[0]

        # Only process press codes (not release codes)
        if code not in code_to_control:
            continue

        control = code_to_control[code]

        # Check if this is a rotary (events include press+release)
        is_rotary = control in ('scroll_up', 'scroll_down', 'knob_cw', 'knob_ccw', 'dial_cw', 'dial_ccw')

        if not events:
            action_strings[control] = 'none'
            continue

        # Convert events back to action string
        key_parts = []
        for event_type, event_code, value in events:
            if event_type == e.EV_KEY and value == 1:  # Press only
                if event_code in key_code_to_name:
                    key_parts.append(key_code_to_name[event_code])
            elif event_type == e.EV_REL:
                if event_code in rel_code_to_name:
                    key_parts.append(f"{rel_code_to_name[event_code]}:{value}")

        if key_parts:
            action_strings[control] = '+'.join(key_parts)

    return action_strings


def get_profile_filepath(profile_name: str) -> Path:
    """Get the file path for a profile

    Args:
        profile_name: Name of the profile

    Returns:
        Path to the .profile file
    """
    profiles_dir = get_profiles_dir()
    filename = sanitize_profile_filename(profile_name)
    return profiles_dir / f"{filename}.profile"


def export_profile_to_file(profile, destination: Path) -> bool:
    """Export a profile to an arbitrary location

    Args:
        profile: Profile object to export
        destination: Destination path

    Returns:
        True if successful
    """
    return save_profile_to_file(profile, destination)


def import_profile_from_file(source: Path) -> Tuple[Optional['Profile'], str]:
    """Import a profile from a file

    Args:
        source: Source file path

    Returns:
        Tuple of (Profile or None, error_message)
    """
    is_valid, error = validate_profile_file(source)
    if not is_valid:
        return None, error

    profile = load_profile_from_file(source)
    if profile is None:
        return None, "Failed to load profile"

    return profile, ""


def migrate_legacy_config() -> Tuple[bool, str]:
    """Migrate from single-file to multi-file profile format

    This function:
    1. Creates a backup of the original config
    2. Creates the profiles directory
    3. Extracts each profile to its own .profile file
    4. Creates new config.conf with device settings only
    5. Renames old config to .legacy

    Returns:
        Tuple of (success, message)
    """
    from .config_loader import load_profiles_from_legacy_file, load_device_config

    config_dir = get_config_dir()
    legacy_path = config_dir / 'mappings.conf'
    profiles_dir = get_profiles_dir()
    new_config_path = config_dir / 'config.conf'

    if not legacy_path.exists():
        return False, "No legacy config file found"

    try:
        # Step 1: Create backup
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = config_dir / f'mappings.conf.pre-migration.{timestamp}.backup'
        shutil.copy2(str(legacy_path), str(backup_path))
        logger.info(f"Created backup at {backup_path}")

        # Step 2: Load all profiles from legacy config
        profiles = load_profiles_from_legacy_file(str(legacy_path))
        if not profiles:
            return False, "No profiles found in legacy config"

        logger.info(f"Found {len(profiles)} profiles to migrate")

        # Step 3: Create profiles directory
        profiles_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created profiles directory: {profiles_dir}")

        # Step 4: Save each profile to individual file
        migrated = 0
        for profile in profiles:
            filepath = get_profile_filepath(profile.name)

            if save_profile_to_file(profile, filepath):
                migrated += 1
                logger.info(f"Migrated profile '{profile.name}' to {filepath}")
            else:
                logger.error(f"Failed to migrate profile '{profile.name}'")

        # Step 5: Create new config.conf with device settings only
        device_config = load_device_config(str(legacy_path))
        _write_device_config(new_config_path, device_config)
        logger.info(f"Created new config file: {new_config_path}")

        # Step 6: Rename old config to mark as migrated
        legacy_backup = config_dir / 'mappings.conf.legacy'
        os.rename(str(legacy_path), str(legacy_backup))
        logger.info(f"Renamed legacy config to {legacy_backup}")

        return True, f"Successfully migrated {migrated} profiles. Backup saved to {backup_path}"

    except Exception as ex:
        logger.error(f"Migration failed: {ex}")
        return False, f"Migration failed: {ex}"


def _write_device_config(filepath: Path, device_config: Dict) -> bool:
    """Write device configuration to config.conf

    Args:
        filepath: Path to config.conf
        device_config: Device settings dictionary

    Returns:
        True if successful
    """
    try:
        lines = []
        lines.append("# TuxBox Configuration")
        lines.append("# Profile mappings are stored in the profiles/ directory")
        lines.append("")
        lines.append("[device]")

        if 'connection' in device_config:
            lines.append(f"connection = {device_config['connection']}")

        if 'mac_address' in device_config:
            lines.append(f"mac_address = {device_config['mac_address']}")

        if 'usb_port' in device_config:
            lines.append(f"usb_port = {device_config['usb_port']}")

        if 'force_haptics' in device_config:
            value = 'true' if device_config['force_haptics'] else 'false'
            lines.append(f"force_haptics = {value}")

        # Preserve tuning settings so migration does not silently reset them
        if 'modifier_delay' in device_config:
            lines.append(f"modifier_delay = {device_config['modifier_delay']}")

        if 'window_poll_interval' in device_config:
            lines.append(f"window_poll_interval = {device_config['window_poll_interval']}")

        if 'ctrl_key' in device_config:
            lines.append(f"ctrl_key = {device_config['ctrl_key']}")

        lines.append("")

        # Write atomically
        temp_path = filepath.with_suffix('.tmp')
        with open(temp_path, 'w') as f:
            f.write('\n'.join(lines))

        os.replace(str(temp_path), str(filepath))
        return True

    except Exception as ex:
        logger.error(f"Error writing device config: {ex}")
        return False


def needs_migration() -> bool:
    """Check if migration is needed

    Returns:
        True if legacy config exists and profiles directory doesn't
    """
    return is_legacy_config() and not has_profiles_dir()


def load_profiles_from_directory() -> List:
    """Load all profiles from the profiles directory

    Returns:
        List of Profile objects
    """
    profiles = []

    for filepath in discover_profiles():
        profile = load_profile_from_file(filepath)
        if profile:
            profiles.append(profile)

    return profiles


def delete_profile_file(profile_name: str) -> bool:
    """Delete a profile file

    Args:
        profile_name: Name of the profile to delete

    Returns:
        True if successful
    """
    filepath = get_profile_filepath(profile_name)

    if not filepath.exists():
        logger.warning(f"Profile file not found: {filepath}")
        return False

    try:
        os.remove(str(filepath))
        logger.info(f"Deleted profile file: {filepath}")
        return True
    except Exception as ex:
        logger.error(f"Error deleting profile file: {ex}")
        return False


def rename_profile_file(old_name: str, new_name: str) -> bool:
    """Rename a profile file

    Args:
        old_name: Current profile name
        new_name: New profile name

    Returns:
        True if successful
    """
    old_path = get_profile_filepath(old_name)
    new_path = get_profile_filepath(new_name)

    if not old_path.exists():
        logger.warning(f"Profile file not found: {old_path}")
        return False

    if new_path.exists():
        logger.warning(f"Target profile file already exists: {new_path}")
        return False

    try:
        os.rename(str(old_path), str(new_path))
        logger.info(f"Renamed profile file: {old_path} -> {new_path}")
        return True
    except Exception as ex:
        logger.error(f"Error renaming profile file: {ex}")
        return False


def profile_exists(profile_name: str) -> bool:
    """Check if a profile file exists

    Args:
        profile_name: Name of the profile

    Returns:
        True if profile file exists
    """
    filepath = get_profile_filepath(profile_name)
    return filepath.exists()


def create_initial_config(mac_address: str = None) -> Tuple[bool, str]:
    """Create initial configuration in new format from default_mappings.conf

    This is used for fresh installs to create the new format directly,
    rather than creating legacy format and migrating.

    Args:
        mac_address: Optional MAC address to set in config.conf

    Returns:
        Tuple of (success, message)
    """
    from .config_loader import load_profiles_from_legacy_file

    config_dir = get_config_dir()
    profiles_dir = get_profiles_dir()

    # Check if config already exists
    if has_profiles_dir():
        return False, "Configuration already exists"

    if is_legacy_config():
        return False, "Legacy configuration exists - use migration instead"

    # Find default_mappings.conf
    default_config = Path(__file__).parent / 'default_mappings.conf'
    if not default_config.exists():
        return False, f"Default config not found: {default_config}"

    try:
        # Load profiles from default config
        profiles = load_profiles_from_legacy_file(str(default_config))
        if not profiles:
            return False, "No profiles found in default config"

        # Create directories
        config_dir.mkdir(parents=True, exist_ok=True)
        profiles_dir.mkdir(parents=True, exist_ok=True)

        # Write each profile to individual file
        profile_count = 0
        for profile in profiles:
            filepath = get_profile_filepath(profile.name)
            if save_profile_to_file(profile, filepath):
                profile_count += 1
                logger.info(f"Created profile: {profile.name}")

        if profile_count == 0:
            return False, "Failed to create any profile files"

        # Create config.conf with device settings
        device_config = {
            'mac_address': mac_address if mac_address else 'XX:XX:XX:XX:XX:XX'
        }
        config_path = config_dir / 'config.conf'
        _write_device_config(config_path, device_config)

        return True, f"Created {profile_count} profile(s) in {profiles_dir}"

    except Exception as ex:
        logger.error(f"Error creating initial config: {ex}")
        return False, f"Error: {ex}"


def ensure_tuxbox_gui_profile() -> Tuple[bool, str]:
    """Ensure the TuxBox GUI profile exists

    This is called during reinstall to ensure the meta-configuration profile
    is present even if other profiles exist. The TuxBox GUI profile allows
    the TourBox to control its own configuration GUI.

    Returns:
        Tuple of (success, message)
    """
    from .config_loader import load_profiles_from_legacy_file

    profiles_dir = get_profiles_dir()
    gui_profile_path = profiles_dir / 'tuxbox_gui.profile'

    # Clean up stale old-name GUI profile if it exists
    old_gui_profile = profiles_dir / 'tourbox_gui.profile'
    if old_gui_profile.exists():
        try:
            old_gui_profile.unlink()
            logger.info(f"Removed stale GUI profile: {old_gui_profile.name}")
        except Exception as ex:
            logger.warning(f"Could not remove stale GUI profile: {ex}")

    # Already exists
    if gui_profile_path.exists():
        return True, "TuxBox GUI profile already exists"

    # Find default_mappings.conf
    default_config = Path(__file__).parent / 'default_mappings.conf'
    if not default_config.exists():
        return False, f"Default config not found: {default_config}"

    try:
        # Load all profiles from default config
        profiles = load_profiles_from_legacy_file(str(default_config))

        # Find the TuxBox GUI profile
        gui_profile = None
        for profile in profiles:
            if profile.name == 'TuxBox GUI':
                gui_profile = profile
                break

        if gui_profile is None:
            return False, "TuxBox GUI profile not found in default config"

        # Ensure profiles directory exists
        profiles_dir.mkdir(parents=True, exist_ok=True)

        # Save the profile
        if save_profile_to_file(gui_profile, gui_profile_path):
            logger.info(f"Created TuxBox GUI profile: {gui_profile_path}")
            return True, f"Created TuxBox GUI profile"
        else:
            return False, "Failed to save TuxBox GUI profile"

    except Exception as ex:
        logger.error(f"Error ensuring TuxBox GUI profile: {ex}")
        return False, f"Error: {ex}"


def ensure_default_profile() -> Tuple[bool, str]:
    """Ensure the default profile exists

    This is called during reinstall to ensure the default profile
    is present even if other profiles exist. The default profile is
    the fallback used when no app-specific profile matches.

    Returns:
        Tuple of (success, message)
    """
    from .config_loader import load_profiles_from_legacy_file

    profiles_dir = get_profiles_dir()
    default_profile_path = profiles_dir / 'default.profile'

    # Already exists
    if default_profile_path.exists():
        return True, "Default profile already exists"

    # Find default_mappings.conf
    default_config = Path(__file__).parent / 'default_mappings.conf'
    if not default_config.exists():
        return False, f"Default config not found: {default_config}"

    try:
        # Load all profiles from default config
        profiles = load_profiles_from_legacy_file(str(default_config))

        # Find the default profile
        default_profile = None
        for profile in profiles:
            if profile.name == 'default':
                default_profile = profile
                break

        if default_profile is None:
            return False, "Default profile not found in default config"

        # Ensure profiles directory exists
        profiles_dir.mkdir(parents=True, exist_ok=True)

        # Save the profile
        if save_profile_to_file(default_profile, default_profile_path):
            logger.info(f"Created default profile: {default_profile_path}")
            return True, f"Created default profile"
        else:
            return False, "Failed to save default profile"

    except Exception as ex:
        logger.error(f"Error ensuring default profile: {ex}")
        return False, f"Error: {ex}"
