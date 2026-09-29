#!/usr/bin/env python3
"""Configuration loader for TuxBox button mappings

Loads user-defined button mappings from config file and converts them
to the internal MAPPING dictionary format used by the driver.

Supports application-specific profiles for automatic mapping switching.
"""

import os
import configparser
import logging
import re
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field
from evdev import ecodes as e

from .haptic import HapticConfig, HapticStrength, HapticSpeed
from .window_monitor import (
    DEFAULT_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    MAX_POLL_INTERVAL,
)

logger = logging.getLogger(__name__)

# Transports the driver may use, set with `connection` in the [device] section.
#   auto - USB if present, otherwise Bluetooth (with USB hot-plug promotion)
#   usb  - USB only; the Bluetooth radio is never touched
#   ble  - Bluetooth only; /dev/ttyACM* is never probed
VALID_CONNECTION_MODES = frozenset(('auto', 'usb', 'ble'))
DEFAULT_CONNECTION_MODE = 'auto'


@dataclass
class Profile:
    """Application-specific button mapping profile"""
    name: str
    window_class: Optional[str] = None
    window_title: Optional[str] = None
    app_id: Optional[str] = None
    mapping: Optional[Dict] = None
    capabilities: Optional[Dict] = None

    # NEW FIELDS FOR MODIFIERS
    modifier_buttons: Set[str] = field(default_factory=set)  # e.g., {'tall', 'short'}
    modifier_mappings: Dict[Tuple[str, str], str] = field(default_factory=dict)  # (modifier, control) -> action
    modifier_base_actions: Dict[str, str] = field(default_factory=dict)  # modifier -> base_action (optional)

    # NEW FIELDS FOR COMMENTS
    mapping_comments: Dict[str, str] = field(default_factory=dict)  # control -> comment
    modifier_combo_comments: Dict[Tuple[str, str], str] = field(default_factory=dict)  # (modifier, control) -> comment

    # Haptic feedback configuration
    haptic_config: HapticConfig = field(default_factory=HapticConfig.default_off)

    # Profile enabled state (disabled profiles are skipped during window matching)
    enabled: bool = True

    # Double-click configuration
    double_click_timeout: int = 300  # ms, default
    double_press_actions: Dict[str, str] = field(default_factory=dict)  # control -> action string
    double_press_comments: Dict[str, str] = field(default_factory=dict)  # control -> comment

    # On-release controls (fire action on release as tap, not on press)
    on_release_controls: Set[str] = field(default_factory=set)
    # Controls where user explicitly disabled on_release (don't auto-enable again)
    on_release_user_disabled: Set[str] = field(default_factory=set)

    # Per-profile modifier delay override (None = use global, 0 = disabled, >0 = ms)
    modifier_delay: Optional[int] = None

    def matches(self, window_info) -> bool:
        """Check if this profile matches the given window info"""
        # Disabled profiles never match (except default which is always enabled)
        if not self.enabled and self.name != 'default':
            return False

        if not window_info:
            return False

        # Check app_id match (exact or case-insensitive)
        if self.app_id:
            if window_info.app_id and window_info.app_id.lower() == self.app_id.lower():
                return True

        # Check window_class match (exact or case-insensitive)
        if self.window_class:
            if window_info.wm_class and window_info.wm_class.lower() == self.window_class.lower():
                return True

        # Check window_title match (substring, case-insensitive)
        if self.window_title:
            if window_info.title and self.window_title.lower() in window_info.title.lower():
                return True

        return False

    def __repr__(self):
        matchers = []
        if self.app_id:
            matchers.append(f"app_id={self.app_id}")
        if self.window_class:
            matchers.append(f"class={self.window_class}")
        if self.window_title:
            matchers.append(f"title={self.window_title}")
        return f"Profile({self.name}: {', '.join(matchers)})"

