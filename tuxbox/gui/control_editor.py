#!/usr/bin/env python3
"""Control editor widget

Allows editing of individual control actions with modifiers, keys, and action types.
"""

import logging
from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QLineEdit, QGroupBox, QButtonGroup, QTextEdit,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QDialogButtonBox
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QKeyEvent
from evdev import ecodes as e
from tuxbox.config_loader import VALID_MODIFIER_BUTTONS
from tuxbox.gui.ui_constants import TABLE_ROW_HEIGHT_MULTIPLIER, TEXT_EDIT_HEIGHT_MULTIPLIER
from tuxbox.gui.keymap_util import get_system_display_hints
from tuxbox.gui.theme import muted_label_style
from tuxbox.haptic import HapticStrength, HapticSpeed
from .controller_models import ELITE_CONTROLS, get_model_controls

logger = logging.getLogger(__name__)

# Character to keycode mapping for symbols and special characters
CHAR_TO_KEYCODE = {
    # Symbols (both shifted and unshifted)
    '=': 'EQUAL',
    '+': 'EQUAL',  # Shift+=
    '-': 'MINUS',
    '_': 'MINUS',  # Shift+-
    '[': 'LEFTBRACE',
    '{': 'LEFTBRACE',  # Shift+[
    ']': 'RIGHTBRACE',
    '}': 'RIGHTBRACE',  # Shift+]
    ';': 'SEMICOLON',
    ':': 'SEMICOLON',  # Shift+;
    "'": 'APOSTROPHE',
    '"': 'APOSTROPHE',  # Shift+'
    ',': 'COMMA',
    '<': 'COMMA',  # Shift+,
    '.': 'DOT',
    '>': 'DOT',  # Shift+.
    '/': 'SLASH',
    '?': 'SLASH',  # Shift+/
    '\\': 'BACKSLASH',
    '|': 'BACKSLASH',  # Shift+\
    '`': 'GRAVE',
    '~': 'GRAVE',  # Shift+`
    '1': '1',
    '!': '1',  # Shift+1
    '2': '2',
    '@': '2',  # Shift+2
    '3': '3',
    '#': '3',  # Shift+3
    '4': '4',
    '$': '4',  # Shift+4
    '5': '5',
    '%': '5',  # Shift+5
    '6': '6',
    '^': '6',  # Shift+6
    '7': '7',
    '&': '7',  # Shift+7
    '8': '8',
    '*': '8',  # Shift+8
    '9': '9',
    '(': '9',  # Shift+9
    '0': '0',
    ')': '0',  # Shift+0
}

