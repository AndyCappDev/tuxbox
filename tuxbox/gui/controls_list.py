#!/usr/bin/env python3
"""Controls list widget

Displays all TourBox controls and their current mappings.
"""

import logging
from typing import Optional, Dict
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel
)
from PySide6.QtCore import Signal, Qt
from evdev import ecodes as e

# Import from existing driver code
from tuxbox.config_loader import Profile, BUTTON_CODES

from tuxbox.gui.ui_constants import TABLE_ROW_HEIGHT_MULTIPLIER
from tuxbox.gui.keymap_util import get_system_display_hints
from .controller_models import ELITE_CONTROLS, get_model_controls

logger = logging.getLogger(__name__)


# All control names in display order
CONTROL_NAMES = ELITE_CONTROLS

# Friendly names for display
CONTROL_DISPLAY_NAMES = {
    'side': 'Side Button',
    'top': 'Top Button',
    'tall': 'Tall Button',
    'short': 'Short Button',
    'c1': 'C1 Button',
    'c2': 'C2 Button',
    'tour': 'Tour Button',
    'dpad_up': 'D-Pad Up',
    'dpad_down': 'D-Pad Down',
    'dpad_left': 'D-Pad Left',
    'dpad_right': 'D-Pad Right',
    'scroll_up': 'Scroll Up',
    'scroll_down': 'Scroll Down',
    'scroll_click': 'Scroll Click',
    'knob_cw': 'Knob Clockwise',
    'knob_ccw': 'Knob Counter-CW',
    'knob_click': 'Knob Click',
    'dial_cw': 'Dial Clockwise',
    'dial_ccw': 'Dial Counter-CW',
    'dial_click': 'Dial Click',
}