# Button name to hex code mapping
BUTTON_CODES = {
    # Buttons (press/release)
    'side': (0x01, 0x81),
    'top': (0x02, 0x82),
    'scroll_click': (0x0a, 0x8a),
    'c1': (0x22, 0xa2),
    'c2': (0x23, 0xa3),
    'tall': (0x00, 0x80),
    'short': (0x03, 0x83),
    'dpad_up': (0x10, 0x90),
    'dpad_down': (0x11, 0x91),
    'dpad_left': (0x12, 0x92),
    'dpad_right': (0x13, 0x93),
    'knob_click': (0x37, 0xb7),
    'tour': (0x2a, 0xaa),
    'dial_click': (0x38, 0xb8),

    # Rotary controls (CW/CCW) - includes stop events
    'scroll_up': (0x49, 0xc9),
    'scroll_down': (0x09, 0x89),
    'knob_cw': (0x44, 0xc4),
    'knob_ccw': (0x04, 0x84),
    'dial_cw': (0x4f, 0xcf),
    'dial_ccw': (0x0f, 0x8f),
}

# Supported key names (subset of evdev ecodes)
KEY_NAMES = {
    'KEY_LEFTMETA': e.KEY_LEFTMETA,
    'KEY_LEFTCTRL': e.KEY_LEFTCTRL,
    'KEY_LEFTSHIFT': e.KEY_LEFTSHIFT,
    'KEY_LEFTALT': e.KEY_LEFTALT,
    'KEY_RIGHTALT': e.KEY_RIGHTALT,
    'KEY_RIGHTCTRL': e.KEY_RIGHTCTRL,
    'KEY_RIGHTSHIFT': e.KEY_RIGHTSHIFT,
    'KEY_SPACE': e.KEY_SPACE,
    'KEY_ENTER': e.KEY_ENTER,
    'KEY_TAB': e.KEY_TAB,
    'KEY_ESC': e.KEY_ESC,
    'KEY_BACKSPACE': e.KEY_BACKSPACE,
    'KEY_DELETE': e.KEY_DELETE,
    'KEY_INSERT': e.KEY_INSERT,
    'KEY_HOME': e.KEY_HOME,
    'KEY_END': e.KEY_END,
    'KEY_PAGEUP': e.KEY_PAGEUP,
    'KEY_PAGEDOWN': e.KEY_PAGEDOWN,
    'KEY_UP': e.KEY_UP,
    'KEY_DOWN': e.KEY_DOWN,
    'KEY_LEFT': e.KEY_LEFT,
    'KEY_RIGHT': e.KEY_RIGHT,
    'KEY_CONTEXT_MENU': e.KEY_CONTEXT_MENU,
    'KEY_ZOOMRESET': e.KEY_ZOOMRESET,
    'KEY_ZOOMIN': e.KEY_ZOOMIN,
    'KEY_ZOOMOUT': e.KEY_ZOOMOUT,
    # Symbol keys
    'KEY_MINUS': e.KEY_MINUS,
    'KEY_EQUAL': e.KEY_EQUAL,
    'KEY_LEFTBRACE': e.KEY_LEFTBRACE,
    'KEY_RIGHTBRACE': e.KEY_RIGHTBRACE,
    'KEY_SEMICOLON': e.KEY_SEMICOLON,
    'KEY_APOSTROPHE': e.KEY_APOSTROPHE,
    'KEY_GRAVE': e.KEY_GRAVE,
    'KEY_BACKSLASH': e.KEY_BACKSLASH,
    'KEY_COMMA': e.KEY_COMMA,
    'KEY_DOT': e.KEY_DOT,
    'KEY_SLASH': e.KEY_SLASH,
    'KEY_PERIOD': e.KEY_DOT,  # Alias for KEY_DOT
    # Numpad keys
    **{f'KEY_KP{i}': getattr(e, f'KEY_KP{i}') for i in range(0, 10)},
    'KEY_KPMINUS': e.KEY_KPMINUS,
    'KEY_KPPLUS': e.KEY_KPPLUS,
    'KEY_KPASTERISK': e.KEY_KPASTERISK,
    'KEY_KPSLASH': e.KEY_KPSLASH,
    'KEY_KPDOT': e.KEY_KPDOT,
    'KEY_KPENTER': e.KEY_KPENTER,
    'KEY_KPEQUAL': e.KEY_KPEQUAL,
    'KEY_NUMLOCK': e.KEY_NUMLOCK,
    # Media keys
    'KEY_VOLUMEUP': e.KEY_VOLUMEUP,
    'KEY_VOLUMEDOWN': e.KEY_VOLUMEDOWN,
    'KEY_MUTE': e.KEY_MUTE,
    'KEY_PLAYPAUSE': e.KEY_PLAYPAUSE,
    'KEY_STOPCD': e.KEY_STOPCD,
    'KEY_PREVIOUSSONG': e.KEY_PREVIOUSSONG,
    'KEY_NEXTSONG': e.KEY_NEXTSONG,
    # Letter keys
    **{f'KEY_{chr(i)}': getattr(e, f'KEY_{chr(i)}') for i in range(ord('A'), ord('Z') + 1)},
    # Number keys
    **{f'KEY_{i}': getattr(e, f'KEY_{i}') for i in range(0, 10)},
    # Function keys (F1-F12, includes extended function keys for meta-configuration)
    **{f'KEY_F{i}': getattr(e, f'KEY_F{i}') for i in range(1, 13)},
    # Mouse buttons
    'BTN_LEFT': e.BTN_LEFT,
    'BTN_RIGHT': e.BTN_RIGHT,
    'BTN_MIDDLE': e.BTN_MIDDLE,
}

