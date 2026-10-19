#!/usr/bin/env python3
"""TuxBox Base Driver - Abstract base class for transport implementations

This module contains the shared logic for both BLE and USB transport implementations.
It handles button code processing, modifier state machine, profile management,
and virtual input device (uinput) creation.
"""

import os
import signal
import logging
import pathlib
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Set, List, Tuple

from evdev import UInput, ecodes as e
from .config_loader import (
    load_profiles, load_device_config, BUTTON_CODES, parse_action, set_ctrl_key,
    DEFAULT_CTRL_KEY
)
from .window_monitor import WindowMonitor, DEFAULT_POLL_INTERVAL

# Keyboard modifier keys - these need to be sent before main keys for proper combo recognition
KEYBOARD_MODIFIER_KEYS = {
    e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL,
    e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT,
    e.KEY_LEFTALT, e.KEY_RIGHTALT,
    e.KEY_LEFTMETA, e.KEY_RIGHTMETA,
    # Sent for Ctrl when [device] ctrl_key = capslock (Ctrl/Caps Lock swapped)
    e.KEY_CAPSLOCK,
}

# Mouse button keys - paired with KEYBOARD_MODIFIER_KEYS to detect modifier+mouse
# combos that need a forced delay (see AUTO_MOUSE_MODIFIER_DELAY_MS).
MOUSE_EVENT_KEYS = {e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE}

# When a single batch contains both a modifier press and a mouse event (REL_* or
# BTN_LEFT/RIGHT/MIDDLE), we force at least this much delay between the modifier
# and the mouse event so the compositor has time to latch the modifier into
# keystate before the pointer event arrives. Without this, apps like DaVinci
# Resolve see Alt+scroll as a plain scroll. Pure-keyboard combos are not
# affected and still honor the user's `modifier_delay` setting verbatim.
AUTO_MOUSE_MODIFIER_DELAY_MS = 15

logger = logging.getLogger(__name__)

# Controls that can be held (buttons) vs momentary (rotary)
# Used for "last-wins" behavior where pressing a new button releases the previous
HOLDABLE_BUTTONS = {
    'side', 'top', 'short', 'tall',
    'c1', 'c2',
    'dpad_up', 'dpad_down', 'dpad_left', 'dpad_right',
    'scroll_click', 'knob_click', 'dial_click',
    'tour'
}


class GracefulKiller:
    """Handle SIGINT, SIGTERM, and SIGHUP gracefully"""
    kill_now = False
    reload_config = False

    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)
        signal.signal(signal.SIGHUP, self.reload_gracefully)

    def exit_gracefully(self, *args):
        self.kill_now = True

    def reload_gracefully(self, *args):
        self.reload_config = True
        logger.info("Received SIGHUP - will reload config")


