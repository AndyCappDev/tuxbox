#!/usr/bin/env python3
"""Global settings dialog

Edits the settings that apply to the whole application rather than to one
profile: the [device] section of config.conf (driver behaviour) and the [gui]
section (the configuration window itself, currently its language). Per-profile
settings live in ProfileSettingsDialog.
"""

import logging
from typing import Dict

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QLabel, QGroupBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QMessageBox
)
from PySide6.QtCore import QSize

from tuxbox.config_loader import (
    load_device_config, load_gui_config, DEFAULT_CONNECTION_MODE,
    VALID_CONNECTION_MODES, DEFAULT_CONTROLLER_MODEL, VALID_CONTROLLER_MODELS,
    DEFAULT_CTRL_KEY
)
from tuxbox.window_monitor import (
    DEFAULT_POLL_INTERVAL, MIN_POLL_INTERVAL, MAX_POLL_INTERVAL
)
from tuxbox.gui.theme import muted_label_style
from tuxbox.i18n import _, N_, available_languages

logger = logging.getLogger(__name__)

DEFAULT_USB_PORT = "/dev/ttyACM0"

# Stored in [gui] language when the interface should follow the system locale.
AUTOMATIC_LANGUAGE = 'auto'

# Each mode with the text shown to the user. Deliberately short: a long item
# makes the combo demand more width than the dialog has at large font sizes,
# which elides the text and squeezes out the "Connect via:" label. The help
# text below the combo carries the explanation instead.
# Labels are English source strings marked with N_ and translated when the
# combo is filled: a module-level constant cannot be translated at import time.
CONNECTION_CHOICES = (
    ('auto', N_("Automatic")),
    ('usb', N_("USB only")),
    ('ble', N_("Bluetooth only")),
)

CONNECTION_HELP = {
    'auto': N_("Uses the cable when it is plugged in and falls back to Bluetooth "
               "otherwise, switching to USB as soon as the cable appears."),
    'usb': N_("The Bluetooth radio is never used. Choose this if you always "
              "connect by cable - on a laptop it stops the driver scanning for a "
              "device that is never there."),
    'ble': N_("The USB ports are never checked. Choose this if you only ever "
              "connect over Bluetooth."),
}

# Which key the driver sends for Ctrl. Kept short for the same reason as
# CONNECTION_CHOICES.
CTRL_KEY_CHOICES = (
    ('left', N_("Left Ctrl")),
    ('right', N_("Right Ctrl")),
    ('capslock', N_("Caps Lock")),
)


DIALOG_WIDTH = 560

# Width the help text is laid out against before the dialog has been shown.
# Roughly the dialog width less the form's label column and margins.
HELP_TEXT_WIDTH = 400


class HelpLabel(QLabel):
    """Muted, word-wrapped help text that reports the height it really needs

    A word-wrapped QLabel's size hint describes a single line, so a dialog
    holding several of them budgets too little vertical space. The shortfall
    comes out of whatever else can shrink - here the spin boxes, which end up
    clipped until the user resizes the dialog by hand. Reporting
    heightForWidth keeps the dialog's own hint honest, and the effect grows
    with the user's font size, so this cannot be papered over with a fixed
    minimum height.
    """

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setStyleSheet(muted_label_style(10))

    def _wrapped_height(self) -> int:
        return self.heightForWidth(self.width() or HELP_TEXT_WIDTH)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(hint.width(), HELP_TEXT_WIDTH),
                     max(hint.height(), self._wrapped_height()))

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(hint.width(), max(hint.height(), self._wrapped_height()))

    def resizeEvent(self, event):
        # Once the real width is known, hold the height the text needs at it.
        super().resizeEvent(event)
        self.setMinimumHeight(self.heightForWidth(self.width()))


def _keep_full_height(widget):
    """Stop a widget being clipped when the dialog is short of space

    Spin boxes and combo boxes accept a minimum height below the one they
    need to draw themselves, so a layout under pressure clips them rather
    than making the dialog taller. Pinning the minimum to the height they ask
    for pushes that pressure back into the dialog's own minimum size.
    """
    widget.setMinimumHeight(widget.sizeHint().height())
    return widget