# Mouse/relative movement
REL_NAMES = {
    'REL_WHEEL': e.REL_WHEEL,
    'REL_HWHEEL': e.REL_HWHEEL,
    'REL_DIAL': e.REL_DIAL,
}


def parse_action(action_str: str) -> List[Tuple[int, int, int]]:
    """Parse an action string into evdev events

    Format examples:
        "KEY_A" -> single key press
        "KEY_LEFTCTRL+KEY_C" -> key combination (Ctrl+C)
        "REL_WHEEL:1" -> relative movement (wheel up)
        "REL_WHEEL:-1" -> relative movement (wheel down)
        "KEY_LEFTCTRL+REL_WHEEL:1" -> modifier + relative movement (Ctrl+scroll)

    Returns:
        List of (event_type, event_code, value) tuples
    """
    events = []

    if not action_str or action_str == 'none':
        return events

    # Split by + first to handle compound actions like KEY_LEFTCTRL+REL_WHEEL:1
    parts = [p.strip() for p in action_str.split('+')]

    for part in parts:
        # Check if this part is a relative event (has : and matches REL_*)
        if ':' in part:
            rel_parts = part.split(':')
            if len(rel_parts) == 2:
                rel_name, value_str = rel_parts
                rel_name = rel_name.strip()
                if rel_name in REL_NAMES:
                    try:
                        value = int(value_str.strip())
                        events.append((e.EV_REL, REL_NAMES[rel_name], value))
                        continue
                    except ValueError:
                        logger.error(f"Invalid relative value: {value_str}")
                        continue

        # Check if this part is a key (includes BTN_LEFT/RIGHT/MIDDLE)
        if part in KEY_NAMES:
            events.append((e.EV_KEY, KEY_NAMES[part], 1))  # Press
        else:
            logger.warning(f"Unknown key/button name: {part}")

    return events


def create_button_mapping(press_action: str, release_action: str = None) -> Tuple[List, List]:
    """Create press and release event lists for a button

    Args:
        press_action: Action string for button press
        release_action: Action string for button release (auto-generated if None)

    Returns:
        Tuple of (press_events, release_events)
    """
    press_events = parse_action(press_action)

    # Auto-generate release events if not specified
    if release_action is None:
        release_events = []
        for event_type, event_code, value in press_events:
            if event_type == e.EV_KEY:
                release_events.append((event_type, event_code, 0))  # Release key
            # REL events don't need release
    else:
        release_events = parse_action(release_action)

    return press_events, release_events