class ControlsList(QWidget):
    """Widget displaying all controls and their current actions"""

    # Signal emitted when user clicks a control to edit it
    control_selected = Signal(str)  # control name

    def __init__(self, parent=None, model: str = 'elite'):
        super().__init__(parent)
        self._model = model
        self.current_profile: Optional[Profile] = None
        self._init_ui()

    def set_model(self, model: str):
        """Filter rows without discarding displayed edits or profile mappings."""
        self._model = model
        available = get_model_controls(model)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                self.table.setRowHidden(row, item.data(Qt.UserRole) not in available)

        current = self.table.currentRow()
        if current < 0 or self.table.isRowHidden(current):
            self.table.clearSelection()
            for row in range(self.table.rowCount()):
                if not self.table.isRowHidden(row):
                    self.table.selectRow(row)
                    break

    def _init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("Controls Configuration")
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(header)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Control", "Current Action", "Comment"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)  # Hide row numbers
        # Set row height based on font metrics for proper scaling
        fm = self.table.fontMetrics()
        row_height = int(fm.lineSpacing() * TABLE_ROW_HEIGHT_MULTIPLIER)
        self.table.verticalHeader().setDefaultSectionSize(row_height)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        # Set minimum height to match Modifier Combinations table (5 rows + header)
        header_height = self.table.horizontalHeader().height()
        if header_height < 20:
            header_height = int(fm.lineSpacing() * 1.5)
        min_table_height = row_height * 5 + header_height + 4
        self.table.setMinimumHeight(min_table_height)

        layout.addWidget(self.table)

        # Initial empty state
        self._show_empty_state()

    def load_profile(self, profile: Profile):
        """Load and display controls from a profile

        Args:
            profile: Profile object containing button mappings
        """
        self.current_profile = profile

        # Clear table completely first
        self.table.clearContents()
        self.table.clearSpans()  # Clear any cell spans from empty state
        self.table.setRowCount(0)

        # Now set the row count
        self.table.setRowCount(len(CONTROL_NAMES))

        for row, control_name in enumerate(CONTROL_NAMES):
            # Control name column
            name_item = QTableWidgetItem(CONTROL_DISPLAY_NAMES.get(control_name, control_name))
            name_item.setData(Qt.UserRole, control_name)  # Store internal name
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            name_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.table.setItem(row, 0, name_item)

            # Current action column
            action_text = self._get_action_text(profile, control_name)

            # Debug logging
            if not action_text or action_text.isspace():
                logger.warning(f"Empty action text for {control_name}, using '(unmapped)'")
                action_text = "(unmapped)"

            logger.debug(f"Control {control_name}: '{action_text}'")

            action_item = QTableWidgetItem(action_text)
            action_item.setFlags(action_item.flags() & ~Qt.ItemIsEditable)
            action_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.table.setItem(row, 1, action_item)

            # Comment column
            comment_text = profile.mapping_comments.get(control_name, "")
            comment_item = QTableWidgetItem(comment_text)
            comment_item.setFlags(comment_item.flags() & ~Qt.ItemIsEditable)
            comment_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.table.setItem(row, 2, comment_item)

            # Verify it was set
            verify_item = self.table.item(row, 1)
            logger.debug(f"  Verified table item at row {row}: {verify_item.text() if verify_item else 'None'}")

            # Check row height
            row_height = self.table.rowHeight(row)
            logger.debug(f"  Row {row} height: {row_height}")

        # Force table to update/repaint
        self.table.viewport().update()
        # Don't call resizeColumnsToContents() - it overrides the stretch mode set in _init_ui
        # Column 0 is already set to ResizeToContents, column 1 to Stretch

        # Scroll to top of the list
        self.table.scrollToTop()

        # Filter before selecting so Lite never opens on an absent Side button.
        self.set_model(self._model)

        logger.info(f"Loaded {len(get_model_controls(self._model))} controls for profile: {profile.name}")

    def _get_action_text(self, profile: Profile, control_name: str) -> str:
        """Get human-readable action text for a control

        Args:
            profile: Profile containing mappings
            control_name: Name of the control

        Returns:
            Human-readable action description
        """
        display_hints = get_system_display_hints()

        try:
            # First check if this control is a modifier button
            if control_name in profile.modifier_buttons:
                # It's a modifier - show base action if configured
                if control_name in profile.modifier_base_actions:
                    # Parse base action to get readable text
                    base_action = profile.modifier_base_actions[control_name]
                    result = self._parse_action_string_to_readable(base_action, display_hints)
                else:
                    # No base action configured
                    result = "(no base action)"

                # Check for double-press action on modifier buttons too
                if control_name in profile.double_press_actions:
                    dp_action = profile.double_press_actions[control_name]
                    dp_readable = self._parse_action_string_to_readable(dp_action, display_hints)
                    result = f"{result} (2×: {dp_readable})"

                return result

            if control_name not in BUTTON_CODES:
                logger.warning(f"Control {control_name} not in BUTTON_CODES")
                return "(unknown)"

            codes = BUTTON_CODES[control_name]
            if len(codes) == 0:
                logger.warning(f"Control {control_name} has no codes")
                return "(unmapped)"

            # Get the press code (first in tuple)
            press_code = bytes([codes[0]])
            logger.debug(f"Control {control_name}: press_code={press_code.hex()}")

            # Look up in profile mapping
            if press_code not in profile.mapping:
                logger.debug(f"Control {control_name}: press_code {press_code.hex()} not in mapping")
                return "(unmapped)"

            events = profile.mapping[press_code]
            logger.debug(f"Control {control_name}: events={events}")

            if not events:
                return "(unmapped)"

            # Convert events to readable text
            parts = []
            rel_event = None  # Track if we have a REL event

            for event_type, event_code, value in events:
                logger.debug(f"  Event: type={event_type}, code={event_code}, value={value}")
                if event_type == e.EV_KEY and value == 1:  # Key press
                    key_name = self._get_key_name(event_code, display_hints)
                    logger.debug(f"    Key name: {key_name}")
                    parts.append(key_name)
                elif event_type == e.EV_REL:  # Relative movement
                    rel_event = (event_code, value)

            # Handle relative events with human-readable names
            if rel_event:
                event_code, value = rel_event
                if event_code == e.REL_WHEEL:
                    rel_readable = f"Scroll {'Up' if value > 0 else 'Down'}"
                elif event_code == e.REL_HWHEEL:
                    rel_readable = f"Scroll {'Right' if value > 0 else 'Left'}"
                else:
                    # Fallback for other REL events
                    rel_name = self._get_rel_name(event_code)
                    rel_readable = f"{rel_name}:{value}"

                # Combine modifiers with mouse action
                if parts:
                    result = "+".join(parts) + "+" + rel_readable
                else:
                    result = rel_readable
            else:
                result = "+".join(parts) if parts else "(unmapped)"

            # Check for double-press action
            if control_name in profile.double_press_actions:
                dp_action = profile.double_press_actions[control_name]
                dp_readable = self._parse_action_string_to_readable(dp_action, display_hints)
                result = f"{result} (2×: {dp_readable})"

            logger.debug(f"Control {control_name}: final result='{result}'")
            return result

        except Exception as ex:
            logger.error(f"Error getting action text for {control_name}: {ex}", exc_info=True)
            return "(error)"

    def _parse_action_string_to_readable(self, action_str: str, display_hints: dict = None) -> str:
        """Parse an action string to human-readable format

        Args:
            action_str: Action string like 'KEY_LEFTCTRL' or 'KEY_LEFTCTRL+KEY_C'
            display_hints: Optional dict of KEY_* name -> display character (locale-aware)

        Returns:
            Readable string like 'Ctrl' or 'Ctrl+C'
        """
        if not action_str or action_str == "none":
            return "(none)"

        # Handle simple REL events (scroll, no modifiers)
        if action_str.startswith("REL_") and "+" not in action_str:
            if "WHEEL:" in action_str:
                value = int(action_str.split(":")[1])
                return f"Scroll {'Up' if value > 0 else 'Down'}"
            elif "HWHEEL:" in action_str:
                value = int(action_str.split(":")[1])
                return f"Scroll {'Right' if value > 0 else 'Left'}"

        # Handle simple mouse button events (no modifiers)
        if action_str == "BTN_LEFT":
            return "Left Click"
        elif action_str == "BTN_RIGHT":
            return "Right Click"
        elif action_str == "BTN_MIDDLE":
            return "Middle Click"

        # Helper to convert mouse action part to readable
        def mouse_part_to_readable(part):
            if part.startswith("REL_WHEEL:"):
                value = int(part.split(":")[1])
                return f"Scroll {'Up' if value > 0 else 'Down'}"
            if part.startswith("REL_HWHEEL:"):
                value = int(part.split(":")[1])
                return f"Scroll {'Right' if value > 0 else 'Left'}"
            if part == "BTN_LEFT":
                return "Left Click"
            if part == "BTN_RIGHT":
                return "Right Click"
            if part == "BTN_MIDDLE":
                return "Middle Click"
            return None

        # Symbol key mapping
        SYMBOL_MAP = {
            'LEFTBRACE': '[',
            'RIGHTBRACE': ']',
            'SEMICOLON': ';',
            'APOSTROPHE': "'",
            'GRAVE': '`',
            'BACKSLASH': '\\',
            'COMMA': ',',
            'DOT': '.',
            'SLASH': '/',
            'MINUS': '-',
            'EQUAL': '=',
        }

        # Parse keyboard combination
        parts = action_str.split("+")
        readable_parts = []

        for part in parts:
            part = part.strip()
            if part.startswith("KEY_"):
                key_name = part[4:]  # Remove "KEY_" prefix

                # Map special keys to readable names
                key_map = {
                    'LEFTCTRL': 'Ctrl', 'RIGHTCTRL': 'Ctrl',
                    'LEFTALT': 'Alt', 'RIGHTALT': 'Alt',
                    'LEFTSHIFT': 'Shift', 'RIGHTSHIFT': 'Shift',
                    'LEFTMETA': 'Super', 'RIGHTMETA': 'Super',
                    'SPACE': 'Space', 'ENTER': 'Enter', 'ESC': 'Esc',
                    'TAB': 'Tab', 'BACKSPACE': 'Backspace',
                }

                if key_name in key_map:
                    readable_parts.append(key_map[key_name])
                # Check display hints first (locale-aware), then fall back to SYMBOL_MAP
                elif display_hints and part in display_hints:
                    readable_parts.append(display_hints[part])
                elif key_name in SYMBOL_MAP:
                    readable_parts.append(SYMBOL_MAP[key_name])
                elif len(key_name) == 1:
                    readable_parts.append(key_name)
                else:
                    readable_parts.append(key_name.capitalize())
            else:
                # Check if it's a mouse action part
                mouse_readable = mouse_part_to_readable(part)
                if mouse_readable:
                    readable_parts.append(mouse_readable)
                else:
                    readable_parts.append(part)

        return "+".join(readable_parts)

    def _get_key_name(self, key_code: int, display_hints: dict = None) -> str:
        """Get human-readable key name from evdev code"""
        # Map common symbol keys to their actual symbols
        SYMBOL_MAP = {
            e.KEY_LEFTBRACE: '[',
            e.KEY_RIGHTBRACE: ']',
            e.KEY_SEMICOLON: ';',
            e.KEY_APOSTROPHE: "'",
            e.KEY_GRAVE: '`',
            e.KEY_BACKSLASH: '\\',
            e.KEY_COMMA: ',',
            e.KEY_DOT: '.',
            e.KEY_SLASH: '/',
            e.KEY_MINUS: '-',
            e.KEY_EQUAL: '=',
        }

        # Preferred names for codes that have multiple KEY_ constants
        # (e.g., KEY_MUTE and KEY_MIN_INTERESTING both = 113)
        PREFERRED_NAMES = {
            e.KEY_MUTE: 'Mute',
            e.KEY_VOLUMEUP: 'Volume Up',
            e.KEY_VOLUMEDOWN: 'Volume Down',
            e.KEY_PLAYPAUSE: 'Play/Pause',
            e.KEY_STOPCD: 'Stop',
            e.KEY_PREVIOUSSONG: 'Previous',
            e.KEY_NEXTSONG: 'Next',
            # Mouse buttons
            e.BTN_LEFT: 'Left Click',
            e.BTN_RIGHT: 'Right Click',
            e.BTN_MIDDLE: 'Middle Click',
        }

        # Check preferred names first
        if key_code in PREFERRED_NAMES:
            return PREFERRED_NAMES[key_code]

        # Check display hints (locale-aware) before falling back to US SYMBOL_MAP
        if display_hints:
            for name, code in e.__dict__.items():
                if name.startswith('KEY_') and code == key_code and name in display_hints:
                    return display_hints[name]

        # Check if it's a symbol key
        if key_code in SYMBOL_MAP:
            return SYMBOL_MAP[key_code]

        # Find key name in ecodes
        for name, code in e.__dict__.items():
            if name.startswith('KEY_') and code == key_code:
                # Clean up name
                original_name = name
                name = name.replace('KEY_', '')

                # Don't strip LEFT/RIGHT from arrow keys and navigation keys
                if original_name not in ('KEY_LEFT', 'KEY_RIGHT', 'KEY_UP', 'KEY_DOWN'):
                    name = name.replace('LEFT', '')
                    name = name.replace('RIGHT', '')

                # Special case for Meta key
                if name == 'META':
                    name = 'SUPER'

                # Replace underscores with spaces for readability
                name = name.replace('_', ' ')
                return name.title()
        return f"Key{key_code}"

    def _get_rel_name(self, rel_code: int) -> str:
        """Get human-readable relative event name"""
        for name, code in e.__dict__.items():
            if name.startswith('REL_') and code == rel_code:
                return name.replace('REL_', '')
        return f"Rel{rel_code}"

    def _show_empty_state(self):
        """Show empty state when no profile loaded"""
        self.table.setRowCount(1)
        item = QTableWidgetItem("No profile selected")
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(0, 0, item)
        self.table.setSpan(0, 0, 1, 3)

    def _on_selection_changed(self):
        """Handle row selection change"""
        selected = self.table.selectedItems()
        if selected:
            row = self.table.currentRow()
            name_item = self.table.item(row, 0)
            if name_item:
                control_name = name_item.data(Qt.UserRole)
                if control_name:
                    logger.debug(f"Control selected: {control_name}")
                    self.control_selected.emit(control_name)

    def select_control(self, control_name: str):
        """Programmatically select a control in the list

        Args:
            control_name: Name of the control to select
        """
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == control_name:
                if self.table.isRowHidden(row):
                    return
                self.table.selectRow(row)
                self.table.scrollToItem(item)
                break