class TuxBoxBase(ABC):
    """Abstract base class for TourBox Elite transport implementations

    This class contains all transport-agnostic logic including:
    - Button code to control name mapping
    - Modifier button state machine
    - Profile switching and management
    - Virtual input device (uinput) creation and event sending
    - Configuration hot-reload via SIGHUP

    Subclasses must implement:
    - connect(): Establish connection to device
    - disconnect(): Close connection
    - run_connection(): Main connection loop
    """

    def __init__(self, pidfile: Optional[str] = None, config_path: Optional[str] = None):
        """Initialize the TuxBox driver base

        Args:
            pidfile: Path to PID file (default: $XDG_RUNTIME_DIR/tuxbox.pid)
            config_path: Path to configuration file (default: auto-detect)
        """
        # Default to user runtime dir, fallback to /tmp for user access
        default_pidfile = os.path.join(os.getenv('XDG_RUNTIME_DIR', '/tmp'), 'tuxbox.pid')
        self.pidfile = pidfile or os.getenv('pidfile') or default_pidfile
        self.config_path = config_path
        self.controller: Optional[UInput] = None
        self.device_name = "TourBox"
        self.killer = GracefulKiller()
        self.button_count = 0
        self.mapping: Optional[Dict] = None
        self.capabilities: Optional[Dict] = None
        self.profiles: List = []
        self.current_profile = None
        self.window_monitor: Optional[WindowMonitor] = None
        self.use_profiles = False

        # Modifier state tracking
        self.modifier_buttons: Set[str] = set()        # Set of button names that are modifiers
        self.active_modifiers: Set[str] = set()        # Currently pressed modifier buttons
        self.modifier_mappings: Dict[Tuple[str, str], List] = {}  # (modifier, control) -> action events
        self.modifier_base_actions: Dict[str, List] = {}  # modifier -> base action events
        self.base_action_active: Set[str] = set()      # Modifiers with base action currently pressed
        self.combo_used: Set[str] = set()              # Modifiers that had a combo used while held

        # Last-wins button state tracking
        # Maps button_name -> list of (event_type, event_code, value) press events
        self.active_button_events: Dict[str, List[Tuple[int, int, int]]] = {}

        # Active combo tracking - for proper release when modifier is released first
        # Maps combo_target_button -> list of (event_type, event_code, value) press events
        self.active_combo_events: Dict[str, List[Tuple[int, int, int]]] = {}

        # Double-click state tracking (immediate fire - no timer-based deferral)
        self._double_click_first_press: Dict[str, float] = {}  # control -> timestamp of first press
        self._double_click_active_events: Dict[str, List] = {}  # control -> active double-press events (for release)

        # On-release button tracking - buttons that fire on release as a tap
        self._on_release_pending: Dict[str, List[Tuple[int, int, int]]] = {}  # control -> deferred events
        # On-release combo tracking - for on_release buttons pressed while modifier active
        self._on_release_combo_pending: Dict[str, Tuple[str, List]] = {}  # control -> (modifier_name, combo_events)
        # On-release modifier tracking - modifier buttons with on_release that need base action on release
        self._on_release_modifier_pending: Dict[str, List[Tuple[int, int, int]]] = {}  # control -> base action events

        # Load device config for modifier_delay and ctrl_key settings
        device_config = load_device_config(config_path)
        # Must be set before profiles are parsed into key events
        ctrl_key = device_config.get('ctrl_key', DEFAULT_CTRL_KEY)
        set_ctrl_key(ctrl_key)
        if ctrl_key != DEFAULT_CTRL_KEY:
            logger.info(f"Ctrl in mappings is sent as: {ctrl_key}")
        # Global modifier delay in milliseconds - time between modifier keys and main keys
        # Default 0 (disabled). Set to 20-50 if apps don't recognize key combos.
        # Per-profile values override this when set.
        self._global_modifier_delay = device_config.get('modifier_delay', 0)
        self.modifier_delay = self._global_modifier_delay
        if self.modifier_delay > 0:
            logger.info(f"Global modifier delay enabled: {self.modifier_delay}ms")

        # How often the active window is polled for profile switching.
        # Configurable via [device] window_poll_interval in config.conf.
        self.window_poll_interval = device_config.get(
            'window_poll_interval', DEFAULT_POLL_INTERVAL
        )

    def is_modifier_button(self, control_name: str) -> bool:
        """Check if a control is configured as a modifier button

        Args:
            control_name: Name of the control (e.g., 'tall', 'short')

        Returns:
            True if the control is a modifier button, False otherwise
        """
        return control_name in self.modifier_buttons

    def _send_events(self, events: List[Tuple[int, int, int]]):
        """Send events to the virtual input device with optional modifier delay

        If the batch contains a modifier key press (Ctrl/Shift/Alt/Meta) along
        with other events, the modifier is sent first, syned, then the rest of
        the events are sent after a delay. This helps applications recognize
        key combinations.

        The delay used is `max(self.modifier_delay, AUTO_MOUSE_MODIFIER_DELAY_MS)`
        when the batch mixes a modifier with a mouse event (REL_* or BTN_LEFT/
        RIGHT/MIDDLE), and `self.modifier_delay` otherwise. The auto-delay
        exists because compositors need a moment to latch a modifier into
        keystate before processing pointer events; without it, things like
        Alt+scroll get delivered as plain scrolls. Pure keyboard combos still
        honor `self.modifier_delay` verbatim (default 0).

        Args:
            events: List of (event_type, event_code, value) tuples
        """
        if not events or not self.controller:
            return

        # Single pass: partition events and detect mouse-mixing.
        modifier_presses = []
        other_events = []
        has_mouse_event = False

        for event in events:
            event_type, event_code, value = event
            if (event_type == e.EV_KEY and
                value == 1 and
                event_code in KEYBOARD_MODIFIER_KEYS):
                modifier_presses.append(event)
            else:
                other_events.append(event)
                if event_type == e.EV_REL:
                    has_mouse_event = True
                elif (event_type == e.EV_KEY and
                      value == 1 and
                      event_code in MOUSE_EVENT_KEYS):
                    has_mouse_event = True

        # Compute the delay to use for this batch. Mouse+modifier combos get
        # the auto floor; everything else just uses the configured value.
        effective_delay = self.modifier_delay
        if modifier_presses and has_mouse_event:
            effective_delay = max(effective_delay, AUTO_MOUSE_MODIFIER_DELAY_MS)

        # If we have both modifiers and other events and a non-zero delay,
        # send the modifier first, wait, then send the rest.
        if effective_delay > 0 and modifier_presses and other_events:
            for event in modifier_presses:
                self.controller.write(*event)
            self.controller.syn()

            time.sleep(effective_delay / 1000.0)

            for event in other_events:
                self.controller.write(*event)
            self.controller.syn()
            return

        # No delay needed - send all events normally
        for event in events:
            self.controller.write(*event)
        self.controller.syn()

    def _release_previous_buttons(self, new_button: str):
        """Release any previously held buttons (last-wins behavior)

        When a new button is pressed, release keyboard events from any
        previously held buttons to prevent modifier stacking.

        Args:
            new_button: The button being pressed (don't release this one)
        """
        for button_name, events in list(self.active_button_events.items()):
            if button_name == new_button:
                continue

            # Send release events for each press event that was sent
            for event_type, event_code, value in events:
                if event_type == e.EV_KEY and value == 1:
                    self.controller.write(event_type, event_code, 0)
            self.controller.syn()

            del self.active_button_events[button_name]
            logger.debug(f"Last-wins: released {button_name}")

    def get_control_name_from_code(self, data_bytes: bytes) -> Optional[Tuple[str, bool]]:
        """Get control name and press/release state from button code

        Args:
            data_bytes: Raw button data from device (single byte)

        Returns:
            Tuple of (control_name, is_press) or None if not found
        """
        for control_name, codes in BUTTON_CODES.items():
            if len(codes) >= 2:
                press_code, release_code = codes[0], codes[1]
                if data_bytes == bytes([press_code]):
                    return (control_name, True)
                elif data_bytes == bytes([release_code]):
                    return (control_name, False)
        return None

    def get_modified_action(self, control_name: str) -> Optional[List]:
        """Get modified action if a modifier is currently active

        Args:
            control_name: Name of the control being actuated

        Returns:
            List of action events if a modifier combo exists, None otherwise
        """
        # Check if any modifier is active
        if not self.active_modifiers:
            return None

        # For now, we only support single modifiers (not multiple simultaneous)
        # Take the first (and only) active modifier
        if len(self.active_modifiers) == 1:
            modifier_name = next(iter(self.active_modifiers))

            # Check if there's a combo mapping for this modifier + control
            combo_key = (modifier_name, control_name)
            if combo_key in self.modifier_mappings:
                return self.modifier_mappings[combo_key]

        return None

    def has_double_press_action(self, control_name: str) -> bool:
        """Check if a control has a double-press action configured

        Args:
            control_name: Name of the control (e.g., 'top', 'side')

        Returns:
            True if the control has a double-press action configured
        """
        if not self.current_profile:
            return False
        return control_name in self.current_profile.double_press_actions

    def get_double_press_events(self, control_name: str) -> Optional[List]:
        """Get the parsed events for a double-press action

        Args:
            control_name: Name of the control

        Returns:
            List of action events for double-press, or None if not configured
        """
        if not self.current_profile:
            return None
        action_str = self.current_profile.double_press_actions.get(control_name)
        if action_str:
            return parse_action(action_str)
        return None

    def _cancel_double_click_timers(self):
        """Clear double-click detection state"""
        self._double_click_first_press.clear()
        self._double_click_active_events.clear()

    def process_button_code(self, data: bytearray):
        """Process button/dial data from TourBox Elite

        Each notification is a single byte containing button press/release
        or dial rotation data. Maps to Linux input events via MAPPING dict.

        Implements modifier button logic:
        - Tracks modifier button state (pressed/released)
        - Executes modifier base actions if configured
        - Routes to combo actions when modifier is held

        Implements double-click detection:
        - If button has double-press action, delays single-press execution
        - Detects second press within timeout window

        Args:
            data: Raw button data (single byte as bytearray)
        """
        self.button_count += 1

        # Convert bytearray to bytes for dict lookup
        data_bytes = bytes(data)

        # Step 0: Handle double-click detection (before other processing)
        # This intercepts buttons with double-press configured
        control_info = self.get_control_name_from_code(data_bytes)

        if control_info:
            control_name, is_press = control_info

            # Skip rotary controls - they can't have double-click
            is_rotary = control_name in ('scroll_up', 'scroll_down', 'knob_cw', 'knob_ccw', 'dial_cw', 'dial_ccw')

            # Skip on_release controls - they handle double-press differently (in Step 4)
            is_on_release = self.current_profile and control_name in self.current_profile.on_release_controls

            # Skip if there's an active modifier with a combo for this button - let Step 3 handle it
            has_active_combo = self.active_modifiers and self.get_modified_action(control_name)

            if not is_rotary and not is_on_release and not has_active_combo and self.has_double_press_action(control_name):
                if is_press:
                    # IMMEDIATE FIRE: Check if this is second press (double-press detection)
                    if control_name in self._double_click_first_press:
                        elapsed_ms = (time.time() - self._double_click_first_press[control_name]) * 1000
                        if elapsed_ms < self.current_profile.double_click_timeout:
                            # Double-press detected! Fire double-press action
                            del self._double_click_first_press[control_name]
                            double_events = self.get_double_press_events(control_name)
                            if double_events:
                                logger.info(f"Double-press detected: {control_name} ({elapsed_ms:.0f}ms)")

                                # Last-wins: release other buttons first
                                if control_name in HOLDABLE_BUTTONS:
                                    self._release_previous_buttons(control_name)
                                    press_events = [(t, c, v) for t, c, v in double_events
                                                   if t == e.EV_KEY and v == 1]
                                    if press_events:
                                        self.active_button_events[control_name] = press_events

                                # Track for release handling
                                self._double_click_active_events[control_name] = double_events

                                self._send_events(double_events)
                            return
                        else:
                            # Too slow - treat as new first press
                            del self._double_click_first_press[control_name]

                    # First press (or new first press after timeout) - track timestamp
                    # IMMEDIATE FIRE: Execute base action right now (no deferral)
                    self._double_click_first_press[control_name] = time.time()
                    logger.debug(f"Double-press tracking started for {control_name}")

                    # Fire base action immediately - bypass modifier deferral logic
                    if self.is_modifier_button(control_name):
                        # It's a modifier button with double-press
                        self.active_modifiers.add(control_name)
                        if control_name in self.modifier_base_actions:
                            base_events = self.modifier_base_actions[control_name]
                            # Fire immediately (no deferral for combos)
                            press_events = [(t, c, v) for t, c, v in base_events if v == 1]
                            self._send_events(press_events)
                            self.base_action_active.add(control_name)
                            logger.info(f"Immediate fire: modifier {control_name} base action PRESSED")
                        else:
                            logger.info(f"Immediate fire: modifier {control_name} (no base action)")
                    else:
                        # Regular button with double-press
                        base_events = self.mapping.get(data_bytes, [])
                        if base_events:
                            # Last-wins: release other buttons first
                            if control_name in HOLDABLE_BUTTONS:
                                self._release_previous_buttons(control_name)
                                press_events = [(t, c, v) for t, c, v in base_events
                                               if t == e.EV_KEY and v == 1]
                                if press_events:
                                    self.active_button_events[control_name] = press_events

                            # Fire the base action
                            self._send_events(base_events)
                            logger.info(f"Immediate fire: {control_name} base action fired")
                    return  # Don't fall through - we handled the press
                else:
                    # Release event for button with double-press
                    # NOTE: Do NOT clear first-press timestamp here!
                    # We need it to persist so second press can detect double-press.
                    # It gets cleared when: double-press fires, or next press is too late.

                    # Check if this is releasing an active double-press action
                    if control_name in self._double_click_active_events:
                        # Release the double-press action keys
                        double_events = self._double_click_active_events.pop(control_name)
                        release_events = []
                        for event_type, event_code, value in double_events:
                            if event_type == e.EV_KEY and value == 1:
                                release_events.append((event_type, event_code, 0))

                        if release_events:
                            logger.info(f"Double-press release: {control_name}")
                            for event in release_events:
                                self.controller.write(*event)
                            self.controller.syn()

                        # Also clear from active_button_events
                        self.active_button_events.pop(control_name, None)
                        return

                    # For normal release, fall through to Step 4 to release base action

        # Step 1: Identify control name and press/release state
        # (already done above, reuse control_info)

        # Step 2: Check if this is a modifier button event
        if control_info:
            control_name, is_press = control_info

            if self.is_modifier_button(control_name):
                # Check for second press of on_release modifier double-press (immediate fire)
                is_on_release_modifier = (self.current_profile and
                                          control_name in self.current_profile.on_release_controls)
                if is_press and is_on_release_modifier and control_name in self._double_click_first_press:
                    elapsed_ms = (time.time() - self._double_click_first_press[control_name]) * 1000
                    if elapsed_ms < self.current_profile.double_click_timeout:
                        # Second press within timeout - fire double action as tap
                        del self._double_click_first_press[control_name]
                        dp_events = self.get_double_press_events(control_name)
                        if dp_events:
                            logger.info(f"Modifier {control_name} on_release: double-press detected ({elapsed_ms:.0f}ms)")
                            # Fire as tap (press + release)
                            self._send_events(dp_events)
                            for event_type, event_code, value in dp_events:
                                if event_type == e.EV_KEY and value == 1:
                                    self.controller.write(event_type, event_code, 0)
                            self.controller.syn()
                        # Still track as modifier for potential combos
                        self.active_modifiers.add(control_name)
                        return
                    else:
                        # Too slow - clear timestamp, treat as new first press
                        del self._double_click_first_press[control_name]

                # This is a modifier button - but check if it should trigger a combo first
                # (e.g., Tour is active, Side is pressed, and tour.side combo exists)
                if is_press and self.active_modifiers:
                    # Check if any active modifier has a combo for this button
                    modified_action = self.get_modified_action(control_name)
                    if modified_action:
                        # This modifier triggers a combo with an already-active modifier
                        # Don't treat it as a new modifier - fall through to Step 3
                        logger.info(f"Modifier {control_name} triggers combo with {self.active_modifiers}")
                        # Don't return - let Step 3 handle the combo
                    else:
                        # No combo with existing modifiers - handle as normal modifier
                        self.active_modifiers.add(control_name)
                        logger.info(f"Modifier {control_name} PRESSED, active: {self.active_modifiers}")

                        # Execute base action press if configured
                        if control_name in self.modifier_base_actions:
                            events = self.modifier_base_actions[control_name]

                            # Check if this modifier has on_release enabled - defer until release
                            if self.current_profile and control_name in self.current_profile.on_release_controls:
                                self._on_release_modifier_pending[control_name] = events
                                logger.info(f"Modifier {control_name} base action DEFERRED (on_release enabled)")
                            else:
                                # Immediate fire - base action fires on press (combos release it if triggered)
                                press_events = [(t, c, v) for t, c, v in events if v == 1]
                                self._send_events(press_events)
                                self.base_action_active.add(control_name)
                                logger.info(f"Modifier {control_name} base action PRESSED")
                        else:
                            logger.info(f"Modifier {control_name} - no base action, tracking state only")
                        return
                elif is_press:
                    # No active modifiers - handle as normal modifier
                    self.active_modifiers.add(control_name)
                    logger.info(f"Modifier {control_name} PRESSED, active: {self.active_modifiers}")

                    # Execute base action press if configured
                    if control_name in self.modifier_base_actions:
                        events = self.modifier_base_actions[control_name]

                        # Check if this modifier has on_release enabled - defer until release
                        if self.current_profile and control_name in self.current_profile.on_release_controls:
                            self._on_release_modifier_pending[control_name] = events
                            logger.info(f"Modifier {control_name} base action DEFERRED (on_release enabled)")
                        else:
                            # Immediate fire - base action fires on press (combos release it if triggered)
                            press_events = [(t, c, v) for t, c, v in events if v == 1]
                            self._send_events(press_events)
                            self.base_action_active.add(control_name)
                            logger.info(f"Modifier {control_name} base action PRESSED")
                    else:
                        logger.info(f"Modifier {control_name} - no base action, tracking state only")
                    return
                else:
                    # Modifier released - only handle if it was tracked as a modifier
                    # (not if it was used as a combo target)
                    if control_name in self.active_modifiers:
                        self.active_modifiers.discard(control_name)
                        logger.info(f"Modifier {control_name} RELEASED, active: {self.active_modifiers}")

                        # Check if this is an on_release modifier - fire base action as tap if no combo used
                        if control_name in self._on_release_modifier_pending:
                            events = self._on_release_modifier_pending.pop(control_name)
                            # Only fire if no combo was used
                            if control_name not in self.combo_used:
                                # Fire base action immediately as tap (immediate fire for on_release)
                                self._send_events(events)
                                # Immediately send release events
                                for event_type, event_code, value in events:
                                    if event_type == e.EV_KEY and value == 1:
                                        self.controller.write(event_type, event_code, 0)
                                self.controller.syn()

                                # Check if control has double-press action configured - track for detection
                                dp_action = self.current_profile.double_press_actions.get(control_name, "") if self.current_profile else ""
                                if dp_action:
                                    # Track timestamp for double-press detection on next press
                                    self._double_click_first_press[control_name] = time.time()
                                    logger.info(f"Modifier {control_name} on_release: fired base action as tap, tracking for double-press")
                                else:
                                    logger.info(f"Modifier {control_name} on_release: fired base action as tap")
                            else:
                                logger.info(f"Modifier {control_name} on_release: combo was used, skipping base action")
                            # Reset combo usage tracking
                            self.combo_used.discard(control_name)
                            return

                        # Release base action if it's still active (wasn't released by combo)
                        if control_name in self.base_action_active:
                            events = self.modifier_base_actions[control_name]
                            # Send release events
                            for event_type, event_code, value in events:
                                if value == 1:  # Was a press event, send release
                                    self.controller.write(event_type, event_code, 0)
                            self.controller.syn()
                            self.base_action_active.discard(control_name)
                            logger.info(f"Modifier {control_name} base action RELEASED")

                        # Reset combo usage tracking
                        self.combo_used.discard(control_name)
                        return
                    # If not in active_modifiers, it was a combo target - fall through to Step 3

        # Step 3: Check for modified action (combo)
        if control_info:
            control_name, is_press = control_info

            # Check for pending on_release combo (fire as tap on release)
            if not is_press and control_name in self._on_release_combo_pending:
                modifier_name, combo_events = self._on_release_combo_pending.pop(control_name)
                # Fire combo as tap (press + release)
                # Send press events
                self._send_events(combo_events)
                # Immediately send release events
                for event_type, event_code, value in combo_events:
                    if event_type == e.EV_KEY and value == 1:
                        self.controller.write(event_type, event_code, 0)
                self.controller.syn()
                logger.info(f"On-release combo: fired {modifier_name}.{control_name} as tap")
                return

            # Check for active combo first (for release when modifier is already released)
            if not is_press and control_name in self.active_combo_events:
                # Use tracked events for release
                tracked_events = self.active_combo_events.pop(control_name)
                events_to_send = []
                for event_type, event_code, value in tracked_events:
                    if event_type == e.EV_KEY and value == 1:
                        events_to_send.append((event_type, event_code, 0))
                    else:
                        events_to_send.append((event_type, event_code, value))

                # Log and send
                event_desc = []
                for event_type, event_code, value in events_to_send:
                    if event_type == e.EV_KEY:
                        key_name = next((k for k, v in e.__dict__.items() if (k.startswith('KEY_') or k.startswith('BTN_')) and v == event_code), f"CODE_{event_code}")
                        action = "PRESS" if value == 1 else "RELEASE" if value == 0 else f"VAL={value}"
                        event_desc.append(f"{key_name}:{action}")
                logger.info(f"Combo release (tracked): {control_name} -> {', '.join(event_desc)}")

                for event in events_to_send:
                    self.controller.write(*event)
                self.controller.syn()
                return

            modified_action = self.get_modified_action(control_name)

            if modified_action:
                # Execute combo action instead of normal action
                modifier_name = next(iter(self.active_modifiers))

                if is_press:
                    # Check if this is an on_release control - defer combo until release
                    if self.current_profile and control_name in self.current_profile.on_release_controls:
                        # Store combo for later execution on release
                        self._on_release_combo_pending[control_name] = (modifier_name, modified_action)
                        # Clear double-press tracking and release base action if active
                        self._double_click_first_press.pop(modifier_name, None)
                        if modifier_name in self.base_action_active:
                            base_events = self.modifier_base_actions[modifier_name]
                            for event_type, event_code, value in base_events:
                                if value == 1:
                                    self.controller.write(event_type, event_code, 0)
                            self.controller.syn()
                            self.base_action_active.discard(modifier_name)
                        self.combo_used.add(modifier_name)
                        logger.info(f"On-release combo: deferred {modifier_name}.{control_name}")
                        return

                    # Combo button pressed - clear double-press tracking for modifier
                    self._double_click_first_press.pop(modifier_name, None)

                    # Combo button pressed - release base action if already active
                    if modifier_name in self.base_action_active:
                        # Release the base action first
                        base_events = self.modifier_base_actions[modifier_name]
                        for event_type, event_code, value in base_events:
                            if value == 1:  # Was a press, send release
                                self.controller.write(event_type, event_code, 0)
                        self.controller.syn()
                        self.base_action_active.discard(modifier_name)
                        logger.info(f"Cancelled base action for {modifier_name} (combo triggered)")

                    # Mark that combo was used
                    self.combo_used.add(modifier_name)

                    # Track combo events for release (in case modifier is released first)
                    self.active_combo_events[control_name] = modified_action

                    # Send combo press
                    events_to_send = modified_action
                else:
                    # Combo button released - send combo release
                    # Also remove from tracking
                    self.active_combo_events.pop(control_name, None)
                    events_to_send = []
                    for event_type, event_code, value in modified_action:
                        if event_type == e.EV_KEY and value == 1:
                            # Convert press to release
                            events_to_send.append((event_type, event_code, 0))
                        else:
                            # Keep other events as-is
                            events_to_send.append((event_type, event_code, value))

                # Log the actual events being sent
                event_desc = []
                for event_type, event_code, value in events_to_send:
                    if event_type == e.EV_KEY:
                        key_name = next((k for k, v in e.__dict__.items() if (k.startswith('KEY_') or k.startswith('BTN_')) and v == event_code), f"CODE_{event_code}")
                        action = "PRESS" if value == 1 else "RELEASE" if value == 0 else f"VAL={value}"
                        event_desc.append(f"{key_name}:{action}")
                logger.info(f"Combo: {modifier_name}.{control_name} -> {', '.join(event_desc)}")

                self._send_events(events_to_send)
                return

        # Step 4: Execute normal action (no modifier or no combo mapping)
        if data_bytes:
            mapping = self.mapping.get(data_bytes, [])
            if mapping:
                # Check for on_release controls - defer action until release
                if control_info and self.current_profile:
                    control_name, is_press = control_info
                    if control_name in self.current_profile.on_release_controls:
                        if is_press:
                            # Check if this is a second press (double-press detection with immediate fire)
                            if control_name in self._double_click_first_press:
                                elapsed_ms = (time.time() - self._double_click_first_press[control_name]) * 1000
                                if elapsed_ms < self.current_profile.double_click_timeout:
                                    # Second press within timeout - fire double action as tap
                                    del self._double_click_first_press[control_name]
                                    double_events = self.get_double_press_events(control_name)
                                    if double_events:
                                        logger.info(f"On-release double-press detected: {control_name} ({elapsed_ms:.0f}ms)")
                                        # Fire double action as tap
                                        self._send_events(double_events)
                                        # Immediately send release events
                                        release_events = [(t, c, 0) for t, c, v in double_events
                                                         if t == e.EV_KEY and v == 1]
                                        if release_events:
                                            for event in release_events:
                                                self.controller.write(*event)
                                            self.controller.syn()
                                    return
                                else:
                                    # Too slow - clear timestamp, treat as new first press
                                    del self._double_click_first_press[control_name]

                            # First press - store events for later (both KEY and REL events)
                            press_events = [(t, c, v) for t, c, v in mapping
                                           if (t == e.EV_KEY and v == 1) or t == e.EV_REL]
                            if press_events:
                                self._on_release_pending[control_name] = press_events
                                logger.info(f"On-release: deferred {control_name} press")
                            return  # Don't execute action yet
                        else:
                            # Release - check if has double_press configured
                            if control_name in self._on_release_pending:
                                pending_events = self._on_release_pending.pop(control_name)

                                # Fire tap immediately (immediate fire for on_release)
                                # Build press events (KEY events get press value, REL events use stored value)
                                press_events = []
                                for event_type, event_code, value in pending_events:
                                    if event_type == e.EV_KEY:
                                        press_events.append((event_type, event_code, 1))
                                    elif event_type == e.EV_REL:
                                        press_events.append((event_type, event_code, value))
                                self._send_events(press_events)
                                # Immediately send release events (only for KEY events, not REL)
                                for event_type, event_code, value in pending_events:
                                    if event_type == e.EV_KEY:
                                        self.controller.write(event_type, event_code, 0)
                                self.controller.syn()

                                # Check if this control has double-press configured - track for detection
                                if self.has_double_press_action(control_name):
                                    self._double_click_first_press[control_name] = time.time()
                                    logger.info(f"On-release: fired {control_name} as tap, tracking for double-press")
                                else:
                                    logger.info(f"On-release: fired {control_name} as tap")
                                return
                            # No pending events, nothing to do
                            return

                # Last-wins behavior: release previously held buttons when a new one is pressed
                if control_info and control_info[0] in HOLDABLE_BUTTONS:
                    control_name, is_press = control_info

                    if is_press:
                        # Release any other held buttons first
                        self._release_previous_buttons(control_name)

                        # Track this button's press events for later release
                        press_events = [(t, c, v) for t, c, v in mapping
                                       if t == e.EV_KEY and v == 1]
                        if press_events:
                            self.active_button_events[control_name] = press_events
                    else:
                        # Button released - stop tracking it
                        self.active_button_events.pop(control_name, None)

                # Log the actual events being sent
                event_desc = []
                for event_type, event_code, value in mapping:
                    if event_type == e.EV_KEY:
                        key_name = next((k for k, v in e.__dict__.items() if (k.startswith('KEY_') or k.startswith('BTN_')) and v == event_code), f"CODE_{event_code}")
                        action = "PRESS" if value == 1 else "RELEASE" if value == 0 else f"VAL={value}"
                        event_desc.append(f"{key_name}:{action}")
                    elif event_type == e.EV_REL:
                        rel_name = next((k for k, v in e.__dict__.items() if k.startswith('REL_') and v == event_code), f"REL_{event_code}")
                        event_desc.append(f"{rel_name}:{value}")
                logger.info(f"{data_bytes.hex()} -> {', '.join(event_desc)}")

                # Send input events to virtual device
                self._send_events(mapping)
            elif control_info:
                # Recognized control, just not bound in the active profile.
                # Normal for a partially-configured profile, so this is debug
                # rather than a warning (see #53).
                control_name, is_press = control_info
                profile_name = self.current_profile.name if self.current_profile else "none"
                action = "press" if is_press else "release"
                logger.debug(
                    f"No binding for {control_name} ({action}) in profile "
                    f"'{profile_name}' [{data_bytes.hex()}]"
                )
            else:
                logger.warning(f"Unknown button code: {data_bytes.hex()}")

    def switch_profile(self, profile):
        """Switch to a different profile

        Updates the active mapping and recreates the virtual input device
        with the new capabilities if needed.

        Args:
            profile: Profile object to switch to
        """
        if profile == self.current_profile:
            return

        self.current_profile = profile
        self.mapping = profile.mapping

        # Load modifier configuration
        self.modifier_buttons = profile.modifier_buttons
        self.active_modifiers.clear()  # Clear modifier state when switching
        self.base_action_active.clear()  # Clear base action state
        self.combo_used.clear()  # Clear combo usage tracking
        self.active_button_events.clear()  # Clear last-wins button tracking
        self.active_combo_events.clear()  # Clear active combo tracking
        self._on_release_pending.clear()  # Clear on-release pending state
        self._on_release_combo_pending.clear()  # Clear on-release combo pending state
        self._on_release_modifier_pending.clear()  # Clear on-release modifier pending state
        self._cancel_double_click_timers()  # Cancel any pending double-click timers

        # Convert modifier mappings from action strings to events
        self.modifier_mappings = {}
        logger.info(f"Converting {len(profile.modifier_mappings)} modifier mappings from strings to events")
        for (modifier, control), action_str in profile.modifier_mappings.items():
            events = parse_action(action_str)
            logger.info(f"  Parsing combo {modifier}.{control} = '{action_str}' -> {events}")
            # For rotary controls, add press+release cycle
            if control in ('scroll_up', 'scroll_down', 'knob_cw', 'knob_ccw', 'dial_cw', 'dial_ccw'):
                # Create release events
                release_events = []
                for event_type, event_code, value in events:
                    if event_type == e.EV_KEY:
                        release_events.append((event_type, event_code, 0))
                self.modifier_mappings[(modifier, control)] = events + release_events
            else:
                self.modifier_mappings[(modifier, control)] = events
            # Log the final stored events with key names
            for event_type, event_code, value in self.modifier_mappings[(modifier, control)]:
                if event_type == e.EV_KEY:
                    key_name = next((k for k, v in e.__dict__.items() if (k.startswith('KEY_') or k.startswith('BTN_')) and v == event_code), f"CODE_{event_code}")
                    logger.info(f"  Event: {key_name} (code={event_code}) value={value}")

        # Convert base actions from action strings to events
        self.modifier_base_actions = {}
        for modifier, action_str in profile.modifier_base_actions.items():
            self.modifier_base_actions[modifier] = parse_action(action_str)

        # Resolve per-profile modifier_delay (profile value > global > 0)
        if profile.modifier_delay is not None:
            self.modifier_delay = profile.modifier_delay
            logger.info(f"  Per-profile modifier_delay: {self.modifier_delay}ms")
        else:
            self.modifier_delay = self._global_modifier_delay

        # Print profile switch to console
        print(f"\nSwitched to profile: {profile.name}")
        logger.info(f"Switched to profile: {profile.name}")
        if self.modifier_buttons:
            logger.info(f"  Modifiers active: {', '.join(self.modifier_buttons)}")

        # Check if capabilities changed
        if profile.capabilities != self.capabilities:
            logger.info("Profile has different capabilities - recreating virtual input device")
            self.capabilities = profile.capabilities

            # Close old controller if exists
            if self.controller:
                self.controller.close()

            # Create new controller with updated capabilities
            self.controller = UInput(
                self.capabilities,
                name=self.device_name,
                vendor=0xC251,
                product=0x2005
            )
            dev_path = self.controller.device.path if self.controller.device else "unknown"
            logger.debug(f"Virtual input device recreated: {dev_path}")

    def reload_config_mappings(self):
        """Reload configuration from file and update mappings

        Called when SIGHUP is received. Reloads the config file and updates
        the current profile's mappings without restarting the driver.
        """
        print("\nReloading configuration...")
        logger.info("Reloading configuration from file")

        try:
            # Remember current profile name
            current_profile_name = self.current_profile.name if self.current_profile else 'default'

            # Reload device config first: ctrl_key affects how profiles parse
            device_config = load_device_config(self.config_path)
            set_ctrl_key(device_config.get('ctrl_key', DEFAULT_CTRL_KEY))

            # Reload profiles from config
            new_profiles = load_profiles(self.config_path)

            if not new_profiles:
                logger.error("Failed to reload config - no profiles found")
                print("Failed to reload: No profiles found in config")
                return

            self.profiles = new_profiles
            logger.info(f"Reloaded {len(self.profiles)} profiles")

            # Reload global modifier_delay from device config
            self._global_modifier_delay = device_config.get('modifier_delay', 0)

            # Find the current profile in the new profiles
            new_current_profile = next((p for p in self.profiles if p.name == current_profile_name), None)

            if not new_current_profile:
                # Current profile no longer exists, fall back to default or first profile
                logger.warning(f"Profile '{current_profile_name}' not found after reload")
                new_current_profile = next((p for p in self.profiles if p.name == 'default'), self.profiles[0])
                print(f"Profile '{current_profile_name}' not found, using '{new_current_profile.name}'")

            # Update current profile and mapping
            self.current_profile = new_current_profile
            self.mapping = new_current_profile.mapping

            # Reload modifier configuration
            self.modifier_buttons = new_current_profile.modifier_buttons
            self.active_modifiers.clear()  # Clear modifier state on reload

            # Convert modifier mappings from action strings to events
            self.modifier_mappings = {}
            for (modifier, control), action_str in new_current_profile.modifier_mappings.items():
                events = parse_action(action_str)
                # For rotary controls, add press+release cycle
                if control in ('scroll_up', 'scroll_down', 'knob_cw', 'knob_ccw', 'dial_cw', 'dial_ccw'):
                    release_events = []
                    for event_type, event_code, value in events:
                        if event_type == e.EV_KEY:
                            release_events.append((event_type, event_code, 0))
                    self.modifier_mappings[(modifier, control)] = events + release_events
                else:
                    self.modifier_mappings[(modifier, control)] = events

            # Convert base actions from action strings to events
            self.modifier_base_actions = {}
            for modifier, action_str in new_current_profile.modifier_base_actions.items():
                self.modifier_base_actions[modifier] = parse_action(action_str)

            # Resolve per-profile modifier_delay (profile value > global > 0)
            if new_current_profile.modifier_delay is not None:
                self.modifier_delay = new_current_profile.modifier_delay
                logger.info(f"Per-profile modifier_delay: {self.modifier_delay}ms")
            else:
                self.modifier_delay = self._global_modifier_delay

            # Check if capabilities changed
            if new_current_profile.capabilities != self.capabilities:
                logger.info("Capabilities changed - recreating virtual input device")
                self.capabilities = new_current_profile.capabilities

                # Close old controller
                if self.controller:
                    self.controller.close()

                # Create new controller with updated capabilities
                self.controller = UInput(
                    self.capabilities,
                    name=self.device_name,
                    vendor=0xC251,
                    product=0x2005
                )
                dev_path = self.controller.device.path if self.controller.device else "unknown"
                logger.debug(f"Virtual input device recreated: {dev_path}")

            print(f"Configuration reloaded successfully - using profile: {self.current_profile.name}")
            if self.modifier_buttons:
                print(f"   Modifiers active: {', '.join(self.modifier_buttons)}")
            logger.info(f"Configuration reload complete - active profile: {self.current_profile.name}")

        except Exception as ex:
            logger.error(f"Error reloading config: {ex}", exc_info=True)
            print(f"Error reloading config: {ex}")

    async def send_haptic_config(self):
        """Send haptic configuration to device

        Override in subclasses (BLE, USB) to send the current profile's
        haptic settings to the device. Called when profile switches.

        This is a no-op in the base class - subclasses implement the
        transport-specific logic.
        """
        pass

    async def on_window_change(self, window_info):
        """Handle window focus changes

        Args:
            window_info: WindowInfo object with current window details
        """
        old_profile = self.current_profile

        # Find matching profile
        for profile in self.profiles:
            if profile.matches(window_info):
                if profile != self.current_profile:
                    self.switch_profile(profile)
                break
        else:
            # No match - switch to default profile
            default_profile = next((p for p in self.profiles if p.name == 'default'), None)
            if default_profile and default_profile != self.current_profile:
                self.switch_profile(default_profile)

        # Send haptic config if profile changed
        if self.current_profile != old_profile:
            await self.send_haptic_config()

    def clear_modifier_state(self):
        """Clear all modifier state - call on disconnect to prevent stuck keys"""
        self.active_modifiers.clear()
        self.base_action_active.clear()
        self.combo_used.clear()
        self.active_button_events.clear()  # Clear last-wins button tracking
        self.active_combo_events.clear()  # Clear active combo tracking
        self._cancel_double_click_timers()  # Cancel any pending double-click timers

    def create_virtual_device(self):
        """Create the virtual input device (uinput)

        Should be called after loading profiles and setting capabilities.
        """
        logger.info("Creating virtual input device...")
        self.controller = UInput(
            self.capabilities,
            name=self.device_name,
            vendor=0xC251,
            product=0x2005
        )
        logger.info("Virtual input device created")

    def cleanup(self):
        """Clean up resources - close virtual device"""
        if self.controller:
            self.controller.close()
            self.controller = None

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to the TourBox device

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    async def disconnect(self):
        """Disconnect from the TourBox device"""
        pass

    @abstractmethod
    async def run_connection(self) -> bool:
        """Run a single connection session

        Returns:
            True if should retry connection, False if user requested exit
        """
        pass