def get_config_path(config_path: str = None) -> str:
    """Find config file path

    Checks for both new format (config.conf) and legacy format (mappings.conf).

    Args:
        config_path: Path to config file. If None, searches default locations.

    Returns:
        Path to config file, or None if not found
    """
    if config_path is not None and os.path.exists(config_path):
        return config_path

    # Default config locations
    default_paths = []

    # If running under sudo, check the real user's config first
    # This allows: sudo ./driver -> uses /home/username/.config/tuxbox/...
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        sudo_home = os.path.expanduser(f'~{sudo_user}')
        # Check new format first
        sudo_config_new = os.path.join(sudo_home, '.config/tuxbox/config.conf')
        default_paths.append(sudo_config_new)
        # Then legacy format
        sudo_config_legacy = os.path.join(sudo_home, '.config/tuxbox/mappings.conf')
        default_paths.append(sudo_config_legacy)
        # Legacy tourbox paths (pre-v3 migration)
        default_paths.append(os.path.join(sudo_home, '.config/tourbox/config.conf'))
        default_paths.append(os.path.join(sudo_home, '.config/tourbox/mappings.conf'))

    # Then check current user's home (for non-sudo usage)
    default_paths.extend([
        os.path.expanduser('~/.config/tuxbox/config.conf'),  # New format
        os.path.expanduser('~/.config/tuxbox/mappings.conf'),  # Legacy format
        os.path.expanduser('~/.config/tourbox/config.conf'),  # Pre-v3 legacy path
        os.path.expanduser('~/.config/tourbox/mappings.conf'),  # Pre-v3 legacy path
        '/etc/tuxbox/mappings.conf',  # System-wide config
        os.path.join(os.path.dirname(__file__), 'default_mappings.conf'),  # Built-in fallback
    ])

    for path in default_paths:
        if os.path.exists(path):
            return path

    return None


DEFAULT_CONTROLLER_MODEL = 'elite'
VALID_CONTROLLER_MODELS = ('elite', 'lite')


def load_device_config(config_path: str = None) -> Dict[str, str]:
    """Load device settings from config file

    Args:
        config_path: Path to config file. If None, searches default locations.

    Returns:
        Dictionary with device settings (mac_address, etc.)
    """
    config_path = get_config_path(config_path)

    if not config_path:
        logger.warning("No config file found for device settings")
        return {}

    logger.info(f"Loading device config from {config_path}")

    config = configparser.ConfigParser(inline_comment_prefixes=('#',), interpolation=None)
    config.read(config_path)

    device_config = {}

    if 'device' in config:
        if 'controller_model' in config['device']:
            model = config['device']['controller_model'].strip().lower()
            if model in VALID_CONTROLLER_MODELS:
                device_config['controller_model'] = model
            else:
                logger.warning("Unknown controller_model '%s'; using %s",
                               model, DEFAULT_CONTROLLER_MODEL)
        if 'connection' in config['device']:
            # Which transports the driver is allowed to use. 'usb' keeps the
            # Bluetooth radio out of it entirely, which matters on a laptop:
            # with no TourBox present the BLE path otherwise scans forever.
            raw = config['device']['connection'].strip().lower()
            if raw in VALID_CONNECTION_MODES:
                device_config['connection'] = raw
            else:
                logger.warning(
                    f"Invalid connection mode '{raw}' "
                    f"(expected one of {', '.join(sorted(VALID_CONNECTION_MODES))}), "
                    f"using default '{DEFAULT_CONNECTION_MODE}'"
                )
        if 'mac_address' in config['device']:
            device_config['mac_address'] = config['device']['mac_address'].strip()
        if 'usb_port' in config['device']:
            device_config['usb_port'] = config['device']['usb_port'].strip()
        if 'force_haptics' in config['device']:
            # Parse boolean value
            force_val = config['device']['force_haptics'].strip().lower()
            device_config['force_haptics'] = force_val in ('true', 'yes', '1', 'on')
        if 'modifier_delay' in config['device']:
            # Parse integer value (milliseconds) - delay between modifier keys and main keys
            # Default is 0 (disabled). Set to 20-50 if applications don't recognize combos.
            try:
                device_config['modifier_delay'] = int(config['device']['modifier_delay'].strip())
            except ValueError:
                logger.warning(f"Invalid modifier_delay value, using default 0")
                device_config['modifier_delay'] = 0
        if 'window_poll_interval' in config['device']:
            # Parse float value (seconds) - how often the active window is checked
            # for profile switching. Raise this to reduce D-Bus/subprocess load.
            raw = config['device']['window_poll_interval'].strip()
            try:
                interval = float(raw)
            except ValueError:
                logger.warning(
                    f"Invalid window_poll_interval '{raw}', "
                    f"using default {DEFAULT_POLL_INTERVAL}s"
                )
            else:
                clamped = max(MIN_POLL_INTERVAL, min(MAX_POLL_INTERVAL, interval))
                if clamped != interval:
                    logger.warning(
                        f"window_poll_interval {interval}s out of range "
                        f"({MIN_POLL_INTERVAL}-{MAX_POLL_INTERVAL}s), clamped to {clamped}s"
                    )
                device_config['window_poll_interval'] = clamped

    return device_config