class DeviceSettingsDialog(QDialog):
    """Dialog for editing global driver settings"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Current values, with defaults filled in for anything unset. An unset
        # setting is written back only if the user changes it, so untouched
        # config files keep their comments and stay minimal.
        self._original = load_device_config()
        self._original_gui = load_gui_config()

        self._init_ui()

        # Size to what the content asks for, then refuse to go below it. The
        # help text is word-wrapped, so leaving the dialog free to open at its
        # layout minimum clips the spin boxes until the user drags it taller.
        self.setMinimumWidth(DIALOG_WIDTH)
        self.adjustSize()
        self.setMinimumHeight(self.height())

    # --- UI construction ---------------------------------------------------

    def _init_ui(self):
        self.setWindowTitle(_("Global Settings"))
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_language_group())
        layout.addWidget(self._build_controller_group())
        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_usb_group())
        layout.addWidget(self._build_behaviour_group())

        note = HelpLabel(
            _("These settings apply across profiles. To change settings "
            "for one profile, use the gear button in the profile list.")
        )
        layout.addWidget(note)

        layout.addLayout(self._build_buttons())

    def _build_language_group(self) -> QGroupBox:
        group = QGroupBox(_("Language"))
        form = QFormLayout(group)
        form.setVerticalSpacing(8)

        self.language_combo = QComboBox()
        self.language_combo.addItem(_("Same as the system"), AUTOMATIC_LANGUAGE)
        # Every language with a compiled catalog, so a new translation only has
        # to be dropped into tuxbox/locale to appear here.
        for code, name in available_languages():
            self.language_combo.addItem(name, code)

        current = self._original_gui.get('language', AUTOMATIC_LANGUAGE)
        index = self.language_combo.findData(current)
        self.language_combo.setCurrentIndex(index if index >= 0 else 0)
        form.addRow(_("Interface language:"), _keep_full_height(self.language_combo))

        form.addRow(HelpLabel(
            _("Applies to this window and its dialogs. It takes effect the next "
              "time the window is opened.")
        ))

        return group

    def _build_controller_group(self) -> QGroupBox:
        group = QGroupBox(_("Controller view"))
        form = QFormLayout(group)
        self.model_combo = QComboBox()
        for model in VALID_CONTROLLER_MODELS:
            self.model_combo.addItem(_('TourBox %s') % (model.title(),), model)
        current = self._original.get('controller_model', DEFAULT_CONTROLLER_MODEL)
        index = self.model_combo.findData(current)
        self.model_combo.setCurrentIndex(index if index >= 0 else 0)
        form.addRow(_("Model:"), _keep_full_height(self.model_combo))
        form.addRow(HelpLabel(
            _("Choose the controller artwork and available controls. Mappings for "
            "controls the model lacks are hidden, not deleted.")
        ))
        return group

    def _build_connection_group(self) -> QGroupBox:
        group = QGroupBox(_("Connection"))
        form = QFormLayout(group)
        form.setVerticalSpacing(8)

        self.connection_combo = QComboBox()
        for mode, label in CONNECTION_CHOICES:
            self.connection_combo.addItem(_(label), mode)

        current = self._original.get('connection', DEFAULT_CONNECTION_MODE)
        if current not in VALID_CONNECTION_MODES:
            current = DEFAULT_CONNECTION_MODE
        index = self.connection_combo.findData(current)
        self.connection_combo.setCurrentIndex(index if index >= 0 else 0)
        self.connection_combo.currentIndexChanged.connect(self._update_connection_help)

        form.addRow(_("Connect via:"), _keep_full_height(self.connection_combo))

        self.connection_help = HelpLabel("")
        form.addRow(self.connection_help)
        self._update_connection_help()

        return group

    def _build_usb_group(self) -> QGroupBox:
        group = QGroupBox(_("USB"))
        form = QFormLayout(group)
        form.setVerticalSpacing(8)

        self.usb_port_edit = QLineEdit(self._original.get('usb_port', ''))
        self.usb_port_edit.setPlaceholderText(_('%s (detected automatically)') % (DEFAULT_USB_PORT,))
        form.addRow(_("Serial port:"), _keep_full_height(self.usb_port_edit))

        info = HelpLabel(
            _("Leave empty unless your TourBox appears on a non-standard port. "
            "The driver probes all /dev/ttyACM* devices either way.")
        )
        form.addRow(info)

        return group

    def _build_behaviour_group(self) -> QGroupBox:
        group = QGroupBox(_("Behaviour"))
        form = QFormLayout(group)
        form.setVerticalSpacing(8)

        # Haptics
        self.force_haptics_check = QCheckBox(_("Force haptic feedback on"))
        self.force_haptics_check.setChecked(bool(self._original.get('force_haptics', False)))
        form.addRow(_("Haptics:"), _keep_full_height(self.force_haptics_check))

        haptics_info = HelpLabel(
            _("Sends haptic settings even when a profile leaves them at their defaults.")
        )
        form.addRow(haptics_info)

        # Modifier delay
        self.modifier_delay_spin = QSpinBox()
        self.modifier_delay_spin.setRange(0, 100)
        self.modifier_delay_spin.setSingleStep(5)
        self.modifier_delay_spin.setSuffix(" ms")
        self.modifier_delay_spin.setFixedWidth(90)
        self.modifier_delay_spin.setValue(int(self._original.get('modifier_delay', 0)))
        form.addRow(_("Modifier delay:"), _keep_full_height(self.modifier_delay_spin))

        delay_info = HelpLabel(
            _("Pause between modifier keys and the key they modify. Raise to 20-50 ms "
            "if apps like GIMP miss key combos. Profiles can override this.")
        )
        form.addRow(delay_info)

        # Which key is sent for Ctrl
        self.ctrl_key_combo = QComboBox()
        for choice, label in CTRL_KEY_CHOICES:
            self.ctrl_key_combo.addItem(_(label), choice)
        index = self.ctrl_key_combo.findData(
            self._original.get('ctrl_key', DEFAULT_CTRL_KEY)
        )
        self.ctrl_key_combo.setCurrentIndex(index if index >= 0 else 0)
        form.addRow(_("Send Ctrl as:"), _keep_full_height(self.ctrl_key_combo))

        ctrl_key_info = HelpLabel(
            _("If you swapped Ctrl and Caps Lock in your keyboard settings, the swap "
            "applies to the TourBox too and its Ctrl shortcuts type Caps Lock. "
            "Choose Right Ctrl or Caps Lock so they work again.")
        )
        form.addRow(ctrl_key_info)

        # Window poll interval
        self.poll_interval_spin = QDoubleSpinBox()
        self.poll_interval_spin.setRange(MIN_POLL_INTERVAL, MAX_POLL_INTERVAL)
        self.poll_interval_spin.setSingleStep(0.1)
        self.poll_interval_spin.setDecimals(1)
        self.poll_interval_spin.setSuffix(" s")
        self.poll_interval_spin.setFixedWidth(90)
        self.poll_interval_spin.setValue(
            float(self._original.get('window_poll_interval', DEFAULT_POLL_INTERVAL))
        )
        form.addRow(_("Window check:"), _keep_full_height(self.poll_interval_spin))

        poll_info = HelpLabel(
            _("How often the focused window is checked for automatic profile switching. "
            "Not used on KDE Plasma, which reports window changes as they happen.")
        )
        form.addRow(poll_info)

        return group

    def _build_buttons(self) -> QHBoxLayout:
        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel_button = QPushButton(_("Cancel"))
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)

        save_button = QPushButton(_("Save"))
        save_button.setDefault(True)
        save_button.clicked.connect(self._on_save)
        buttons.addWidget(save_button)

        return buttons

    def _update_connection_help(self):
        mode = self.connection_combo.currentData()
        self.connection_help.setText(_(CONNECTION_HELP.get(mode, "")))

    # --- Saving ------------------------------------------------------------

    def _on_save(self):
        port = self.usb_port_edit.text().strip()
        if port and not port.startswith('/dev/'):
            QMessageBox.warning(
                self,
                _("Invalid Serial Port"),
                _("'%s' does not look like a serial port.\n\nEnter a device path such as /dev/ttyACM0, or leave the field empty to let the driver find the TourBox itself.") % (port,)
            )
            self.usb_port_edit.setFocus()
            return

        self.accept()

    def get_changes(self) -> Dict:
        """Return the settings the user actually changed

        Only changed settings are returned, so saving does not stamp defaults
        into a config file that never mentioned them. A value of None means
        the setting should be removed and the default restored.
        """
        changes = {}

        model = self.model_combo.currentData()
        if model != self._original.get('controller_model', DEFAULT_CONTROLLER_MODEL):
            changes['controller_model'] = (
                None if model == DEFAULT_CONTROLLER_MODEL else model
            )

        connection = self.connection_combo.currentData()
        if connection != self._original.get('connection', DEFAULT_CONNECTION_MODE):
            # 'auto' is the default, so record it as a removal rather than
            # writing a line that only restates the default.
            changes['connection'] = None if connection == DEFAULT_CONNECTION_MODE else connection

        port = self.usb_port_edit.text().strip()
        if port != self._original.get('usb_port', ''):
            changes['usb_port'] = port or None

        haptics = self.force_haptics_check.isChecked()
        if haptics != bool(self._original.get('force_haptics', False)):
            changes['force_haptics'] = haptics if haptics else None

        delay = self.modifier_delay_spin.value()
        if delay != int(self._original.get('modifier_delay', 0)):
            changes['modifier_delay'] = delay if delay else None

        ctrl_key = self.ctrl_key_combo.currentData()
        if ctrl_key != self._original.get('ctrl_key', DEFAULT_CTRL_KEY):
            changes['ctrl_key'] = None if ctrl_key == DEFAULT_CTRL_KEY else ctrl_key

        interval = round(self.poll_interval_spin.value(), 1)
        original_interval = float(self._original.get('window_poll_interval', DEFAULT_POLL_INTERVAL))
        if interval != round(original_interval, 1):
            changes['window_poll_interval'] = (
                None if interval == DEFAULT_POLL_INTERVAL else interval
            )

        return changes

    def get_language_changes(self) -> Dict:
        """Return the [gui] settings the user actually changed"""
        changes = {}

        language = self.language_combo.currentData()
        original = self._original_gui.get('language', AUTOMATIC_LANGUAGE)
        if language != original:
            # 'auto' is the default, so record it as a removal rather than
            # writing a line that only restates the default.
            changes['language'] = None if language == AUTOMATIC_LANGUAGE else language

        return changes