# Keycode to character mapping for symbols (reverse lookup for parsing)
KEYCODE_TO_CHAR = {
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

# Some keycodes alias multiple KEY_* names (e.g. code 113 = both
# KEY_MIN_INTERESTING and KEY_MUTE); pin the user-facing one here.
_PREFERRED_CODE_NAMES = {
    e.KEY_MUTE: 'KEY_MUTE',
}

# Build reverse lookup: evdev keycode int -> KEY_* name string
_EVDEV_CODE_TO_NAME = {}
for _code, _name in e.bytype[e.EV_KEY].items():
    if isinstance(_name, tuple):
        _name = _PREFERRED_CODE_NAMES.get(_code, _name[0])
    if _name.startswith('KEY_'):
        _EVDEV_CODE_TO_NAME[_code] = _name

# Modifier keycodes to ignore during key capture
_MODIFIER_EVDEV_CODES = {
    e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL,
    e.KEY_LEFTALT, e.KEY_RIGHTALT,
    e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT,
    e.KEY_LEFTMETA, e.KEY_RIGHTMETA,
}

# Special keys that can't be reliably typed
SPECIAL_KEYS = {
    'None': None,
    '--- Control Keys ---': None,
    'Enter': e.KEY_ENTER,
    'Escape': e.KEY_ESC,
    'Tab': e.KEY_TAB,
    'Space': e.KEY_SPACE,
    'Backspace': e.KEY_BACKSPACE,
    'Delete': e.KEY_DELETE,
    'Insert': e.KEY_INSERT,
    'Context Menu': e.KEY_CONTEXT_MENU,
    '--- Arrow Keys ---': None,
    'Up': e.KEY_UP,
    'Down': e.KEY_DOWN,
    'Left': e.KEY_LEFT,
    'Right': e.KEY_RIGHT,
    '--- Navigation ---': None,
    'Home': e.KEY_HOME,
    'End': e.KEY_END,
    'Page Up': e.KEY_PAGEUP,
    'Page Down': e.KEY_PAGEDOWN,
    '--- Zoom Keys ---': None,
    'Zoom Reset': e.KEY_ZOOMRESET,
    'Zoom In': e.KEY_ZOOMIN,
    'Zoom Out': e.KEY_ZOOMOUT,
    '--- Function Keys ---': None,
    'F1': e.KEY_F1, 'F2': e.KEY_F2, 'F3': e.KEY_F3, 'F4': e.KEY_F4,
    'F5': e.KEY_F5, 'F6': e.KEY_F6, 'F7': e.KEY_F7, 'F8': e.KEY_F8,
    'F9': e.KEY_F9, 'F10': e.KEY_F10, 'F11': e.KEY_F11, 'F12': e.KEY_F12,
    '--- Media Keys ---': None,
    'Volume Up': e.KEY_VOLUMEUP,
    'Volume Down': e.KEY_VOLUMEDOWN,
    'Mute': e.KEY_MUTE,
    'Play/Pause': e.KEY_PLAYPAUSE,
    'Stop': e.KEY_STOPCD,
    'Previous Track': e.KEY_PREVIOUSSONG,
    'Next Track': e.KEY_NEXTSONG,
}

# All available controls
ALL_CONTROLS = ELITE_CONTROLS

# Rotary controls that have haptic feedback - maps control name to dial name
ROTARY_TO_DIAL = {
    'scroll_up': 'scroll',
    'scroll_down': 'scroll',
    'knob_cw': 'knob',
    'knob_ccw': 'knob',
    'dial_cw': 'dial',
    'dial_ccw': 'dial',
}


class KeyCaptureLineEdit(QLineEdit):
    """Custom QLineEdit that captures physical key scancodes instead of typed characters.

    Records the evdev keycode from the native scancode, ensuring correct mapping
    regardless of keyboard layout.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Press a key")
        self._evdev_keycode = None
        self._display_char = None  # Locale-aware character from key event

    def keyPressEvent(self, event: QKeyEvent):
        # Ignore auto-repeat
        if event.isAutoRepeat():
            return

        native_sc = event.nativeScanCode()
        if native_sc == 0:
            # No scancode available — ignore
            return

        # X11/Wayland native scancode = evdev keycode + 8
        evdev_code = native_sc - 8

        # Ignore modifier-only presses
        if evdev_code in _MODIFIER_EVDEV_CODES:
            return

        key_name = _EVDEV_CODE_TO_NAME.get(evdev_code)
        if key_name is None:
            return

        self._evdev_keycode = evdev_code

        # Display: use the typed character for printable keys, otherwise a readable name
        char = event.text()
        if char and char.isprintable():
            self._display_char = char
            self.setText(char)
        else:
            self._display_char = None
            # Strip KEY_ prefix and make readable (e.g. KEY_SPACE -> Space)
            display = key_name[4:] if key_name.startswith('KEY_') else key_name
            self.setText(display.capitalize())

        # Clear selection and emit textChanged for mutual-exclusion logic
        self.deselect()

    def get_key_name(self) -> Optional[str]:
        """Return the stored KEY_* name string, or None if nothing captured."""
        if self._evdev_keycode is not None:
            return _EVDEV_CODE_TO_NAME.get(self._evdev_keycode)
        return None

    def set_from_key_name(self, key_name: str, display_hints: dict = None):
        """Set state from a KEY_* string (for loading existing configs).

        Args:
            key_name: e.g. 'KEY_EQUAL', 'KEY_A', 'KEY_SPACE'
            display_hints: Optional dict of KEY_* name -> display character (locale-aware)
        """
        # Find evdev code for this name
        for code, name in _EVDEV_CODE_TO_NAME.items():
            if name == key_name:
                self._evdev_keycode = code
                # Check display hints first (locale-aware character)
                if display_hints and key_name in display_hints:
                    self._display_char = display_hints[key_name]
                    self.setText(display_hints[key_name])
                    return
                # Fallback: use KEYCODE_TO_CHAR if available, otherwise derive from name
                short = key_name[4:] if key_name.startswith('KEY_') else key_name
                if short in KEYCODE_TO_CHAR:
                    self.setText(KEYCODE_TO_CHAR[short])
                elif len(short) == 1:
                    self.setText(short.lower())
                else:
                    self.setText(short.capitalize())
                self._display_char = None
                return
        # Unknown key name — just display it raw
        self.setText(key_name)
        self._display_char = None

    def get_display_char(self) -> str:
        """Return the locale-aware display character, or None if not available."""
        return self._display_char

    def clear(self):
        """Reset captured keycode and display text."""
        self._evdev_keycode = None
        self._display_char = None
        super().clear()


class ComboConfigDialog(QDialog):
    """Dialog for configuring a modifier combination"""

    def __init__(self, parent=None, modifier_name: str = "", control_name: str = "",
                 action: str = "", comment: str = "", exclude_controls: set = None,
                 haptic_strength: HapticStrength = None, haptic_speed: HapticSpeed = None,
                 available_controls: tuple = ALL_CONTROLS):
        super().__init__(parent)
        self.setWindowTitle("Configure Modifier Combination")
        self.setMinimumWidth(500)
        self.result_haptic = haptic_strength  # Track haptic strength setting
        self.result_haptic_speed = haptic_speed  # Track haptic speed setting

        layout = QVBoxLayout(self)

        # Title
        title = QLabel(f"Configure combination for modifier: {modifier_name}")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        # Control selection
        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("Control:"))
        self.control_combo = QComboBox()
        self.control_combo.addItem("(select control)")
        # Set minimum height based on font metrics
        fm_control = self.control_combo.fontMetrics()
        self.control_combo.setMinimumHeight(int(fm_control.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER))

        # Prepare exclusion set (modifier itself + already used controls)
        if exclude_controls is None:
            exclude_controls = set()
        exclude_set = exclude_controls | {modifier_name}

        for control in available_controls:
            # Don't allow the modifier itself or already-used controls
            if control not in exclude_set:
                self.control_combo.addItem(control)

        if control_name:
            idx = self.control_combo.findText(control_name)
            if idx >= 0:
                self.control_combo.setCurrentIndex(idx)
        control_layout.addWidget(self.control_combo, stretch=1)
        layout.addLayout(control_layout)

        # Action type selection
        action_type_layout = QHBoxLayout()
        action_type_layout.addWidget(QLabel("Action Type:"))
        self.action_type_combo = QComboBox()
        self.action_type_combo.addItems(["Keyboard", "Mouse", "None"])
        # Set minimum height based on font metrics
        fm_action = self.action_type_combo.fontMetrics()
        self.action_type_combo.setMinimumHeight(int(fm_action.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER))
        self.action_type_combo.currentTextChanged.connect(self._on_action_type_changed)
        action_type_layout.addWidget(self.action_type_combo)
        action_type_layout.addStretch()
        layout.addLayout(action_type_layout)

        # Keyboard action group - all on one row
        self.keyboard_group = QGroupBox("Keyboard Action")
        keyboard_layout = QHBoxLayout(self.keyboard_group)

        # Calculate minimum height for buttons and input fields based on font metrics
        fm = self.keyboard_group.fontMetrics()
        button_height = int(fm.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER)

        # Modifier buttons
        self.ctrl_btn = QPushButton("Ctrl")
        self.ctrl_btn.setCheckable(True)
        self.ctrl_btn.setMaximumWidth(55)
        self.ctrl_btn.setMinimumHeight(button_height)
        keyboard_layout.addWidget(self.ctrl_btn)

        self.alt_btn = QPushButton("Alt")
        self.alt_btn.setCheckable(True)
        self.alt_btn.setMaximumWidth(55)
        self.alt_btn.setMinimumHeight(button_height)
        keyboard_layout.addWidget(self.alt_btn)

        self.shift_btn = QPushButton("Shift")
        self.shift_btn.setCheckable(True)
        self.shift_btn.setMaximumWidth(55)
        self.shift_btn.setMinimumHeight(button_height)
        keyboard_layout.addWidget(self.shift_btn)

        self.super_btn = QPushButton("Super")
        self.super_btn.setCheckable(True)
        self.super_btn.setMaximumWidth(55)
        self.super_btn.setMinimumHeight(button_height)
        keyboard_layout.addWidget(self.super_btn)

        # Spacing between modifiers and key input
        keyboard_layout.addSpacing(15)

        # Key input
        key_label = QLabel("Key:")
        keyboard_layout.addWidget(key_label)

        self.key_input = KeyCaptureLineEdit()
        self.key_input.setMaximumWidth(120)
        self.key_input.setMinimumHeight(button_height)
        self.key_input.textChanged.connect(self._on_key_input_changed)
        keyboard_layout.addWidget(self.key_input)

        or_label = QLabel("or")
        keyboard_layout.addWidget(or_label)

        self.special_key_combo = QComboBox()
        for key_name in SPECIAL_KEYS.keys():
            self.special_key_combo.addItem(key_name)
            # Disable separator items (those starting with "---"), but not "None"
            if key_name.startswith("---"):
                idx = self.special_key_combo.count() - 1
                self.special_key_combo.model().item(idx).setEnabled(False)
        self.special_key_combo.setMaximumWidth(150)
        self.special_key_combo.setMinimumHeight(button_height)
        self.special_key_combo.currentTextChanged.connect(self._on_special_key_changed)
        keyboard_layout.addWidget(self.special_key_combo)

        keyboard_layout.addStretch()

        layout.addWidget(self.keyboard_group)

        # Mouse wheel action group
        self.mouse_group = QGroupBox("Mouse Action")
        self.mouse_group.setMinimumHeight(80)  # Ensure enough space for controls
        mouse_layout = QVBoxLayout(self.mouse_group)

        # Calculate minimum height for combo box based on font metrics
        fm_mouse = self.mouse_group.fontMetrics()
        combo_height = int(fm_mouse.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER)

        mouse_dir_layout = QHBoxLayout()
        mouse_dir_layout.addWidget(QLabel("Action:"))
        self.mouse_direction_combo = QComboBox()
        self.mouse_direction_combo.addItems([
            "Scroll Up",
            "Scroll Down",
            "Scroll Left",
            "Scroll Right",
            "Left Click",
            "Right Click",
            "Middle Click"
        ])
        self.mouse_direction_combo.setMinimumHeight(combo_height)
        mouse_dir_layout.addWidget(self.mouse_direction_combo)
        mouse_dir_layout.addStretch()
        mouse_layout.addLayout(mouse_dir_layout)

        layout.addWidget(self.mouse_group)
        self.mouse_group.hide()  # Hidden by default

        # Comment field
        comment_label = QLabel("Comment:")
        layout.addWidget(comment_label)
        self.comment_text = QTextEdit()
        self.comment_text.setPlaceholderText("Add notes about this combination...")
        # Set height to approximately 1 line based on font metrics
        fm = self.comment_text.fontMetrics()
        self.comment_text.setMaximumHeight(int(fm.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER))
        self.comment_text.setPlainText(comment)
        layout.addWidget(self.comment_text)

        # Haptic feedback group (only for rotary controls)
        self.haptic_group = QGroupBox("Haptic Feedback")
        haptic_layout = QVBoxLayout(self.haptic_group)

        # Strength row
        haptic_strength_row = QHBoxLayout()
        haptic_strength_row.addWidget(QLabel("Strength:"))
        self.haptic_combo = QComboBox()
        self.haptic_combo.addItem("Use Profile Default", None)
        self.haptic_combo.addItem("Off", HapticStrength.OFF)
        self.haptic_combo.addItem("Weak", HapticStrength.WEAK)
        self.haptic_combo.addItem("Strong", HapticStrength.STRONG)
        # Set minimum height based on font metrics
        fm_haptic = self.haptic_combo.fontMetrics()
        self.haptic_combo.setMinimumHeight(int(fm_haptic.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER))
        # Set initial value
        if haptic_strength is not None:
            index = self.haptic_combo.findData(haptic_strength)
            if index >= 0:
                self.haptic_combo.setCurrentIndex(index)
        haptic_strength_row.addWidget(self.haptic_combo)
        haptic_strength_row.addStretch()
        haptic_layout.addLayout(haptic_strength_row)

        # Speed row
        haptic_speed_row = QHBoxLayout()
        haptic_speed_row.addWidget(QLabel("Speed:"))
        self.haptic_speed_combo = QComboBox()
        self.haptic_speed_combo.addItem("Use Profile Default", None)
        self.haptic_speed_combo.addItem("Fast (more detents)", HapticSpeed.FAST)
        self.haptic_speed_combo.addItem("Medium", HapticSpeed.MEDIUM)
        self.haptic_speed_combo.addItem("Slow (fewer detents)", HapticSpeed.SLOW)
        self.haptic_speed_combo.setMinimumHeight(int(fm_haptic.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER))
        # Set initial value
        if haptic_speed is not None:
            speed_index = self.haptic_speed_combo.findData(haptic_speed)
            if speed_index >= 0:
                self.haptic_speed_combo.setCurrentIndex(speed_index)
        haptic_speed_row.addWidget(self.haptic_speed_combo)
        haptic_speed_row.addStretch()
        haptic_layout.addLayout(haptic_speed_row)

        haptic_info = QLabel(
            "Haptic feedback for this modifier+dial combination."
        )
        haptic_info.setWordWrap(True)
        haptic_info.setStyleSheet(muted_label_style(10))
        haptic_layout.addWidget(haptic_info)

        layout.addWidget(self.haptic_group)
        self.haptic_group.hide()  # Hidden by default, shown when rotary control selected

        # Connect control selection to update haptic visibility
        self.control_combo.currentTextChanged.connect(self._on_control_changed)

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Parse and populate if editing existing combo
        if action:
            self._parse_and_populate(action)

        # Show haptic if editing existing rotary control
        if control_name and control_name in ROTARY_TO_DIAL:
            self.haptic_group.show()

    def _on_action_type_changed(self, action_type: str):
        """Handle action type change"""
        if action_type == "Keyboard":
            self.keyboard_group.show()
            self.mouse_group.hide()
        elif action_type == "Mouse":
            self.keyboard_group.hide()
            self.mouse_group.show()
        else:  # None
            self.keyboard_group.hide()
            self.mouse_group.hide()

    def _on_control_changed(self, control_name: str):
        """Handle control selection change - show/hide haptic for rotary controls"""
        if control_name in ROTARY_TO_DIAL:
            self.haptic_group.show()
        else:
            self.haptic_group.hide()

    def _on_key_input_changed(self, text: str):
        """Handle key input text change - clear special key dropdown"""
        if text:
            self.special_key_combo.setCurrentIndex(0)

    def _on_special_key_changed(self, key_name: str):
        """Handle special key dropdown change - clear text input"""
        if key_name and key_name != "None" and SPECIAL_KEYS.get(key_name) is not None:
            self.key_input.clear()

    def _parse_and_populate(self, action_str: str):
        """Parse action string and populate UI fields"""
        if not action_str or action_str == "none":
            self.action_type_combo.setCurrentText("None")
            return

        # Check if it's a mouse action (scroll or button)
        if action_str.startswith("REL_WHEEL:") or action_str.startswith("REL_HWHEEL:"):
            self.action_type_combo.setCurrentText("Mouse")
            if action_str.startswith("REL_WHEEL:"):
                value = int(action_str.split(":")[1])
                if value > 0:
                    self.mouse_direction_combo.setCurrentText("Scroll Up")
                else:
                    self.mouse_direction_combo.setCurrentText("Scroll Down")
            else:
                value = int(action_str.split(":")[1])
                if value > 0:
                    self.mouse_direction_combo.setCurrentText("Scroll Right")
                else:
                    self.mouse_direction_combo.setCurrentText("Scroll Left")
            return

        # Check if it's a mouse button action
        if action_str in ("BTN_LEFT", "BTN_RIGHT", "BTN_MIDDLE"):
            self.action_type_combo.setCurrentText("Mouse")
            if action_str == "BTN_LEFT":
                self.mouse_direction_combo.setCurrentText("Left Click")
            elif action_str == "BTN_RIGHT":
                self.mouse_direction_combo.setCurrentText("Right Click")
            elif action_str == "BTN_MIDDLE":
                self.mouse_direction_combo.setCurrentText("Middle Click")
            return

        # It's a keyboard action
        self.action_type_combo.setCurrentText("Keyboard")

        # Parse key combination
        parts = action_str.split("+")
        for part in parts:
            part = part.strip()
            part_upper = part.upper()
            if "CTRL" in part_upper:
                self.ctrl_btn.setChecked(True)
            elif "ALT" in part_upper:
                self.alt_btn.setChecked(True)
            elif "SHIFT" in part_upper:
                self.shift_btn.setChecked(True)
            elif "META" in part_upper or "SUPER" in part_upper:
                self.super_btn.setChecked(True)
            else:
                # It's the actual key
                key_part = part
                full_key = key_part if key_part.startswith("KEY_") else f"KEY_{key_part}"

                # Check if it maps to a single character (letter, number, symbol)
                short = full_key[4:]  # Remove KEY_ prefix
                is_single = (short.upper() in KEYCODE_TO_CHAR or len(short) == 1)

                if is_single:
                    self.key_input.set_from_key_name(full_key.upper())
                else:
                    # Try to match in special keys dropdown
                    for i in range(self.special_key_combo.count()):
                        item_text = self.special_key_combo.itemText(i)
                        if item_text.lower() == short.lower():
                            self.special_key_combo.setCurrentIndex(i)
                            break

    def get_control(self) -> str:
        """Get selected control name"""
        control = self.control_combo.currentText()
        return control if control != "(select control)" else ""

    def get_action(self) -> str:
        """Get configured action string"""
        action_type = self.action_type_combo.currentText()

        if action_type == "None":
            return "none"

        if action_type == "Mouse":
            action = self.mouse_direction_combo.currentText()
            if action == "Scroll Up":
                return "REL_WHEEL:1"
            elif action == "Scroll Down":
                return "REL_WHEEL:-1"
            elif action == "Scroll Left":
                return "REL_HWHEEL:-1"
            elif action == "Scroll Right":
                return "REL_HWHEEL:1"
            elif action == "Left Click":
                return "BTN_LEFT"
            elif action == "Right Click":
                return "BTN_RIGHT"
            elif action == "Middle Click":
                return "BTN_MIDDLE"

        # Keyboard action
        parts = []

        # Add modifiers
        if self.ctrl_btn.isChecked():
            parts.append("KEY_LEFTCTRL")
        if self.alt_btn.isChecked():
            parts.append("KEY_LEFTALT")
        if self.shift_btn.isChecked():
            parts.append("KEY_LEFTSHIFT")
        if self.super_btn.isChecked():
            parts.append("KEY_LEFTMETA")

        # Add key (prefer scancode-captured name, fall back to CHAR_TO_KEYCODE)
        captured = self.key_input.get_key_name()
        if captured:
            parts.append(captured)
        elif self.key_input.text():
            char = self.key_input.text()
            if char in CHAR_TO_KEYCODE:
                key_name = CHAR_TO_KEYCODE[char]
                parts.append(f"KEY_{key_name}")
            else:
                parts.append(f"KEY_{char.upper()}")
        elif self.special_key_combo.currentText() != "None":
            key_name = self.special_key_combo.currentText()
            if SPECIAL_KEYS.get(key_name):
                code = SPECIAL_KEYS[key_name]
                if code in _EVDEV_CODE_TO_NAME:
                    parts.append(_EVDEV_CODE_TO_NAME[code])

        return "+".join(parts) if parts else "none"

    def get_comment(self) -> str:
        """Get comment text"""
        return self.comment_text.toPlainText().strip()

    def get_haptic(self) -> Optional[HapticStrength]:
        """Get haptic strength setting (None = use profile default)"""
        return self.haptic_combo.currentData()

    def get_haptic_speed(self) -> Optional[HapticSpeed]:
        """Get haptic speed setting (None = use profile default)"""
        return self.haptic_speed_combo.currentData()


class DoublePressDialog(QDialog):
    """Dialog for configuring double-press action"""

    def __init__(self, parent=None, control_name: str = "", action: str = "",
                 comment: str = "", timeout: int = 300):
        super().__init__(parent)
        self.setWindowTitle("Configure Double-Press Action")
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)

        # Title and info
        title = QLabel(f"Double-Press Action for: {control_name}")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)

        info_label = QLabel(
            f"This action triggers when the button is pressed twice within {timeout}ms.\n"
            f"Single-press actions fire immediately (no delay)."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(muted_label_style(10, "margin-bottom: 10px;"))
        layout.addWidget(info_label)

        # Action type selection
        action_type_layout = QHBoxLayout()
        action_type_layout.addWidget(QLabel("Action Type:"))
        self.action_type_combo = QComboBox()
        self.action_type_combo.addItems(["Keyboard", "Mouse"])
        fm = self.action_type_combo.fontMetrics()
        self.action_type_combo.setMinimumHeight(int(fm.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER))
        self.action_type_combo.currentTextChanged.connect(self._on_action_type_changed)
        action_type_layout.addWidget(self.action_type_combo)
        action_type_layout.addStretch()
        layout.addLayout(action_type_layout)

        # Keyboard action group
        self.keyboard_group = QGroupBox("Keyboard Action")
        keyboard_layout = QVBoxLayout(self.keyboard_group)

        button_height = int(fm.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER)

        # Modifiers
        mod_layout = QHBoxLayout()
        self.ctrl_btn = QPushButton("Ctrl")
        self.ctrl_btn.setCheckable(True)
        self.ctrl_btn.setMaximumWidth(80)
        self.ctrl_btn.setMinimumHeight(button_height)
        mod_layout.addWidget(self.ctrl_btn)

        self.alt_btn = QPushButton("Alt")
        self.alt_btn.setCheckable(True)
        self.alt_btn.setMaximumWidth(80)
        self.alt_btn.setMinimumHeight(button_height)
        mod_layout.addWidget(self.alt_btn)

        self.shift_btn = QPushButton("Shift")
        self.shift_btn.setCheckable(True)
        self.shift_btn.setMaximumWidth(80)
        self.shift_btn.setMinimumHeight(button_height)
        mod_layout.addWidget(self.shift_btn)

        self.super_btn = QPushButton("Super")
        self.super_btn.setCheckable(True)
        self.super_btn.setMaximumWidth(80)
        self.super_btn.setMinimumHeight(button_height)
        mod_layout.addWidget(self.super_btn)

        mod_layout.addStretch()
        keyboard_layout.addLayout(mod_layout)

        # Key input
        key_layout = QHBoxLayout()
        key_layout.addWidget(QLabel("Key:"))

        self.key_input = KeyCaptureLineEdit()
        self.key_input.setMaximumWidth(150)
        self.key_input.setMinimumHeight(button_height)
        self.key_input.textChanged.connect(self._on_key_input_changed)
        key_layout.addWidget(self.key_input)

        key_layout.addWidget(QLabel("or"))

        self.special_key_combo = QComboBox()
        for key_name in SPECIAL_KEYS.keys():
            self.special_key_combo.addItem(key_name)
            # Disable separator items (those starting with "---"), but not "None"
            if key_name.startswith("---"):
                idx = self.special_key_combo.count() - 1
                self.special_key_combo.model().item(idx).setEnabled(False)
        self.special_key_combo.setMaximumWidth(150)
        self.special_key_combo.setMinimumHeight(button_height)
        self.special_key_combo.currentTextChanged.connect(self._on_special_key_changed)
        key_layout.addWidget(self.special_key_combo)

        key_layout.addStretch()
        keyboard_layout.addLayout(key_layout)

        layout.addWidget(self.keyboard_group)

        # Mouse action group
        self.mouse_group = QGroupBox("Mouse Action")
        mouse_layout = QHBoxLayout(self.mouse_group)
        mouse_layout.addWidget(QLabel("Action:"))
        self.mouse_combo = QComboBox()
        self.mouse_combo.addItems([
            "Scroll Up", "Scroll Down", "Scroll Left", "Scroll Right",
            "Left Click", "Right Click", "Middle Click"
        ])
        self.mouse_combo.setMinimumHeight(button_height)
        mouse_layout.addWidget(self.mouse_combo)
        mouse_layout.addStretch()
        layout.addWidget(self.mouse_group)
        self.mouse_group.hide()

        # Comment field
        comment_layout = QHBoxLayout()
        comment_layout.addWidget(QLabel("Comment:"))
        self.comment_input = QLineEdit()
        self.comment_input.setPlaceholderText("Notes for this action...")
        self.comment_input.setMinimumHeight(button_height)
        self.comment_input.setText(comment)
        comment_layout.addWidget(self.comment_input)
        layout.addLayout(comment_layout)

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Parse and populate if editing existing action
        if action:
            self._parse_and_populate(action)

    def _on_action_type_changed(self, action_type: str):
        if action_type == "Keyboard":
            self.keyboard_group.show()
            self.mouse_group.hide()
        else:
            self.keyboard_group.hide()
            self.mouse_group.show()

    def _on_key_input_changed(self, text: str):
        if text:
            self.special_key_combo.setCurrentIndex(0)

    def _on_special_key_changed(self, key_name: str):
        if key_name and key_name != "None" and SPECIAL_KEYS.get(key_name) is not None:
            self.key_input.clear()

    def _parse_and_populate(self, action_str: str):
        """Parse action string and populate UI"""
        if not action_str:
            return

        # Check for mouse action
        if action_str.startswith("REL_WHEEL:") or action_str.startswith("REL_HWHEEL:"):
            self.action_type_combo.setCurrentText("Mouse")
            if action_str.startswith("REL_WHEEL:"):
                value = int(action_str.split(":")[1])
                self.mouse_combo.setCurrentText("Scroll Up" if value > 0 else "Scroll Down")
            else:
                value = int(action_str.split(":")[1])
                self.mouse_combo.setCurrentText("Scroll Right" if value > 0 else "Scroll Left")
            return

        if action_str in ("BTN_LEFT", "BTN_RIGHT", "BTN_MIDDLE"):
            self.action_type_combo.setCurrentText("Mouse")
            if action_str == "BTN_LEFT":
                self.mouse_combo.setCurrentText("Left Click")
            elif action_str == "BTN_RIGHT":
                self.mouse_combo.setCurrentText("Right Click")
            else:
                self.mouse_combo.setCurrentText("Middle Click")
            return

        # Keyboard action
        self.action_type_combo.setCurrentText("Keyboard")
        parts = action_str.split("+")
        for part in parts:
            part = part.strip().upper()
            if "CTRL" in part:
                self.ctrl_btn.setChecked(True)
            elif "ALT" in part:
                self.alt_btn.setChecked(True)
            elif "SHIFT" in part:
                self.shift_btn.setChecked(True)
            elif "META" in part or "SUPER" in part:
                self.super_btn.setChecked(True)
            else:
                key_part = part
                full_key = key_part if key_part.startswith("KEY_") else f"KEY_{key_part}"

                short = full_key[4:]
                is_single = (short in KEYCODE_TO_CHAR or len(short) == 1)

                if is_single:
                    self.key_input.set_from_key_name(full_key.upper())
                else:
                    for i in range(self.special_key_combo.count()):
                        if self.special_key_combo.itemText(i).upper().replace(" ", "") == short.replace("_", ""):
                            self.special_key_combo.setCurrentIndex(i)
                            break

    def get_action(self) -> str:
        """Get configured action string"""
        action_type = self.action_type_combo.currentText()

        if action_type == "Mouse":
            action = self.mouse_combo.currentText()
            if action == "Scroll Up":
                return "REL_WHEEL:1"
            elif action == "Scroll Down":
                return "REL_WHEEL:-1"
            elif action == "Scroll Left":
                return "REL_HWHEEL:-1"
            elif action == "Scroll Right":
                return "REL_HWHEEL:1"
            elif action == "Left Click":
                return "BTN_LEFT"
            elif action == "Right Click":
                return "BTN_RIGHT"
            elif action == "Middle Click":
                return "BTN_MIDDLE"

        # Keyboard action
        parts = []
        if self.ctrl_btn.isChecked():
            parts.append("KEY_LEFTCTRL")
        if self.alt_btn.isChecked():
            parts.append("KEY_LEFTALT")
        if self.shift_btn.isChecked():
            parts.append("KEY_LEFTSHIFT")
        if self.super_btn.isChecked():
            parts.append("KEY_LEFTMETA")

        captured = self.key_input.get_key_name()
        if captured:
            parts.append(captured)
        elif self.key_input.text():
            char = self.key_input.text()
            if char in CHAR_TO_KEYCODE:
                parts.append(f"KEY_{CHAR_TO_KEYCODE[char]}")
            else:
                parts.append(f"KEY_{char.upper()}")
        elif self.special_key_combo.currentText() != "None":
            key_name = self.special_key_combo.currentText()
            if SPECIAL_KEYS.get(key_name):
                code = SPECIAL_KEYS[key_name]
                if code in _EVDEV_CODE_TO_NAME:
                    parts.append(_EVDEV_CODE_TO_NAME[code])

        return "+".join(parts) if parts else ""

    def get_comment(self) -> str:
        return self.comment_input.text().strip()


class ControlEditor(QWidget):
    """Widget for editing a control's action"""

    # Signals emitted when user makes changes
    action_changed = Signal(str, str)  # control_name, action_string
    comment_changed = Signal(str, str)  # control_name, comment
    modifier_config_changed = Signal(str, dict)  # control_name, modifier_config
    combo_selected = Signal(str)  # combo_control_name (control selected from Modifier Combinations table)
    haptic_changed = Signal(str, object, object)  # dial_name, HapticStrength or None, HapticSpeed or None
    combo_haptic_changed = Signal(str, str, object, object)  # modifier_name, dial_name, HapticStrength or None, HapticSpeed or None
    double_press_action_changed = Signal(str, str)  # control_name, action_string (empty to clear)
    double_press_comment_changed = Signal(str, str)  # control_name, comment
    on_release_changed = Signal(str, bool)  # control_name, enabled

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_control = None
        self.current_dial = None  # Track which dial we're editing (for haptic)
        self.combo_haptics = {}  # Track haptic strength for combos: (modifier, dial) -> HapticStrength
        self.combo_haptic_speeds = {}  # Track haptic speed for combos: (modifier, dial) -> HapticSpeed
        self.current_double_click_timeout = 300  # Track current profile's timeout for display
        self._model = 'elite'
        self._init_ui()

    def set_model(self, model: str):
        """Hide unavailable combinations while retaining their saved actions."""
        self._model = model
        available = get_model_controls(model)
        for row in range(self.combos_table.rowCount()):
            item = self.combos_table.item(row, 0)
            if item:
                self.combos_table.setRowHidden(row, item.text() not in available)
        current = self.combos_table.currentRow()
        if current >= 0 and self.combos_table.isRowHidden(current):
            self.combos_table.clearSelection()

    def _init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout(self)

        # Header
        self.header_label = QLabel("Edit Control")
        self.header_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.header_label)

        # Control name display
        self.control_label = QLabel("No control selected")
        self.control_label.setStyleSheet(muted_label_style(12))
        layout.addWidget(self.control_label)

        # Action type selection
        action_type_layout = QHBoxLayout()
        action_type_layout.addWidget(QLabel("Action Type:"))
        self.action_type_combo = QComboBox()
        self.action_type_combo.addItems(["Keyboard", "Mouse", "None"])
        # Set minimum height based on font metrics
        fm_action = self.action_type_combo.fontMetrics()
        self.action_type_combo.setMinimumHeight(int(fm_action.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER))
        self.action_type_combo.currentTextChanged.connect(self._on_action_type_changed)
        action_type_layout.addWidget(self.action_type_combo)
        action_type_layout.addStretch()
        layout.addLayout(action_type_layout)

        # Keyboard action group - all controls on one row
        self.keyboard_group = QGroupBox("Keyboard Action")
        keyboard_layout = QHBoxLayout(self.keyboard_group)

        # Calculate minimum height for buttons and input fields based on font metrics
        fm = self.keyboard_group.fontMetrics()
        button_height = int(fm.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER)

        # Modifier buttons
        self.ctrl_btn = QPushButton("Ctrl")
        self.ctrl_btn.setCheckable(True)
        self.ctrl_btn.setMaximumWidth(55)
        self.ctrl_btn.setMinimumHeight(button_height)
        keyboard_layout.addWidget(self.ctrl_btn)

        self.alt_btn = QPushButton("Alt")
        self.alt_btn.setCheckable(True)
        self.alt_btn.setMaximumWidth(55)
        self.alt_btn.setMinimumHeight(button_height)
        keyboard_layout.addWidget(self.alt_btn)

        self.shift_btn = QPushButton("Shift")
        self.shift_btn.setCheckable(True)
        self.shift_btn.setMaximumWidth(55)
        self.shift_btn.setMinimumHeight(button_height)
        keyboard_layout.addWidget(self.shift_btn)

        self.super_btn = QPushButton("Super")
        self.super_btn.setCheckable(True)
        self.super_btn.setMaximumWidth(55)
        self.super_btn.setMinimumHeight(button_height)
        keyboard_layout.addWidget(self.super_btn)

        # Spacing between modifiers and key input
        keyboard_layout.addSpacing(15)

        # Key input
        key_label = QLabel("Key:")
        keyboard_layout.addWidget(key_label)

        self.key_input = KeyCaptureLineEdit()
        self.key_input.setMaximumWidth(120)
        self.key_input.setMinimumHeight(button_height)
        self.key_input.textChanged.connect(self._on_key_input_changed)
        keyboard_layout.addWidget(self.key_input)

        or_label = QLabel("or")
        keyboard_layout.addWidget(or_label)

        self.special_key_combo = QComboBox()
        for key_name in SPECIAL_KEYS.keys():
            self.special_key_combo.addItem(key_name)
            # Disable separator items (those starting with "---"), but not "None"
            if key_name.startswith("---"):
                idx = self.special_key_combo.count() - 1
                self.special_key_combo.model().item(idx).setEnabled(False)
        self.special_key_combo.setMaximumWidth(150)
        self.special_key_combo.setMinimumHeight(button_height)
        self.special_key_combo.currentTextChanged.connect(self._on_special_key_changed)
        keyboard_layout.addWidget(self.special_key_combo)

        keyboard_layout.addStretch()

        layout.addWidget(self.keyboard_group)

        # Mouse wheel action group
        self.mouse_group = QGroupBox("Mouse Action")
        self.mouse_group.setMinimumHeight(80)  # Ensure enough space for controls
        mouse_layout = QVBoxLayout(self.mouse_group)

        # Calculate minimum height for buttons and combo box based on font metrics
        fm_mouse = self.mouse_group.fontMetrics()
        mouse_button_height = int(fm_mouse.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER)

        mouse_dir_layout = QHBoxLayout()

        # Modifier buttons (left side)
        self.mouse_ctrl_btn = QPushButton("Ctrl")
        self.mouse_ctrl_btn.setCheckable(True)
        self.mouse_ctrl_btn.setMaximumWidth(55)
        self.mouse_ctrl_btn.setMinimumHeight(mouse_button_height)
        mouse_dir_layout.addWidget(self.mouse_ctrl_btn)

        self.mouse_alt_btn = QPushButton("Alt")
        self.mouse_alt_btn.setCheckable(True)
        self.mouse_alt_btn.setMaximumWidth(55)
        self.mouse_alt_btn.setMinimumHeight(mouse_button_height)
        mouse_dir_layout.addWidget(self.mouse_alt_btn)

        self.mouse_shift_btn = QPushButton("Shift")
        self.mouse_shift_btn.setCheckable(True)
        self.mouse_shift_btn.setMaximumWidth(55)
        self.mouse_shift_btn.setMinimumHeight(mouse_button_height)
        mouse_dir_layout.addWidget(self.mouse_shift_btn)

        self.mouse_super_btn = QPushButton("Super")
        self.mouse_super_btn.setCheckable(True)
        self.mouse_super_btn.setMaximumWidth(55)
        self.mouse_super_btn.setMinimumHeight(mouse_button_height)
        mouse_dir_layout.addWidget(self.mouse_super_btn)

        # Spacing between modifiers and action
        mouse_dir_layout.addSpacing(15)

        # Action dropdown (right side)
        mouse_dir_layout.addWidget(QLabel("Action:"))
        self.mouse_direction_combo = QComboBox()
        self.mouse_direction_combo.addItems([
            "Scroll Up",
            "Scroll Down",
            "Scroll Left",
            "Scroll Right",
            "Left Click",
            "Right Click",
            "Middle Click"
        ])
        self.mouse_direction_combo.setMinimumHeight(mouse_button_height)
        mouse_dir_layout.addWidget(self.mouse_direction_combo)
        mouse_dir_layout.addStretch()
        mouse_layout.addLayout(mouse_dir_layout)

        layout.addWidget(self.mouse_group)
        self.mouse_group.hide()  # Hidden by default

        # Haptic feedback group (only for rotary controls)
        self.haptic_group = QGroupBox("Haptic Feedback")
        haptic_layout = QVBoxLayout(self.haptic_group)

        haptic_row = QHBoxLayout()
        # Strength dropdown
        haptic_row.addWidget(QLabel("Strength:"))
        self.haptic_combo = QComboBox()
        self.haptic_combo.addItem("Use Profile Default", None)
        self.haptic_combo.addItem("Off", HapticStrength.OFF)
        self.haptic_combo.addItem("Weak", HapticStrength.WEAK)
        self.haptic_combo.addItem("Strong", HapticStrength.STRONG)
        # Set minimum height based on font metrics
        fm_haptic = self.haptic_combo.fontMetrics()
        self.haptic_combo.setMinimumHeight(int(fm_haptic.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER))
        haptic_row.addWidget(self.haptic_combo)

        # Speed dropdown (to the right of strength)
        haptic_row.addSpacing(20)
        haptic_row.addWidget(QLabel("Speed:"))
        self.haptic_speed_combo = QComboBox()
        self.haptic_speed_combo.addItem("Use Profile Default", None)
        self.haptic_speed_combo.addItem("Fast (more detents)", HapticSpeed.FAST)
        self.haptic_speed_combo.addItem("Medium", HapticSpeed.MEDIUM)
        self.haptic_speed_combo.addItem("Slow (fewer detents)", HapticSpeed.SLOW)
        self.haptic_speed_combo.setMinimumHeight(int(fm_haptic.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER))
        haptic_row.addWidget(self.haptic_speed_combo)

        haptic_row.addStretch()
        haptic_layout.addLayout(haptic_row)

        haptic_info = QLabel(
            "Per-dial haptic setting. 'Use Profile Default' uses the profile's global setting."
        )
        haptic_info.setWordWrap(True)
        haptic_info.setStyleSheet(muted_label_style(10))
        haptic_layout.addWidget(haptic_info)

        layout.addWidget(self.haptic_group)
        self.haptic_group.hide()  # Hidden by default, shown for rotary controls

        # Comment/Notes field (visible for non-modifier controls)
        self.comment_group = QGroupBox("Comment")
        comment_layout = QVBoxLayout(self.comment_group)

        self.comment_text = QTextEdit()
        self.comment_text.setPlaceholderText("Add notes or comments about this mapping...")
        # Set height to approximately 1 line based on font metrics
        fm = self.comment_text.fontMetrics()
        text_height = int(fm.lineSpacing() * TEXT_EDIT_HEIGHT_MULTIPLIER)
        self.comment_text.setMinimumHeight(text_height)
        self.comment_text.setMaximumHeight(text_height)
        comment_layout.addWidget(self.comment_text)

        # Set group box min/max height to prevent stretching
        self.comment_group.setMinimumHeight(text_height + 40)  # Text + title + margins
        self.comment_group.setMaximumHeight(text_height + 40)  # Prevent vertical stretching

        layout.addWidget(self.comment_group)

        # Double-Press Action section (compact - opens dialog)
        self.double_press_section = QWidget()
        dp_section_layout = QHBoxLayout(self.double_press_section)
        dp_section_layout.setContentsMargins(0, 5, 0, 5)

        dp_label = QLabel("Double-Press:")
        dp_section_layout.addWidget(dp_label)

        self.dp_action_label = QLabel("(none)")
        self.dp_action_label.setStyleSheet(muted_label_style())
        dp_section_layout.addWidget(self.dp_action_label)

        dp_section_layout.addStretch()

        self.dp_configure_btn = QPushButton("Configure...")
        self.dp_configure_btn.clicked.connect(self._on_configure_double_press)
        dp_section_layout.addWidget(self.dp_configure_btn)

        self.dp_clear_btn = QPushButton("Clear")
        self.dp_clear_btn.clicked.connect(self._on_dp_clear)
        self.dp_clear_btn.setEnabled(False)
        dp_section_layout.addWidget(self.dp_clear_btn)

        layout.addWidget(self.double_press_section)
        self.double_press_section.hide()  # Hidden for rotary controls

        # On-Release checkbox (only for holdable buttons)
        self.on_release_section = QWidget()
        on_release_layout = QHBoxLayout(self.on_release_section)
        on_release_layout.setContentsMargins(0, 5, 0, 5)

        self.on_release_checkbox = QCheckBox("Activate on release")
        self.on_release_checkbox.setToolTip(
            "Fire action when button is released (as a tap) instead of when pressed.\n"
            "Use for buttons with combos or double-press to improve reliability."
        )
        self.on_release_checkbox.stateChanged.connect(self._on_on_release_changed)
        on_release_layout.addWidget(self.on_release_checkbox)
        on_release_layout.addStretch()

        layout.addWidget(self.on_release_section)
        self.on_release_section.hide()  # Hidden for rotary controls

        # Modifier Combinations section (only visible for physical buttons)
        # No groupbox wrapper - just the label, table, and button
        self.combos_label = QLabel("Modifier Combinations:")
        self.combos_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(self.combos_label)

        self.combos_table = QTableWidget()
        self.combos_table.setColumnCount(4)
        self.combos_table.setHorizontalHeaderLabels(["Control", "Action", "Comment", ""])
        self.combos_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.combos_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.combos_table.horizontalHeader().setStretchLastSection(False)
        self.combos_table.setColumnWidth(3, 80)  # Fixed width for icon button column
        self.combos_table.setEditTriggers(QTableWidget.NoEditTriggers)  # Read-only
        self.combos_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.combos_table.setSelectionMode(QTableWidget.SingleSelection)
        self.combos_table.verticalHeader().setVisible(False)  # Hide row numbers

        # Ensure vertical scrollbar is shown only when needed
        self.combos_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        # Set row height and table max height based on font metrics for proper scaling
        fm = self.combos_table.fontMetrics()
        row_height = int(fm.lineSpacing() * TABLE_ROW_HEIGHT_MULTIPLIER)
        self.combos_table.verticalHeader().setDefaultSectionSize(row_height)
        self.combos_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)

        # Set max height to fit ~6 rows plus header (allows table to scale but caps it)
        header_height = self.combos_table.horizontalHeader().height()

        # Header height might be 0 at init, use reasonable default based on font metrics
        if header_height < 20:
            header_height = int(fm.lineSpacing() * 1.5)  # Base on font size

        # Calculate min/max height: min 3 rows, max 5 rows + header + frame/borders
        min_table_height = row_height * 3 + header_height + 4
        max_table_height = row_height * 5 + header_height + 4
        self.combos_table.setMinimumHeight(min_table_height)
        self.combos_table.setMaximumHeight(max_table_height)
        self.combos_table.itemSelectionChanged.connect(self._on_combo_selection_changed)
        layout.addWidget(self.combos_table)

        combos_btn_layout = QHBoxLayout()
        self.add_combo_btn = QPushButton("Add Combination")
        self.add_combo_btn.clicked.connect(self._on_add_combo)
        combos_btn_layout.addWidget(self.add_combo_btn)
        combos_btn_layout.addStretch()
        layout.addLayout(combos_btn_layout)

        # Small spacing before Apply button
        layout.addSpacing(8)

        # Apply button
        button_layout = QHBoxLayout()
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.clicked.connect(self._on_apply)
        button_layout.addWidget(self.apply_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        # Initially disabled
        self.setEnabled(False)

    def load_control(self, control_name: str, current_action: str, comment: str = "",
                     modifier_combos: dict = None, haptic_strength: Optional[HapticStrength] = None,
                     haptic_speed: Optional[HapticSpeed] = None,
                     double_press_action: str = "", double_press_comment: str = "",
                     double_click_timeout: int = 300, on_release: bool = False):
        """Load a control for editing

        Args:
            control_name: Name of the control (e.g., 'side', 'knob_cw')
            current_action: Current action string (e.g., 'KEY_LEFTCTRL+KEY_C')
            comment: Optional comment/notes for this control
            modifier_combos: Dict of control_name -> (action, comment) for combos (optional)
            haptic_strength: Current haptic strength for rotary controls (None = use profile default)
            haptic_speed: Current haptic speed for rotary controls (None = use profile default)
            double_press_action: Current double-press action string (optional)
            double_press_comment: Comment for double-press action (optional)
            double_click_timeout: Current profile's double-click timeout in ms
            on_release: Whether this control fires on release (tap) instead of press
        """
        self.current_control = control_name
        self.current_dial = ROTARY_TO_DIAL.get(control_name)  # None for non-rotary
        self.control_label.setText(f"Editing: {control_name}")
        self.setEnabled(True)

        # Load comment
        self.comment_text.setPlainText(comment)

        # Show/hide haptic group based on whether this is a rotary control
        if self.current_dial:
            self.haptic_group.show()
            # Set haptic strength combo to current value
            if haptic_strength is None:
                self.haptic_combo.setCurrentIndex(0)  # "Use Profile Default"
            else:
                index = self.haptic_combo.findData(haptic_strength)
                if index >= 0:
                    self.haptic_combo.setCurrentIndex(index)
            # Set haptic speed combo to current value
            if haptic_speed is None:
                self.haptic_speed_combo.setCurrentIndex(0)  # "Use Profile Default"
            else:
                speed_index = self.haptic_speed_combo.findData(haptic_speed)
                if speed_index >= 0:
                    self.haptic_speed_combo.setCurrentIndex(speed_index)
        else:
            self.haptic_group.hide()

        # Show/hide double-press section based on control type
        # Rotary controls can't have double-press
        is_rotary = control_name in ('scroll_up', 'scroll_down', 'knob_cw', 'knob_ccw', 'dial_cw', 'dial_ccw')
        if is_rotary:
            self.double_press_section.hide()
        else:
            self.double_press_section.show()
            self.current_double_click_timeout = double_click_timeout
            self._current_dp_action = double_press_action
            self._current_dp_comment = double_press_comment
            self._update_dp_display()

        # Show/hide on-release section based on control type
        # Rotary controls can't have on-release (they're momentary)
        if is_rotary:
            self.on_release_section.hide()
        else:
            self.on_release_section.show()
            # Block signals while setting to avoid emitting change during load
            self.on_release_checkbox.blockSignals(True)
            self.on_release_checkbox.setChecked(on_release)
            self.on_release_checkbox.blockSignals(False)

        # Parse and populate the action UI
        self._parse_and_populate(current_action)

        # Clear combos table
        self.combos_table.setRowCount(0)

        # Check if this control can have modifier combinations (physical button only)
        can_have_combos = control_name in VALID_MODIFIER_BUTTONS

        if can_have_combos:
            # Show and enable modifier combinations for physical buttons
            self.combos_label.show()
            self.combos_table.show()
            self.add_combo_btn.show()
            self.combos_table.setEnabled(True)
            self.add_combo_btn.setEnabled(True)

            # Load combos into table if any
            if modifier_combos:
                for combo_control, (combo_action, combo_comment) in modifier_combos.items():
                    # Don't auto-select when loading existing combos
                    self._add_combo_row(combo_control, combo_action, combo_comment, select=False)

                # Select the first combo after loading all of them
                if self.combos_table.rowCount() > 0:
                    for row in range(self.combos_table.rowCount()):
                        if not self.combos_table.isRowHidden(row):
                            self.combos_table.selectRow(row)
                            break
        else:
            # Not a physical button - hide modifier combinations section entirely
            # (rotary controls can't be modifiers, so no need to show this)
            self.combos_label.hide()
            self.combos_table.hide()
            self.add_combo_btn.hide()

        logger.info(f"Loaded control for editing: {control_name}")

    def _parse_and_populate(self, action_str: str):
        """Parse action string and populate UI fields

        Args:
            action_str: Action string like 'KEY_LEFTCTRL+KEY_C' or 'REL_WHEEL:1'
        """
        # Reset UI
        self.ctrl_btn.setChecked(False)
        self.alt_btn.setChecked(False)
        self.shift_btn.setChecked(False)
        self.super_btn.setChecked(False)
        self.key_input.clear()
        self.special_key_combo.setCurrentIndex(0)

        # Reset mouse modifiers
        self.mouse_ctrl_btn.setChecked(False)
        self.mouse_alt_btn.setChecked(False)
        self.mouse_shift_btn.setChecked(False)
        self.mouse_super_btn.setChecked(False)

        if not action_str or action_str == "(none)" or action_str == "(unmapped)":
            self.action_type_combo.setCurrentText("None")
            return

        # Check if it's a mouse action (handle both raw and human-readable formats)
        # Also check for compound actions with modifiers like "KEY_LEFTCTRL+REL_WHEEL:1"
        # Raw patterns
        mouse_action_patterns = ["REL_WHEEL:", "REL_HWHEEL:", "BTN_LEFT", "BTN_RIGHT", "BTN_MIDDLE"]
        # Human-readable patterns (for when action comes from display text)
        mouse_readable_patterns = ["Scroll Up", "Scroll Down", "Scroll Left", "Scroll Right",
                                   "Left Click", "Right Click", "Middle Click"]
        has_mouse_action = (any(pattern in action_str for pattern in mouse_action_patterns) or
                           any(pattern in action_str for pattern in mouse_readable_patterns))

        if action_str.startswith("Wheel ") or action_str.startswith("Scroll "):
            self.action_type_combo.setCurrentText("Mouse")
            # Parse direction from human-readable format
            if "Up" in action_str:
                self.mouse_direction_combo.setCurrentText("Scroll Up")
            elif "Down" in action_str:
                self.mouse_direction_combo.setCurrentText("Scroll Down")
            elif "Left" in action_str:
                self.mouse_direction_combo.setCurrentText("Scroll Left")
            elif "Right" in action_str:
                self.mouse_direction_combo.setCurrentText("Scroll Right")
            return
        elif has_mouse_action:
            # Mouse action (possibly with modifiers)
            self.action_type_combo.setCurrentText("Mouse")

            # Parse modifiers and mouse action from compound string
            parts = action_str.split("+")
            for part in parts:
                part = part.strip()
                part_upper = part.upper()

                # Check for modifiers (both raw KEY_LEFT* and human-readable formats)
                if "CTRL" in part_upper:
                    self.mouse_ctrl_btn.setChecked(True)
                elif "ALT" in part_upper:
                    self.mouse_alt_btn.setChecked(True)
                elif "SHIFT" in part_upper:
                    self.mouse_shift_btn.setChecked(True)
                elif "META" in part_upper or "SUPER" in part_upper:
                    self.mouse_super_btn.setChecked(True)
                # Check for mouse actions (raw format)
                elif part.startswith("REL_WHEEL:"):
                    value = int(part.split(":")[1])
                    if value > 0:
                        self.mouse_direction_combo.setCurrentText("Scroll Up")
                    else:
                        self.mouse_direction_combo.setCurrentText("Scroll Down")
                elif part.startswith("REL_HWHEEL:"):
                    value = int(part.split(":")[1])
                    if value > 0:
                        self.mouse_direction_combo.setCurrentText("Scroll Right")
                    else:
                        self.mouse_direction_combo.setCurrentText("Scroll Left")
                elif part == "BTN_LEFT":
                    self.mouse_direction_combo.setCurrentText("Left Click")
                elif part == "BTN_RIGHT":
                    self.mouse_direction_combo.setCurrentText("Right Click")
                elif part == "BTN_MIDDLE":
                    self.mouse_direction_combo.setCurrentText("Middle Click")
                # Check for mouse actions (human-readable format)
                elif part == "Scroll Up":
                    self.mouse_direction_combo.setCurrentText("Scroll Up")
                elif part == "Scroll Down":
                    self.mouse_direction_combo.setCurrentText("Scroll Down")
                elif part == "Scroll Left":
                    self.mouse_direction_combo.setCurrentText("Scroll Left")
                elif part == "Scroll Right":
                    self.mouse_direction_combo.setCurrentText("Scroll Right")
                elif part == "Left Click":
                    self.mouse_direction_combo.setCurrentText("Left Click")
                elif part == "Right Click":
                    self.mouse_direction_combo.setCurrentText("Right Click")
                elif part == "Middle Click":
                    self.mouse_direction_combo.setCurrentText("Middle Click")
            return
        elif action_str.startswith("WHEEL:") or action_str.startswith("HWHEEL:"):
            # Legacy format support (no modifiers)
            self.action_type_combo.setCurrentText("Mouse")
            if action_str.startswith("WHEEL:"):
                value = int(action_str.split(":")[1])
                if value > 0:
                    self.mouse_direction_combo.setCurrentText("Scroll Up")
                else:
                    self.mouse_direction_combo.setCurrentText("Scroll Down")
            elif action_str.startswith("HWHEEL:"):
                value = int(action_str.split(":")[1])
                if value > 0:
                    self.mouse_direction_combo.setCurrentText("Scroll Right")
                else:
                    self.mouse_direction_combo.setCurrentText("Scroll Left")
            return
        # Check if it's a mouse button action (human-readable only, raw handled above)
        elif action_str in ("Left Click", "Right Click", "Middle Click"):
            self.action_type_combo.setCurrentText("Mouse")
            self.mouse_direction_combo.setCurrentText(action_str)
            return

        # It's a keyboard action
        self.action_type_combo.setCurrentText("Keyboard")

        # Parse key combination
        parts = action_str.split("+")
        for part in parts:
            part = part.strip()
            part_upper = part.upper()
            if "CTRL" in part_upper:
                self.ctrl_btn.setChecked(True)
            elif "ALT" in part_upper:
                self.alt_btn.setChecked(True)
            elif "SHIFT" in part_upper:
                self.shift_btn.setChecked(True)
            elif "META" in part_upper or "SUPER" in part_upper:
                self.super_btn.setChecked(True)
            else:
                # It's the actual key
                key_part = part
                full_key = key_part if key_part.startswith("KEY_") else f"KEY_{key_part}"

                # Check if it maps to a single character (letter, number, symbol)
                short = full_key[4:]  # Remove KEY_ prefix
                is_single = (short.upper() in KEYCODE_TO_CHAR or len(short) == 1)

                if is_single:
                    self.key_input.set_from_key_name(full_key.upper(), get_system_display_hints())
                else:
                    # It's a special key name - try to match in special keys dropdown
                    found = False
                    part_normalized = short.lower().replace(' ', '').replace('_', '')

                    for i in range(self.special_key_combo.count()):
                        item_text = self.special_key_combo.itemText(i)
                        item_normalized = item_text.lower().replace(' ', '').replace('_', '')

                        if item_text.lower() == short.lower():
                            self.special_key_combo.setCurrentIndex(i)
                            found = True
                            break
                        elif item_normalized == part_normalized:
                            self.special_key_combo.setCurrentIndex(i)
                            found = True
                            break

                    if not found:
                        logger.warning(f"Could not parse key: {short}")
                        self.special_key_combo.setCurrentIndex(0)

    def _on_action_type_changed(self, action_type: str):
        """Handle action type change"""
        # Check if current control is rotary (they never have double-press)
        is_rotary = self.current_control in ('scroll_up', 'scroll_down', 'knob_cw', 'knob_ccw', 'dial_cw', 'dial_ccw')

        if action_type == "Keyboard":
            self.keyboard_group.show()
            self.mouse_group.hide()
            # Enable double-press for keyboard actions (unless rotary)
            if not is_rotary:
                self.double_press_section.show()
                self.double_press_section.setEnabled(True)
        elif action_type == "Mouse":
            self.keyboard_group.hide()
            self.mouse_group.show()
            # Disable (gray out) double-press for mouse actions (not practical)
            if not is_rotary:
                self.double_press_section.show()
                self.double_press_section.setEnabled(False)
        else:  # None
            self.keyboard_group.hide()
            self.mouse_group.hide()
            # Disable double-press for None
            if not is_rotary:
                self.double_press_section.show()
                self.double_press_section.setEnabled(False)

    def _on_key_input_changed(self, text: str):
        """Handle key input text change - clear special key dropdown"""
        if text:
            self.special_key_combo.setCurrentIndex(0)

    def _on_special_key_changed(self, key_name: str):
        """Handle special key dropdown change - clear text input"""
        if key_name and key_name != "None" and SPECIAL_KEYS.get(key_name) is not None:
            self.key_input.clear()

    def _on_apply(self):
        """Handle Apply button click"""
        if not self.current_control:
            return

        # Build action string from keyboard/mouse UI
        action_str = self._build_action_string()
        logger.info(f"Apply: {self.current_control} -> {action_str}")

        # Emit action change
        self.action_changed.emit(self.current_control, action_str)

        # Emit comment (always, even if empty)
        comment = self.comment_text.toPlainText().strip()
        self.comment_changed.emit(self.current_control, comment)

        # Emit double-press action change and on-release state (for non-rotary controls)
        is_rotary = self.current_control in ('scroll_up', 'scroll_down', 'knob_cw', 'knob_ccw', 'dial_cw', 'dial_ccw')
        if not is_rotary:
            dp_action = self._build_dp_action_string()
            dp_comment = self._get_dp_comment()
            self.double_press_action_changed.emit(self.current_control, dp_action)
            self.double_press_comment_changed.emit(self.current_control, dp_comment)
            logger.info(f"Apply double-press: {self.current_control} -> {dp_action or '(none)'}")

            # Emit on-release state
            on_release = self.on_release_checkbox.isChecked()
            self.on_release_changed.emit(self.current_control, on_release)
            logger.info(f"Apply on-release: {self.current_control} -> {on_release}")

        # Emit haptic change for rotary controls
        if self.current_dial:
            haptic_strength = self.haptic_combo.currentData()  # None or HapticStrength
            haptic_speed = self.haptic_speed_combo.currentData()  # None or HapticSpeed
            self.haptic_changed.emit(self.current_dial, haptic_strength, haptic_speed)
            logger.info(f"Apply haptic: {self.current_dial} -> strength={haptic_strength}, speed={haptic_speed}")

        # If this is a physical button, check if there are modifier combinations
        if self.current_control in VALID_MODIFIER_BUTTONS:
            # Extract combos from table
            combos = {}
            for row in range(self.combos_table.rowCount()):
                control_item = self.combos_table.item(row, 0)
                action_item = self.combos_table.item(row, 1)
                comment_item = self.combos_table.item(row, 2)

                if control_item and action_item:
                    control_name = control_item.text().strip()
                    # Get raw action string from UserRole data
                    action = action_item.data(Qt.UserRole) or action_item.text().strip()
                    combo_comment = comment_item.text().strip() if comment_item else ""

                    if control_name and action:
                        combos[control_name] = (action, combo_comment)

            # Build modifier config
            # A button IS a modifier if it has combinations
            is_modifier = len(combos) > 0

            modifier_config = {
                'is_modifier': is_modifier,
                'base_action': action_str,
                'base_action_comment': '',
                'combos': combos
            }

            self.modifier_config_changed.emit(self.current_control, modifier_config)
            logger.info(f"Apply modifier config: {self.current_control} - is_modifier={is_modifier}, {len(combos)} combos")

    def _build_action_string(self) -> str:
        """Build action string from current UI state

        Returns:
            Action string like 'KEY_LEFTCTRL+KEY_C' or 'REL_WHEEL:1'
        """
        action_type = self.action_type_combo.currentText()

        if action_type == "None":
            return "none"

        if action_type == "Mouse":
            parts = []

            # Add mouse modifiers
            if self.mouse_ctrl_btn.isChecked():
                parts.append("KEY_LEFTCTRL")
            if self.mouse_alt_btn.isChecked():
                parts.append("KEY_LEFTALT")
            if self.mouse_shift_btn.isChecked():
                parts.append("KEY_LEFTSHIFT")
            if self.mouse_super_btn.isChecked():
                parts.append("KEY_LEFTMETA")

            # Add mouse action
            action = self.mouse_direction_combo.currentText()
            if action == "Scroll Up":
                parts.append("REL_WHEEL:1")
            elif action == "Scroll Down":
                parts.append("REL_WHEEL:-1")
            elif action == "Scroll Left":
                parts.append("REL_HWHEEL:-1")
            elif action == "Scroll Right":
                parts.append("REL_HWHEEL:1")
            elif action == "Left Click":
                parts.append("BTN_LEFT")
            elif action == "Right Click":
                parts.append("BTN_RIGHT")
            elif action == "Middle Click":
                parts.append("BTN_MIDDLE")

            return "+".join(parts) if parts else "none"

        # Keyboard action
        parts = []

        # Add modifiers
        if self.ctrl_btn.isChecked():
            parts.append("KEY_LEFTCTRL")
        if self.alt_btn.isChecked():
            parts.append("KEY_LEFTALT")
        if self.shift_btn.isChecked():
            parts.append("KEY_LEFTSHIFT")
        if self.super_btn.isChecked():
            parts.append("KEY_LEFTMETA")

        # Add key (prefer scancode-captured name, fall back to CHAR_TO_KEYCODE)
        captured = self.key_input.get_key_name()
        if captured:
            parts.append(captured)
        elif self.key_input.text():
            char = self.key_input.text()
            if char in CHAR_TO_KEYCODE:
                key_name = CHAR_TO_KEYCODE[char]
                parts.append(f"KEY_{key_name}")
            else:
                parts.append(f"KEY_{char.upper()}")
        elif self.special_key_combo.currentText() != "None":
            key_name = self.special_key_combo.currentText()
            if SPECIAL_KEYS.get(key_name):
                code = SPECIAL_KEYS[key_name]
                if code in _EVDEV_CODE_TO_NAME:
                    parts.append(_EVDEV_CODE_TO_NAME[code])

        return "+".join(parts) if parts else "none"

    def _on_combo_selection_changed(self):
        """Handle selection change in Modifier Combinations table"""
        selected = self.combos_table.selectedItems()
        if selected:
            row = self.combos_table.currentRow()
            control_item = self.combos_table.item(row, 0)
            if control_item:
                combo_control = control_item.text().strip()
                logger.debug(f"Combo selected: {combo_control}")
                self.combo_selected.emit(combo_control)

    def _on_add_combo(self):
        """Handle Add Combination button click"""
        # Get list of already-used controls
        used_controls = set()
        for row in range(self.combos_table.rowCount()):
            control_item = self.combos_table.item(row, 0)
            if control_item:
                used_controls.add(control_item.text().strip())

        # Open dialog to configure combination
        dialog = ComboConfigDialog(
            self, modifier_name=self.current_control, exclude_controls=used_controls,
            available_controls=get_model_controls(self._model)
        )
        if dialog.exec() == QDialog.Accepted:
            control = dialog.get_control()
            action = dialog.get_action()
            comment = dialog.get_comment()
            haptic = dialog.get_haptic()
            haptic_speed = dialog.get_haptic_speed()

            if control and action and action != "none":
                self._add_combo_row(control, action, comment)

                # Emit haptic change if this is a rotary control combo
                dial_name = ROTARY_TO_DIAL.get(control)
                if dial_name:
                    self.combo_haptic_changed.emit(self.current_control, dial_name, haptic, haptic_speed)
                    self.combo_haptics[(self.current_control, dial_name)] = haptic
                    self.combo_haptic_speeds[(self.current_control, dial_name)] = haptic_speed

    def _on_edit_combo(self, row: int):
        """Handle Edit button click for a combination"""
        # Get current values
        control_item = self.combos_table.item(row, 0)
        action_item = self.combos_table.item(row, 1)
        comment_item = self.combos_table.item(row, 2)

        control = control_item.text() if control_item else ""
        action = action_item.data(Qt.UserRole) if action_item else ""  # Get raw action string
        comment = comment_item.text() if comment_item else ""

        # Get current haptic settings for this combo (if it's a rotary)
        dial_name = ROTARY_TO_DIAL.get(control)
        current_haptic = None
        current_haptic_speed = None
        if dial_name:
            current_haptic = self.combo_haptics.get((self.current_control, dial_name))
            current_haptic_speed = self.combo_haptic_speeds.get((self.current_control, dial_name))

        # Get list of already-used controls (excluding the one being edited)
        used_controls = set()
        for r in range(self.combos_table.rowCount()):
            if r != row:  # Skip the row being edited
                c_item = self.combos_table.item(r, 0)
                if c_item:
                    used_controls.add(c_item.text().strip())

        # Open dialog with current values
        dialog = ComboConfigDialog(self, modifier_name=self.current_control,
                                   control_name=control, action=action, comment=comment,
                                   exclude_controls=used_controls, haptic_strength=current_haptic,
                                   haptic_speed=current_haptic_speed,
                                   available_controls=get_model_controls(self._model))
        if dialog.exec() == QDialog.Accepted:
            new_control = dialog.get_control()
            new_action = dialog.get_action()
            new_comment = dialog.get_comment()
            new_haptic = dialog.get_haptic()
            new_haptic_speed = dialog.get_haptic_speed()

            if new_control and new_action and new_action != "none":
                # Update row
                control_item.setText(new_control)

                # Store raw action and display readable version
                readable_action = self._action_to_readable(new_action, get_system_display_hints())
                action_item.setText(readable_action)
                action_item.setData(Qt.UserRole, new_action)

                comment_item.setText(new_comment)

                # Emit haptic change if this is a rotary control combo
                new_dial_name = ROTARY_TO_DIAL.get(new_control)
                if new_dial_name:
                    self.combo_haptic_changed.emit(self.current_control, new_dial_name, new_haptic, new_haptic_speed)
                    self.combo_haptics[(self.current_control, new_dial_name)] = new_haptic
                    self.combo_haptic_speeds[(self.current_control, new_dial_name)] = new_haptic_speed

    def _add_combo_row(self, control_name: str, action: str, comment: str, select: bool = True):
        """Add a row to the combinations table

        Args:
            control_name: Name of the control for this combo
            action: Action string
            comment: Comment text
            select: Whether to select the newly added row (default True)
        """
        row = self.combos_table.rowCount()
        self.combos_table.insertRow(row)

        # Control name
        control_item = QTableWidgetItem(control_name)
        self.combos_table.setItem(row, 0, control_item)
        self.combos_table.setRowHidden(
            row, control_name not in get_model_controls(self._model)
        )

        # Action (display readable, store raw)
        readable_action = self._action_to_readable(action, get_system_display_hints())
        action_item = QTableWidgetItem(readable_action)
        action_item.setData(Qt.UserRole, action)  # Store raw action string
        self.combos_table.setItem(row, 1, action_item)

        # Comment
        comment_item = QTableWidgetItem(comment)
        self.combos_table.setItem(row, 2, comment_item)

        # Buttons
        button_widget = QWidget()
        button_layout = QHBoxLayout(button_widget)
        button_layout.setContentsMargins(2, 2, 2, 2)

        # Edit button with icon
        edit_btn = QPushButton()
        edit_btn.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_FileDialogDetailedView))
        edit_btn.setToolTip("Edit this combination")
        edit_btn.setMaximumWidth(32)
        edit_btn.clicked.connect(lambda: self._on_edit_combo(row))
        button_layout.addWidget(edit_btn)

        # Delete button with icon
        delete_btn = QPushButton()
        delete_btn.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_TrashIcon))
        delete_btn.setToolTip("Delete this combination")
        delete_btn.setMaximumWidth(32)
        delete_btn.clicked.connect(lambda: self._delete_combo_row(row))
        button_layout.addWidget(delete_btn)

        self.combos_table.setCellWidget(row, 3, button_widget)

        # Select the newly added row if requested
        if select and not self.combos_table.isRowHidden(row):
            self.combos_table.selectRow(row)

    def _delete_combo_row(self, row: int):
        """Delete a combination row"""
        self.combos_table.removeRow(row)

    def _action_to_readable(self, action_str: str, display_hints: dict = None) -> str:
        """Convert action string to human-readable format

        Args:
            action_str: Action string like 'KEY_LEFTCTRL+KEY_C'
            display_hints: Optional dict of KEY_* name -> display character (locale-aware)

        Returns:
            Readable string like 'Ctrl+C'
        """
        if not action_str or action_str == "none":
            return "(none)"

        # Handle simple mouse actions (no modifiers)
        if action_str.startswith("REL_WHEEL:") and "+" not in action_str:
            value = action_str.split(":")[1]
            return f"Scroll {'Up' if int(value) > 0 else 'Down'}"
        elif action_str.startswith("REL_HWHEEL:") and "+" not in action_str:
            value = action_str.split(":")[1]
            return f"Scroll {'Right' if int(value) > 0 else 'Left'}"
        elif action_str == "BTN_LEFT":
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

        # Symbol key mapping (US layout fallback)
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

        # Parse keyboard action
        parts = action_str.split("+")
        readable_parts = []

        for part in parts:
            part = part.strip()
            # Convert KEY_ names to readable format
            if part.startswith("KEY_"):
                key_name = part[4:]  # Remove "KEY_" prefix

                # Special mappings
                if key_name == "LEFTCTRL" or key_name == "RIGHTCTRL":
                    readable_parts.append("Ctrl")
                elif key_name == "LEFTALT" or key_name == "RIGHTALT":
                    readable_parts.append("Alt")
                elif key_name == "LEFTSHIFT" or key_name == "RIGHTSHIFT":
                    readable_parts.append("Shift")
                elif key_name == "LEFTMETA" or key_name == "RIGHTMETA":
                    readable_parts.append("Super")
                elif key_name == "SPACE":
                    readable_parts.append("Space")
                elif key_name == "ENTER":
                    readable_parts.append("Enter")
                elif key_name == "ESC":
                    readable_parts.append("Esc")
                # Check display hints first (locale-aware), then fall back to SYMBOL_MAP
                elif display_hints and part in display_hints:
                    readable_parts.append(display_hints[part])
                elif key_name in SYMBOL_MAP:
                    readable_parts.append(SYMBOL_MAP[key_name])
                elif len(key_name) == 1:
                    readable_parts.append(key_name)
                else:
                    # Capitalize first letter of other keys
                    readable_parts.append(key_name.capitalize())
            else:
                # Check if it's a mouse action part
                mouse_readable = mouse_part_to_readable(part)
                if mouse_readable:
                    readable_parts.append(mouse_readable)
                else:
                    readable_parts.append(part)

        return "+".join(readable_parts)

    # Double-press action methods

    def _update_dp_display(self):
        """Update the double-press action label display"""
        if self._current_dp_action:
            readable = self._action_to_readable(self._current_dp_action, get_system_display_hints())
            self.dp_action_label.setText(readable)
            self.dp_action_label.setStyleSheet("")  # Normal color
            self.dp_clear_btn.setEnabled(True)
        else:
            self.dp_action_label.setText("(none)")
            self.dp_action_label.setStyleSheet(muted_label_style())
            self.dp_clear_btn.setEnabled(False)

    def _on_configure_double_press(self):
        """Open dialog to configure double-press action"""
        dialog = DoublePressDialog(
            self,
            control_name=self.current_control,
            action=self._current_dp_action,
            comment=self._current_dp_comment,
            timeout=self.current_double_click_timeout
        )

        if dialog.exec() == QDialog.Accepted:
            self._current_dp_action = dialog.get_action()
            self._current_dp_comment = dialog.get_comment()
            self._update_dp_display()

    def _on_dp_clear(self):
        """Clear the double-press action"""
        self._current_dp_action = ""
        self._current_dp_comment = ""
        self._update_dp_display()

    def _build_dp_action_string(self) -> str:
        """Get the current double-press action string"""
        return self._current_dp_action if hasattr(self, '_current_dp_action') else ""

    def _get_dp_comment(self) -> str:
        """Get the current double-press comment"""
        return self._current_dp_comment if hasattr(self, '_current_dp_comment') else ""

    # On-release methods

    def _on_on_release_changed(self, state):
        """Handle on-release checkbox state change (UI feedback only, Apply saves)"""
        if self.current_control:
            enabled = state == Qt.Checked
            # Don't emit signal here - it's emitted in _on_apply
            # This is just for immediate UI feedback/logging
            logger.debug(f"On-release checkbox {'checked' if enabled else 'unchecked'} for {self.current_control}")