def parse_profile_mappings(config: configparser.ConfigParser, section_name: str) -> Tuple[Dict, Dict]:
    """Parse button/rotary mappings from a profile section

    Args:
        config: ConfigParser instance
        section_name: Name of the section (e.g., 'profile:vscode')

    Returns:
        Tuple of (mapping_dict, capabilities_dict)
    """
    mapping = {}

    # Parse button mappings from this section
    for key, action in config[section_name].items():
        # Skip matcher keys
        if key in ('window_class', 'window_title', 'app_id'):
            continue

        # Skip modifier declarations and combo mappings
        if action.strip() == 'modifier' or '.' in key:
            continue

        # Check if it's a button
        if key in BUTTON_CODES:
            codes = BUTTON_CODES[key]

            # Check if it's a rotary control (knob, scroll, dial)
            is_rotary = key in ('scroll_up', 'scroll_down', 'knob_cw', 'knob_ccw', 'dial_cw', 'dial_ccw')

            if len(codes) == 2:
                press_code, release_code = codes
                press_events, release_events = create_button_mapping(action)

                if is_rotary:
                    # For rotary: rotation event = full press+release cycle
                    # Stop event = release only (to ensure keys don't stick)
                    mapping[bytes([press_code])] = press_events + release_events
                    mapping[bytes([release_code])] = release_events
                else:
                    # For buttons: separate press and release
                    mapping[bytes([press_code])] = press_events
                    mapping[bytes([release_code])] = release_events
            elif len(codes) == 1:  # Old format rotary event
                code = codes[0]
                events = parse_action(action)
                mapping[bytes([code])] = events

    # Get capabilities for UInput
    caps = get_capabilities_from_mapping(mapping)

    return mapping, caps


def load_profiles(config_path: str = None) -> List[Profile]:
    """Load application-specific profiles from config file or profiles directory

    This function supports both the new multi-file format (profiles/*.profile)
    and the legacy single-file format (mappings.conf with [profile:*] sections).

    Args:
        config_path: Path to config file. If None, searches default locations.

    Returns:
        List of Profile objects (includes default profile if present)
    """
    from .profile_io import has_profiles_dir, load_profiles_from_directory

    # Check if new format exists (profiles directory with .profile files)
    if has_profiles_dir():
        logger.info("Loading profiles from profiles directory (new format)")
        return load_profiles_from_directory()

    # Fall back to legacy format
    config_path = get_config_path(config_path)

    if not config_path:
        logger.warning("No config file found for profiles")
        return []

    return load_profiles_from_legacy_file(config_path)


def load_profiles_from_legacy_file(config_path: str) -> List[Profile]:
    """Load profiles from a legacy format config file

    This loads profiles from a single config file with [profile:*] sections.
    Used for migration and initial config creation.

    Args:
        config_path: Path to the legacy config file

    Returns:
        List of Profile objects
    """
    logger.info(f"Loading profiles from {config_path} (legacy format)")

    config = configparser.ConfigParser(inline_comment_prefixes=('#',), interpolation=None)
    config.read(config_path)

    profiles = []

    # Find all profile sections
    profile_pattern = re.compile(r'^profile:(.+)$')
    for section in config.sections():
        match = profile_pattern.match(section)
        if match:
            profile_name = match.group(1)

            # Parse matchers
            window_class = config[section].get('window_class')
            window_title = config[section].get('window_title')
            app_id = config[section].get('app_id')

            # Parse mappings
            mapping, caps = parse_profile_mappings(config, section)

            # Parse modifier configurations
            modifier_buttons, modifier_mappings, modifier_base_actions = parse_modifier_mappings(config, section)

            # Parse comments
            mapping_comments, modifier_combo_comments = parse_mapping_comments(config, section)

            # Parse haptic configuration
            haptic_config = parse_haptic_config(config, section)

            # Add modifier combo actions to capabilities
            for action_str in modifier_mappings.values():
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

            # Add modifier base actions to capabilities
            for action_str in modifier_base_actions.values():
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

            profile = Profile(
                name=profile_name,
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
                haptic_config=haptic_config
            )

            profiles.append(profile)
            logger.info(f"Loaded profile: {profile}")
            if modifier_buttons:
                logger.info(f"  Modifiers: {', '.join(modifier_buttons)}")
            if modifier_mappings:
                logger.info(f"  Modifier combos: {len(modifier_mappings)}")
            if haptic_config.global_setting is not None:
                speed_str = f", speed={haptic_config.global_speed}" if haptic_config.global_speed else ""
                logger.info(f"  Haptic: {haptic_config.global_setting}{speed_str}")

    return profiles


def load_config(config_path: str = None) -> Dict[bytes, List[Tuple[int, int, int]]]:
    """Load button mappings from config file (DEPRECATED - use load_profiles instead)

    This function is kept for backward compatibility but will return empty
    mappings. All configs should use the profile format.

    Args:
        config_path: Path to config file. If None, searches default locations.

    Returns:
        Empty dictionary (profiles should be used instead)
    """
    logger.warning("load_config() is deprecated - config file should use profile format")
    return {}, {}


def get_capabilities_from_mapping(mapping: Dict) -> Dict:
    """Extract required input capabilities from mapping

    Args:
        mapping: Button mapping dictionary

    Returns:
        Dictionary of capabilities for UInput
    """
    keys = set()
    rels = set()

    for events in mapping.values():
        for event_type, event_code, _ in events:
            if event_type == e.EV_KEY:
                keys.add(event_code)
            elif event_type == e.EV_REL:
                rels.add(event_code)

    caps = {}
    if keys:
        caps[e.EV_KEY] = list(keys)
    if rels:
        caps[e.EV_REL] = list(rels)

    return caps


# Define which controls can be modifiers (physical buttons with press/release events)
VALID_MODIFIER_BUTTONS = {
    'side', 'top', 'short', 'tall',
    'c1', 'c2',
    'dpad_up', 'dpad_down', 'dpad_left', 'dpad_right',
    'scroll_click', 'knob_click', 'dial_click',
    'tour'
}

# Rotary controls that CANNOT be modifiers (momentary, cannot be held)
INVALID_MODIFIER_CONTROLS = {
    'scroll_up', 'scroll_down',
    'knob_cw', 'knob_ccw',
    'dial_cw', 'dial_ccw'
}


def parse_modifier_mappings(config: configparser.ConfigParser, section_name: str) -> Tuple[Set[str], Dict[Tuple[str, str], str], Dict[str, str]]:
    """Parse modifier button configurations from a profile section

    Args:
        config: ConfigParser instance
        section_name: Name of the section (e.g., 'profile:default')

    Returns:
        Tuple of (modifier_buttons, modifier_mappings, modifier_base_actions)
        - modifier_buttons: Set of button names that are modifiers
        - modifier_mappings: Dict mapping (modifier, control) -> action_string
        - modifier_base_actions: Dict mapping modifier -> base_action_string
    """
    modifier_buttons = set()
    modifier_mappings = {}
    modifier_base_actions = {}

    # First pass: identify modifiers
    for key, value in config[section_name].items():
        # Check if this is a modifier declaration
        if value.strip() == 'modifier':
            control_name = key.strip()

            # Validate that only physical buttons can be modifiers
            if control_name in INVALID_MODIFIER_CONTROLS:
                logger.error(f"Invalid modifier declaration: {control_name} cannot be a modifier (rotary controls cannot be held)")
                logger.error(f"Only physical buttons with press/release events can be modifiers")
                continue

            if control_name not in VALID_MODIFIER_BUTTONS:
                logger.warning(f"Unknown control declared as modifier: {control_name}")

            modifier_buttons.add(control_name)
            logger.debug(f"Found modifier button: {control_name}")

    # Second pass: parse modifier base actions and combinations
    for key, value in config[section_name].items():
        # Skip non-modifier related keys
        if key in ('window_class', 'window_title', 'app_id'):
            continue

        # Check for modifier base action: "modifier.base_action = ACTION"
        if '.base_action' in key and not key.endswith('.comment'):
            parts = key.split('.')
            if len(parts) == 2:
                modifier_name = parts[0].strip()
                if modifier_name in modifier_buttons:
                    modifier_base_actions[modifier_name] = value.strip()
                    logger.debug(f"Found base action for modifier {modifier_name}: {value.strip()}")

        # Check for modifier combination: "modifier.control = ACTION"
        elif '.' in key and not key.endswith('.comment') and not key.endswith('.base_action'):
            parts = key.split('.')
            if len(parts) == 2:
                modifier_name, control_name = parts[0].strip(), parts[1].strip()

                # Check if this is a modifier combination
                if modifier_name in modifier_buttons:
                    # Validate: prevent self-referential combos
                    if modifier_name == control_name:
                        logger.error(f"Invalid self-referential combo: {key} = {value}")
                        logger.error(f"A modifier button cannot be combined with itself")
                        continue

                    modifier_mappings[(modifier_name, control_name)] = value.strip()
                    logger.debug(f"Found modifier combo: {modifier_name}.{control_name} = {value.strip()}")

    return modifier_buttons, modifier_mappings, modifier_base_actions


def parse_mapping_comments(config: configparser.ConfigParser, section_name: str) -> Tuple[Dict[str, str], Dict[Tuple[str, str], str]]:
    """Parse comments for all mappings in a profile section

    Args:
        config: ConfigParser instance
        section_name: Name of the section (e.g., 'profile:default')

    Returns:
        Tuple of (mapping_comments, modifier_combo_comments)
        - mapping_comments: Dict mapping control -> comment
        - modifier_combo_comments: Dict mapping (modifier, control) -> comment
    """
    mapping_comments = {}
    modifier_combo_comments = {}

    for key, value in config[section_name].items():
        # Skip non-comment keys
        if not key.endswith('.comment'):
            continue

        # Remove the .comment suffix to get the control/combo name
        control_key = key[:-len('.comment')].strip()

        # Convert escape sequences to actual newlines for multiline support
        comment_text = value.strip().replace('\\n', '\n')

        # Check if this is a combo comment: "modifier.control.comment"
        if '.' in control_key:
            parts = control_key.split('.')

            # Check for base_action comment: "modifier.base_action.comment"
            if len(parts) == 2 and parts[1] == 'base_action':
                # Store as a special mapping comment for the base action
                modifier_name = parts[0].strip()
                mapping_comments[f"{modifier_name}.base_action"] = comment_text
                logger.debug(f"Found base action comment for {modifier_name}: {comment_text[:50]}...")

            # Regular combo comment: "modifier.control.comment"
            elif len(parts) == 2:
                modifier_name, control_name = parts[0].strip(), parts[1].strip()
                modifier_combo_comments[(modifier_name, control_name)] = comment_text
                logger.debug(f"Found combo comment for {modifier_name}.{control_name}: {comment_text[:50]}...")

        # Regular control comment: "control.comment"
        else:
            mapping_comments[control_key] = comment_text
            logger.debug(f"Found comment for {control_key}: {comment_text[:50]}...")

    return mapping_comments, modifier_combo_comments


def parse_haptic_config(config: configparser.ConfigParser, section_name: str) -> HapticConfig:
    """Parse haptic configuration from a profile section

    Supports global, per-dial, and per-combo formats for both strength and speed:
    - Global: haptic = weak, haptic_speed = medium
    - Per-dial strength: haptic.knob = strong
    - Per-dial speed: haptic_speed.knob = slow
    - Per-combo strength: haptic.knob.tall = weak
    - Per-combo speed: haptic_speed.knob.tall = medium

    Args:
        config: ConfigParser instance
        section_name: Name of the section (e.g., 'profile:default')

    Returns:
        HapticConfig with parsed settings
    """
    haptic_config = HapticConfig()

    for key, value in config[section_name].items():
        if key == 'haptic':
            # Global profile haptic strength setting
            haptic_config.global_setting = HapticStrength.from_string(value)
            logger.debug(f"Parsed global haptic: {value} -> {haptic_config.global_setting}")

        elif key == 'haptic_speed':
            # Global haptic speed setting
            haptic_config.global_speed = HapticSpeed.from_string(value)
            logger.debug(f"Parsed global haptic speed: {value} -> {haptic_config.global_speed}")

        elif key.startswith('haptic.'):
            parts = key.split('.')
            if len(parts) == 2:
                # Per-dial strength: haptic.knob = weak
                dial = parts[1]
                strength = HapticStrength.from_string(value)
                haptic_config.dial_settings[dial] = strength
                logger.debug(f"Parsed dial haptic: {dial} = {strength}")

            elif len(parts) == 3:
                # Per-combo strength: haptic.knob.tall = strong
                dial, modifier = parts[1], parts[2]
                strength = HapticStrength.from_string(value)
                haptic_config.combo_settings[(dial, modifier)] = strength
                logger.debug(f"Parsed combo haptic: {dial}.{modifier} = {strength}")

        elif key.startswith('haptic_speed.'):
            parts = key.split('.')
            if len(parts) == 2:
                # Per-dial speed: haptic_speed.knob = slow
                dial = parts[1]
                speed = HapticSpeed.from_string(value)
                haptic_config.dial_speed_settings[dial] = speed
                logger.debug(f"Parsed dial haptic speed: {dial} = {speed}")

            elif len(parts) == 3:
                # Per-combo speed: haptic_speed.knob.tall = medium
                dial, modifier = parts[1], parts[2]
                speed = HapticSpeed.from_string(value)
                haptic_config.combo_speed_settings[(dial, modifier)] = speed
                logger.debug(f"Parsed combo haptic speed: {dial}.{modifier} = {speed}")

    # Note: global_setting is preserved as the default fallback for dials
    # that don't have a specific per-dial setting ("Use Profile Default").
    # Per-dial and per-combo settings take precedence over global settings.

    return haptic_config


def get_default_mapping():
    """Return built-in default mapping (from original constants.py)"""
    from .constants import MAPPING, CAP
    return MAPPING, CAP
