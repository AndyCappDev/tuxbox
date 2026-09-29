#!/usr/bin/env python3
"""Main window for TuxBox Configuration GUI"""

import sys
import logging
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSplitter, QMessageBox, QDialog, QProgressDialog, QToolBar,
    QScrollArea, QFrame
)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QKeySequence, QIcon, QDesktopServices, QFontMetrics

# Import from GUI modules
from .profile_manager import ProfileManager
from .controls_list import ControlsList
from .controller_view import ControllerView
from .driver_manager import DriverManager
from .control_editor import ControlEditor, ROTARY_TO_DIAL
from .config_writer import (save_profile, save_profile_metadata, create_new_profile,
                            profile_exists_in_config, cleanup_old_backups,
                            save_modifier_config, save_mapping_comments, save_haptic_config)
from .keymap_util import get_system_display_hints

# Import from existing driver code
from tuxbox.config_loader import (
    load_profiles, load_device_config, DEFAULT_CONTROLLER_MODEL
)
from evdev import ecodes as e

logger = logging.getLogger(__name__)


class TuxBoxConfigWindow(QMainWindow):
    """Main configuration window for TuxBox"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TuxBox Configuration")
        # Keep the minimum small enough to fit short/scaled displays (e.g. a
        # 1920x1200 panel at 125% scaling leaves only ~926 logical px of height).
        # An oversized minimum makes Qt clamp the layout and clip the bottom of
        # the central widget, hiding the profile buttons.
        self.setMinimumSize(900, 560)
        self.resize(1280, 1024)

        # Set window icon
        self._set_window_icon()

        # Track current profile and modifications
        self.current_profile = None
        self.modified_mappings = {}  # control_name -> action_string
        self.modified_comments = {}  # control_name -> comment_string
        self.modified_modifiers = {}  # control_name -> modifier_config
        self.modified_haptic = {}  # dial_name -> HapticStrength (None means use profile default)
        self.modified_haptic_speed = {}  # dial_name -> HapticSpeed (None means use profile default)
        self.modified_combo_haptic = {}  # (modifier_name, dial_name) -> HapticStrength
        self.modified_combo_haptic_speed = {}  # (modifier_name, dial_name) -> HapticSpeed
        self.is_modified = False
        self.profile_original_names = {}  # Track original names of profiles (for renames)

        # Create menu bar
        self._create_menu_bar()

        # Create toolbar
        self._create_toolbar()

        # Ensure status bar is created and visible
        self.statusBar().setVisible(True)
        self.statusBar().showMessage("Initializing...")

        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Create main splitter (left side | right side)
        main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(main_splitter)

        # Left side container
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # Top left: Controller image
        model = load_device_config().get('controller_model', DEFAULT_CONTROLLER_MODEL)
        self.controller_view = ControllerView(model=model)
        self.controller_view.setMinimumSize(300, 220)
        self.controller_view.setMaximumHeight(410)  # Preferred height, but allowed to shrink
        left_layout.addWidget(self.controller_view, stretch=0)

        # Bottom left: Profiles manager
        self.profile_manager = ProfileManager()
        self.profile_manager.setMinimumSize(400, 160)
        self.profile_manager.profile_selected.connect(self._on_profile_selected)
        self.profile_manager.profiles_changed.connect(self._on_profiles_changed)
        self.profile_manager.profiles_reset.connect(self._on_profiles_reset)
        left_layout.addWidget(self.profile_manager, stretch=1)

        main_splitter.addWidget(left_widget)

        # Right side container
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # Top right: Controls list (expands to fill available space)
        self.controls_list = ControlsList(model=model)
        self.controls_list.setMinimumWidth(400)  # Minimum width only, height set in ControlsList
        self.controls_list.control_selected.connect(self._on_control_selected)
        right_layout.addWidget(self.controls_list, stretch=1)  # Stretch - table benefits from extra space

        # Bottom right: Control editor
        self.control_editor = ControlEditor()
        self.control_editor.set_model(model)
        self.control_editor.setMinimumWidth(400)
        self.control_editor.action_changed.connect(self._on_action_changed)
        self.control_editor.comment_changed.connect(self._on_comment_changed)
        self.control_editor.modifier_config_changed.connect(self._on_modifier_config_changed)
        self.control_editor.combo_selected.connect(self._on_combo_selected)
        self.control_editor.haptic_changed.connect(self._on_haptic_changed)
        self.control_editor.combo_haptic_changed.connect(self._on_combo_haptic_changed)
        self.control_editor.double_press_action_changed.connect(self._on_double_press_action_changed)
        self.control_editor.double_press_comment_changed.connect(self._on_double_press_comment_changed)
        self.control_editor.on_release_changed.connect(self._on_on_release_changed)
        right_layout.addWidget(self.control_editor, stretch=0)

        # The control editor has a tall stack of fixed-height rows and cannot
        # compress indefinitely. On short windows let the column scroll rather
        # than letting its rows overlap each other.
        right_scroll = QScrollArea()
        right_scroll.setWidget(right_widget)
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        main_splitter.addWidget(right_scroll)

        # Set initial splitter sizes (40% left, 60% right)
        main_splitter.setSizes([400, 600])

        logger.info("Main window initialized (initialization deferred)")

    def _create_menu_bar(self):
        """Create the menu bar"""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        # Save action
        self.save_action = QAction("&Save", self)
        self.save_action.setShortcut(QKeySequence.Save)
        self.save_action.setStatusTip("Save profile changes and apply configuration")
        self.save_action.triggered.connect(self._on_save)
        self.save_action.setEnabled(False)
        file_menu.addAction(self.save_action)

        file_menu.addSeparator()

        # Import Profile action
        import_action = QAction("&Import Profile...", self)
        import_action.setStatusTip("Import a profile from file")
        import_action.triggered.connect(self._on_menu_import_profile)
        file_menu.addAction(import_action)

        # Export Profile action
        export_action = QAction("&Export Profile...", self)
        export_action.setStatusTip("Export current profile to file")
        export_action.triggered.connect(self._on_menu_export_profile)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        # Settings action (global [device] settings)
        settings_action = QAction("&Global Settings...", self)
        settings_action.setStatusTip("Edit settings that apply to the whole driver")
        settings_action.triggered.connect(self._on_menu_settings)
        file_menu.addAction(settings_action)

        # Restart Driver action
        restart_driver_action = QAction("&Restart Driver", self)
        restart_driver_action.setStatusTip("Restart the TuxBox driver service and reload profiles")
        restart_driver_action.triggered.connect(self._on_restart_driver)
        file_menu.addAction(restart_driver_action)

        file_menu.addSeparator()

        # Quit action
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.setStatusTip("Quit application")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        # Check for Updates action
        self.check_updates_action = QAction("Check for &Updates...", self)
        self.check_updates_action.setStatusTip("Check GitHub for a newer version")
        self.check_updates_action.triggered.connect(self._check_for_updates)
        help_menu.addAction(self.check_updates_action)

        # User Guide action
        user_guide_action = QAction("&User Guide", self)
        user_guide_action.setStatusTip("Open the GUI User Guide documentation")
        user_guide_action.triggered.connect(self._open_user_guide)
        help_menu.addAction(user_guide_action)

        help_menu.addSeparator()

        # About action
        about_action = QAction("&About", self)
        about_action.setStatusTip("About TuxBox")
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_toolbar(self):
        """Create the toolbar"""
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)

        # Add save button
        toolbar.addAction(self.save_action)

    def _set_window_icon(self):
        """Set the window icon from assets"""
        import os
        from pathlib import Path

        # Get the path to the icon file
        # __file__ is the path to this module (main_window.py)
        assets_dir = Path(__file__).parent / "assets"
        icon_path = assets_dir / "tuxbox-icon.png"

        if icon_path.exists():
            icon = QIcon(str(icon_path))
            self.setWindowIcon(icon)
            logger.debug(f"Window icon set from {icon_path}")
        else:
            logger.warning(f"Icon file not found: {icon_path}")

    def showEvent(self, event):
        """Called when window is shown - perform initialization"""
        super().showEvent(event)

        # Only run initialization once
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

        # Check for migration before loading profiles
        self._check_migration()

        # Load profiles directly
        self._load_profiles()

        # Update status bar
        self.statusBar().showMessage("Ready")
        logger.info("Initialization complete")

    def _load_profiles(self):
        """Load profiles from configuration file"""
        try:
            profiles = load_profiles()

            if not profiles:
                QMessageBox.warning(
                    self,
                    "No Profiles Found",
                    "No profiles found in configuration.\n"
                    "Please check your configuration at ~/.config/tuxbox/"
                )
                self.statusBar().showMessage("No profiles found")
                return

            # Track original names of all loaded profiles (for detecting renames)
            # Use id(profile) as key since Profile objects aren't hashable
            self.profile_original_names = {id(profile): profile.name for profile in profiles}

            # Load profiles into UI
            self.profile_manager.load_profiles(profiles)
            self.statusBar().showMessage(f"Loaded {len(profiles)} profile(s)")

            logger.info(f"Loaded {len(profiles)} profiles from config")

        except Exception as e:
            error_msg = f"Error loading profiles: {e}"
            logger.error(error_msg, exc_info=True)
            QMessageBox.critical(
                self,
                "Error Loading Profiles",
                f"Failed to load configuration:\n{e}"
            )
            self.statusBar().showMessage("Error loading profiles")

    def _on_profile_selected(self, profile):
        """Handle profile selection

        Args:
            profile: Selected Profile object
        """
        logger.info(f"Profile selected: {profile.name}")

        # Check if there are unsaved changes (profile settings OR control mappings)
        if self.is_modified:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                f"Profile '{self.current_profile.name}' has unsaved changes.\n\n"
                "Do you want to save them before switching profiles?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save
            )

            if reply == QMessageBox.Save:
                # Save the changes (both profile metadata and control mappings)
                # Get the original name (before any renames) to check if profile exists
                original_name = self.profile_original_names.get(id(self.current_profile), self.current_profile.name)
                profile_exists = profile_exists_in_config(original_name)

                if not profile_exists:
                    # This is a new profile - create it
                    logger.info(f"Creating new profile: {self.current_profile.name}")
                    success = create_new_profile(self.current_profile)
                    # Update the original name tracker for the newly created profile
                    if success:
                        self.profile_original_names[id(self.current_profile)] = self.current_profile.name
                else:
                    # Existing profile - save metadata and mappings
                    # Determine if profile was renamed
                    old_name = original_name if original_name != self.current_profile.name else None

                    metadata_success = save_profile_metadata(self.current_profile, old_name)
                    # Update the original name tracker if profile was renamed
                    if old_name and metadata_success:
                        self.profile_original_names[id(self.current_profile)] = self.current_profile.name

                    mappings_success = True
                    if self.modified_mappings:
                        mappings_success = save_profile(self.current_profile, self.modified_mappings)

                    # Save haptic config
                    haptic_success = save_haptic_config(self.current_profile)

                    success = metadata_success and mappings_success and haptic_success

                if not success:
                    QMessageBox.critical(
                        self,
                        "Save Failed",
                        "Failed to save changes. Profile switch cancelled."
                    )
                    # Reselect the current profile
                    self.profile_manager.reselect_current_profile()
                    return
                cleanup_old_backups()
            elif reply == QMessageBox.Cancel:
                # Cancel the profile switch - reselect current profile
                self.profile_manager.reselect_current_profile()
                return
            elif reply == QMessageBox.Discard:
                # Discard changes and reload profile list to revert display
                logger.info(f"Discarding changes to {self.current_profile.name}")

                # IMPORTANT: Clear modifications FIRST before reloading profiles
                # to prevent infinite loop (reload triggers profile_selected signal)
                self.modified_mappings = {}
                self.is_modified = False

                # Reload the current profile to revert UI changes before switching
                # This will automatically select the first control
                self.controls_list.load_profile(self.current_profile)
                # Also need to reload profile list to revert any name/window matching changes
                from tuxbox.config_loader import load_profiles
                profiles = load_profiles()
                # Reset original names tracking
                self.profile_original_names = {id(profile): profile.name for profile in profiles}
                self.profile_manager.load_profiles(profiles)

        # Store current profile and reset modifications
        self.current_profile = profile
        self.modified_mappings = {}
        self.modified_comments = {}
        self.modified_modifiers = {}
        self.modified_haptic = {}
        self.modified_haptic_speed = {}
        self.modified_combo_haptic = {}
        self.modified_combo_haptic_speed = {}
        self.is_modified = False
        self._update_window_title()

        # Disable Save button
        self.save_action.setEnabled(False)

        self.statusBar().showMessage(f"Profile: {profile.name}")

        # Clear any highlighted control from previous profile
        self.controller_view.clear_highlight()

        # Load profile's controls into controls list (loads from saved data)
        # This will automatically select the first control, which will enable the editor
        self.controls_list.load_profile(profile)

    def _on_profiles_changed(self):
        """Handle profile metadata changes (name, window matching rules)"""
        logger.info("Profile settings changed")

        # Mark as modified (profile settings changed, need to save to config)
        self.is_modified = True
        self._update_window_title()

        # Enable save button
        self.save_action.setEnabled(True)

        self.statusBar().showMessage(f"Profile '{self.current_profile.name}' settings modified (not saved)")

    def _on_profiles_reset(self, profile):
        """Handle profiles reset (reload from config without unsaved changes check)

        This is called when deleting an unsaved profile to reset everything
        to the saved state without prompting for unsaved changes.

        Args:
            profile: Profile to switch to
        """
        logger.info(f"Profiles reset, switching to: {profile.name}")

        # Clear modifications and switch profile
        self.current_profile = profile
        self.modified_mappings = {}
        self.modified_comments = {}
        self.modified_modifiers = {}
        self.modified_haptic = {}
        self.modified_haptic_speed = {}
        self.modified_combo_haptic = {}
        self.modified_combo_haptic_speed = {}
        self.is_modified = False
        self._update_window_title()

        # Disable Save button
        self.save_action.setEnabled(False)

        self.statusBar().showMessage(f"Profile: {profile.name}")

        # Clear any highlighted control
        self.controller_view.clear_highlight()

        # Load profile's controls
        self.controls_list.load_profile(profile)

        # Disable control editor until a control is selected
        self.control_editor.setEnabled(False)

    def _get_raw_action_string(self, control_name: str) -> str:
        """Get the raw action string (e.g., 'KEY_LEFTCTRL+KEY_EQUAL') for a control.

        Checks modified_mappings first, then the profile's mapping/modifier data.
        """
        # Check pending modifications first
        if control_name in self.modified_mappings:
            return self.modified_mappings[control_name]

        if not self.current_profile:
            return ""

        # Modifier buttons use base_action
        if control_name in self.current_profile.modifier_buttons:
            return self.current_profile.modifier_base_actions.get(control_name, "")

        # Regular controls: reverse the hex-code mapping back to action string
        from tuxbox.config_loader import BUTTON_CODES
        if control_name not in BUTTON_CODES:
            return ""

        codes = BUTTON_CODES[control_name]
        if len(codes) < 2 or not self.current_profile.mapping:
            return ""

        press_code = bytes([codes[0]])
        events = self.current_profile.mapping.get(press_code, [])
        if not events:
            return ""

        parts = []
        for event_type, event_code, value in events:
            if event_type == e.EV_KEY and value == 1:
                # Find KEY_* or BTN_* name for this code
                for name, code in vars(e).items():
                    if (name.startswith('KEY_') or name.startswith('BTN_')) and isinstance(code, int) and code == event_code:
                        parts.append(name)
                        break
            elif event_type == e.EV_REL:
                for name, code in vars(e).items():
                    if name.startswith('REL_') and isinstance(code, int) and code == event_code:
                        parts.append(f"{name}:{value}")
                        break

        return "+".join(parts) if parts else ""

    def _on_control_selected(self, control_name: str):
        """Handle control selection from list

        Args:
            control_name: Name of selected control
        """
        logger.info(f"Control selected: {control_name}")

        # Check if this control is a modifier
        is_modifier = False
        if self.current_profile and control_name in self.current_profile.modifier_buttons:
            is_modifier = True

        # Highlight in controller view
        self.controller_view.highlight_control(control_name, is_modifier)

        # Get the raw action string for this control (e.g., 'KEY_LEFTCTRL+KEY_EQUAL')
        current_action = self._get_raw_action_string(control_name)

        # Get comment from profile
        comment = ""
        if self.current_profile:
            comment = self.current_profile.mapping_comments.get(control_name, "")

        # Get modifier combos if this is a physical button
        modifier_combos = {}
        if self.current_profile and control_name in self.current_profile.modifier_buttons:
            # Get combos for this modifier
            for (mod, ctrl), action_str in self.current_profile.modifier_mappings.items():
                if mod == control_name:
                    combo_comment = self.current_profile.modifier_combo_comments.get((mod, ctrl), "")
                    modifier_combos[ctrl] = (action_str, combo_comment)

        # Get haptic settings for rotary controls
        haptic_strength = None
        haptic_speed = None
        dial_name = ROTARY_TO_DIAL.get(control_name)
        if dial_name and self.current_profile:
            # Check modified_haptic first, then profile's dial_settings
            if dial_name in self.modified_haptic:
                haptic_strength = self.modified_haptic[dial_name]
            elif dial_name in self.current_profile.haptic_config.dial_settings:
                haptic_strength = self.current_profile.haptic_config.dial_settings[dial_name]
            # Check modified_haptic_speed first, then profile's dial_speed_settings
            if dial_name in self.modified_haptic_speed:
                haptic_speed = self.modified_haptic_speed[dial_name]
            elif dial_name in self.current_profile.haptic_config.dial_speed_settings:
                haptic_speed = self.current_profile.haptic_config.dial_speed_settings[dial_name]
            # Note: None values mean "use profile default"

        # Get double-press action and comment
        double_press_action = ""
        double_press_comment = ""
        double_click_timeout = 300
        on_release = False
        if self.current_profile:
            double_press_action = self.current_profile.double_press_actions.get(control_name, "")
            double_press_comment = self.current_profile.double_press_comments.get(control_name, "")
            double_click_timeout = self.current_profile.double_click_timeout
            on_release = control_name in self.current_profile.on_release_controls

        # Load into editor
        self.control_editor.load_control(
            control_name,
            current_action,
            comment=comment,
            modifier_combos=modifier_combos,
            haptic_strength=haptic_strength,
            haptic_speed=haptic_speed,
            double_press_action=double_press_action,
            double_press_comment=double_press_comment,
            double_click_timeout=double_click_timeout,
            on_release=on_release,
        )

        # Update status bar
        self.statusBar().showMessage(f"Editing: {control_name}")

    def _on_action_changed(self, control_name: str, action_str: str):
        """Handle action change from editor

        Args:
            control_name: Name of the control
            action_str: New action string
        """
        logger.info(f"Action changed: {control_name} -> {action_str}")

        # Track the modification
        self.modified_mappings[control_name] = action_str
        self.is_modified = True
        self._update_window_title()

        # Enable Save button
        self.save_action.setEnabled(True)

        # Convert action string to human-readable format
        hints = get_system_display_hints()
        readable_action = self._action_to_readable(action_str, hints)

        # Update the controls list display
        for row in range(self.controls_list.table.rowCount()):
            item = self.controls_list.table.item(row, 0)
            if item and item.data(Qt.UserRole) == control_name:
                action_item = self.controls_list.table.item(row, 1)
                if action_item:
                    action_item.setText(readable_action)
                break

        self.statusBar().showMessage(f"Modified: {control_name} (not saved)")

    def _on_comment_changed(self, control_name: str, comment: str):
        """Handle comment change from editor

        Args:
            control_name: Name of the control
            comment: New comment text
        """
        logger.info(f"Comment changed: {control_name}")

        # Track the modification
        self.modified_comments[control_name] = comment
        self.is_modified = True
        self._update_window_title()

        # Enable Save button
        self.save_action.setEnabled(True)

        # Update the controls list display
        for row in range(self.controls_list.table.rowCount()):
            item = self.controls_list.table.item(row, 0)
            if item and item.data(Qt.UserRole) == control_name:
                comment_item = self.controls_list.table.item(row, 2)
                if comment_item:
                    comment_item.setText(comment)
                break

        self.statusBar().showMessage(f"Comment modified: {control_name} (not saved)")

    def _on_double_press_action_changed(self, control_name: str, action_str: str):
        """Handle double-press action change from editor

        Args:
            control_name: Name of the control
            action_str: New double-press action string (empty to clear)
        """
        if not self.current_profile:
            return

        logger.info(f"Double-press action changed: {control_name} -> {action_str or '(none)'}")

        # Update the profile directly
        if action_str:
            self.current_profile.double_press_actions[control_name] = action_str
        else:
            # Remove if empty
            self.current_profile.double_press_actions.pop(control_name, None)

        self.is_modified = True
        self._update_window_title()
        self.save_action.setEnabled(True)

        # Update just the action cell for this control (don't reload entire profile
        # as that would wipe out unsaved changes from modified_mappings)
        for row in range(self.controls_list.table.rowCount()):
            item = self.controls_list.table.item(row, 0)
            if item and item.data(Qt.UserRole) == control_name:
                action_item = self.controls_list.table.item(row, 1)
                if action_item:
                    # Get the base action (from modified_mappings or current display)
                    base_action = action_item.text()
                    # Remove any existing double-press suffix
                    if " (2×:" in base_action:
                        base_action = base_action.split(" (2×:")[0]
                    # Add new double-press suffix if action exists
                    if action_str:
                        dp_hints = get_system_display_hints()
                        dp_readable = self._action_to_readable(action_str, dp_hints)
                        action_item.setText(f"{base_action} (2×: {dp_readable})")
                    else:
                        action_item.setText(base_action)
                break

        self.statusBar().showMessage(f"Double-press modified: {control_name} (not saved)")

    def _on_double_press_comment_changed(self, control_name: str, comment: str):
        """Handle double-press comment change from editor

        Args:
            control_name: Name of the control
            comment: New double-press comment text
        """
        if not self.current_profile:
            return

        logger.info(f"Double-press comment changed: {control_name}")

        # Update the profile directly
        if comment:
            self.current_profile.double_press_comments[control_name] = comment
        else:
            # Remove if empty
            self.current_profile.double_press_comments.pop(control_name, None)

        self.is_modified = True
        self._update_window_title()
        self.save_action.setEnabled(True)

    def _on_on_release_changed(self, control_name: str, enabled: bool):
        """Handle on-release toggle change from editor

        Args:
            control_name: Name of the control
            enabled: Whether on-release is enabled for this control
        """
        if not self.current_profile:
            return

        logger.info(f"On-release {'enabled' if enabled else 'disabled'}: {control_name}")

        # Update the profile directly
        if enabled:
            self.current_profile.on_release_controls.add(control_name)
            # User explicitly enabled - remove from user_disabled if present
            self.current_profile.on_release_user_disabled.discard(control_name)
        else:
            self.current_profile.on_release_controls.discard(control_name)
            # Check if this control is a modifier (has combos) - if so, track user's choice
            is_modifier = control_name in self.current_profile.modifier_buttons
            if is_modifier:
                self.current_profile.on_release_user_disabled.add(control_name)
                logger.info(f"Tracking user-disabled on_release for modifier: {control_name}")

        self.is_modified = True
        self._update_window_title()
        self.save_action.setEnabled(True)
        self.statusBar().showMessage(f"On-release modified: {control_name} (not saved)")

    def _on_modifier_config_changed(self, control_name: str, modifier_config: dict):
        """Handle modifier configuration change from editor

        Args:
            control_name: Name of the modifier button
            modifier_config: Modifier configuration dict with:
                - is_modifier: bool
                - base_action: str
                - base_action_comment: str
                - combos: dict of control_name -> (action, comment)
        """
        logger.info(f"Modifier config changed: {control_name}")

        # Track the modification
        self.modified_modifiers[control_name] = modifier_config
        self.is_modified = True
        self._update_window_title()

        # Enable Save button
        self.save_action.setEnabled(True)

        # Auto-enable on_release when button becomes a modifier (has combos)
        if self.current_profile:
            if modifier_config.get('is_modifier'):
                # Button has combos - auto-enable on_release if user hasn't explicitly disabled it
                if control_name not in self.current_profile.on_release_controls:
                    if control_name not in self.current_profile.on_release_user_disabled:
                        self.current_profile.on_release_controls.add(control_name)
                        # Update the checkbox in the editor to reflect this
                        self.control_editor.on_release_checkbox.setChecked(True)
                        logger.info(f"Auto-enabled on_release for new modifier: {control_name}")
            else:
                # Button no longer has combos - clear user_disabled so it can auto-enable if combos added later
                # Don't auto-disable on_release - user may want it for other reasons
                self.current_profile.on_release_user_disabled.discard(control_name)

        # Update the controls list display to show modifier status
        for row in range(self.controls_list.table.rowCount()):
            item = self.controls_list.table.item(row, 0)
            if item and item.data(Qt.UserRole) == control_name:
                # Update the action column
                action_item = self.controls_list.table.item(row, 1)
                if action_item:
                    mod_hints = get_system_display_hints()
                    # Determine the base readable action
                    if modifier_config.get('is_modifier'):
                        # Show base action for modifiers
                        base_action = modifier_config.get('base_action', '')
                        if base_action:
                            readable_action = self._action_to_readable(base_action, mod_hints)
                        else:
                            readable_action = "(no base action)"
                    else:
                        # Non-modifier - show regular action
                        if control_name in self.modified_mappings:
                            readable_action = self._action_to_readable(self.modified_mappings[control_name], mod_hints)
                        elif modifier_config.get('base_action'):
                            readable_action = self._action_to_readable(modifier_config['base_action'], mod_hints)
                        else:
                            readable_action = "(unmapped)"

                    # Append double-press suffix if configured
                    dp_action = self.current_profile.double_press_actions.get(control_name, '')
                    if dp_action:
                        dp_readable = self._action_to_readable(dp_action, mod_hints)
                        readable_action = f"{readable_action} (2×: {dp_readable})"

                    action_item.setText(readable_action)
                break

        if modifier_config.get('is_modifier'):
            self.statusBar().showMessage(f"Modifier configured: {control_name} (not saved)")
        else:
            self.statusBar().showMessage(f"Modifier removed: {control_name} (not saved)")

    def _on_haptic_changed(self, dial_name: str, haptic_strength, haptic_speed):
        """Handle haptic setting change from editor

        Args:
            dial_name: Name of the dial ('knob', 'scroll', or 'dial')
            haptic_strength: HapticStrength or None (None = use profile default)
            haptic_speed: HapticSpeed or None (None = use profile default)
        """
        logger.info(f"Haptic changed: {dial_name} -> strength={haptic_strength}, speed={haptic_speed}")

        # Track the modifications
        self.modified_haptic[dial_name] = haptic_strength
        self.modified_haptic_speed[dial_name] = haptic_speed
        self.is_modified = True
        self._update_window_title()

        # Enable Save button
        self.save_action.setEnabled(True)

        self.statusBar().showMessage(f"Haptic modified: {dial_name} (not saved)")

    def _on_combo_haptic_changed(self, modifier_name: str, dial_name: str, haptic_strength, haptic_speed):
        """Handle combo haptic setting change from editor

        Args:
            modifier_name: Name of the modifier button (e.g., 'side')
            dial_name: Name of the dial ('knob', 'scroll', or 'dial')
            haptic_strength: HapticStrength or None (None = use profile default)
            haptic_speed: HapticSpeed or None (None = use profile default)
        """
        logger.info(f"Combo haptic changed: {modifier_name}+{dial_name} -> strength={haptic_strength}, speed={haptic_speed}")

        # Track the modifications
        self.modified_combo_haptic[(modifier_name, dial_name)] = haptic_strength
        self.modified_combo_haptic_speed[(modifier_name, dial_name)] = haptic_speed
        self.is_modified = True
        self._update_window_title()

        # Enable Save button
        self.save_action.setEnabled(True)

        self.statusBar().showMessage(f"Combo haptic modified: {modifier_name}+{dial_name} (not saved)")

    def _on_combo_selected(self, combo_control: str):
        """Handle combo selection from Modifier Combinations table

        Args:
            combo_control: Name of the control selected in the combo table
        """
        logger.info(f"Combo selected: {combo_control}")

        # Get the current modifier control
        modifier_control = self.control_editor.current_control
        if not modifier_control:
            return

        # Check if current control is a modifier
        is_modifier = False
        if self.current_profile and modifier_control in self.current_profile.modifier_buttons:
            is_modifier = True

        # Highlight both the modifier and the combo control
        self.controller_view.highlight_control(modifier_control, is_modifier, combo_control)

    def _update_window_title(self):
        """Update window title to show modified state"""
        title = "TuxBox Configuration"
        if self.current_profile:
            title += f" - {self.current_profile.name}"
        if self.is_modified:
            title += " *"
        self.setWindowTitle(title)

    def _on_save(self):
        """Handle Save action - save profile changes to config file"""
        if not self.current_profile:
            QMessageBox.warning(self, "No Profile", "No profile is currently selected.")
            return

        if not self.is_modified:
            QMessageBox.information(self, "No Changes", "No changes to save.")
            return

        logger.info(f"Saving profile: {self.current_profile.name}")
        logger.debug(f"Modified mappings: {self.modified_mappings}")
        logger.debug(f"Modified comments: {self.modified_comments}")
        logger.debug(f"Modified modifiers: {self.modified_modifiers}")
        logger.debug(f"Modified haptic: {self.modified_haptic}")
        logger.debug(f"Modified haptic speed: {self.modified_haptic_speed}")
        logger.debug(f"Modified combo haptic: {self.modified_combo_haptic}")
        logger.debug(f"Modified combo haptic speed: {self.modified_combo_haptic_speed}")

        # Apply modifications to the profile object
        # Apply per-dial haptic strength settings
        for dial_name, haptic_strength in self.modified_haptic.items():
            if haptic_strength is None:
                # "Use Profile Default" - remove per-dial setting
                if dial_name in self.current_profile.haptic_config.dial_settings:
                    del self.current_profile.haptic_config.dial_settings[dial_name]
            else:
                # Set per-dial haptic strength
                self.current_profile.haptic_config.dial_settings[dial_name] = haptic_strength

        # Apply per-dial haptic speed settings
        for dial_name, haptic_speed in self.modified_haptic_speed.items():
            if haptic_speed is None:
                # "Use Profile Default" - remove per-dial speed setting
                if dial_name in self.current_profile.haptic_config.dial_speed_settings:
                    del self.current_profile.haptic_config.dial_speed_settings[dial_name]
            else:
                # Set per-dial haptic speed
                self.current_profile.haptic_config.dial_speed_settings[dial_name] = haptic_speed

        # Apply per-combo haptic strength settings (modifier + dial combinations)
        for (modifier_name, dial_name), haptic_strength in self.modified_combo_haptic.items():
            combo_key = (dial_name, modifier_name)  # HapticConfig uses (dial, modifier)
            if haptic_strength is None:
                # "Use Profile Default" - remove per-combo setting
                if combo_key in self.current_profile.haptic_config.combo_settings:
                    del self.current_profile.haptic_config.combo_settings[combo_key]
            else:
                # Set per-combo haptic strength
                self.current_profile.haptic_config.combo_settings[combo_key] = haptic_strength

        # Apply per-combo haptic speed settings (modifier + dial combinations)
        for (modifier_name, dial_name), haptic_speed in self.modified_combo_haptic_speed.items():
            combo_key = (dial_name, modifier_name)  # HapticConfig uses (dial, modifier)
            if haptic_speed is None:
                # "Use Profile Default" - remove per-combo speed setting
                if combo_key in self.current_profile.haptic_config.combo_speed_settings:
                    del self.current_profile.haptic_config.combo_speed_settings[combo_key]
            else:
                # Set per-combo haptic speed
                self.current_profile.haptic_config.combo_speed_settings[combo_key] = haptic_speed

        # Apply comments
        for control_name, comment in self.modified_comments.items():
            if comment:
                self.current_profile.mapping_comments[control_name] = comment
            elif control_name in self.current_profile.mapping_comments:
                del self.current_profile.mapping_comments[control_name]

        # Apply modifier configurations
        for control_name, modifier_config in self.modified_modifiers.items():
            if modifier_config.get('is_modifier'):
                # Add to modifier_buttons set
                self.current_profile.modifier_buttons.add(control_name)

                # Set base action
                base_action = modifier_config.get('base_action', '').strip()
                if base_action:
                    self.current_profile.modifier_base_actions[control_name] = base_action
                elif control_name in self.current_profile.modifier_base_actions:
                    del self.current_profile.modifier_base_actions[control_name]

                # Set base action comment
                base_action_comment = modifier_config.get('base_action_comment', '').strip()
                base_action_key = f"{control_name}.base_action"
                if base_action_comment:
                    self.current_profile.mapping_comments[base_action_key] = base_action_comment
                elif base_action_key in self.current_profile.mapping_comments:
                    del self.current_profile.mapping_comments[base_action_key]

                # Set combos
                # First, remove old combos for this modifier
                old_combos = [(mod, ctrl) for (mod, ctrl) in self.current_profile.modifier_mappings.keys() if mod == control_name]
                for combo_key in old_combos:
                    del self.current_profile.modifier_mappings[combo_key]
                    if combo_key in self.current_profile.modifier_combo_comments:
                        del self.current_profile.modifier_combo_comments[combo_key]

                # Add new combos
                for ctrl, (action, combo_comment) in modifier_config.get('combos', {}).items():
                    combo_key = (control_name, ctrl)
                    self.current_profile.modifier_mappings[combo_key] = action
                    if combo_comment:
                        self.current_profile.modifier_combo_comments[combo_key] = combo_comment
            else:
                # is_modifier is False - remove modifier configuration
                # Remove from modifier_buttons set
                if control_name in self.current_profile.modifier_buttons:
                    self.current_profile.modifier_buttons.discard(control_name)

                # Remove base action
                if control_name in self.current_profile.modifier_base_actions:
                    del self.current_profile.modifier_base_actions[control_name]

                # Remove base action comment
                base_action_key = f"{control_name}.base_action"
                if base_action_key in self.current_profile.mapping_comments:
                    del self.current_profile.mapping_comments[base_action_key]

                # Remove all combos for this modifier
                old_combos = [(mod, ctrl) for (mod, ctrl) in self.current_profile.modifier_mappings.keys() if mod == control_name]
                for combo_key in old_combos:
                    del self.current_profile.modifier_mappings[combo_key]
                    if combo_key in self.current_profile.modifier_combo_comments:
                        del self.current_profile.modifier_combo_comments[combo_key]

        # Get the original name (before any renames) to check if profile exists
        original_name = self.profile_original_names.get(id(self.current_profile), self.current_profile.name)
        profile_exists = profile_exists_in_config(original_name)

        if not profile_exists:
            # This is a new profile - create it
            logger.info(f"Creating new profile: {self.current_profile.name}")
            success = create_new_profile(self.current_profile)
            if not success:
                self.statusBar().showMessage("Failed to create new profile")
                QMessageBox.critical(
                    self,
                    "Save Failed",
                    f"Failed to create new profile '{self.current_profile.name}'.\n\n"
                    "Check the logs for details."
                )
                return
            # Update the original name tracker for the newly created profile
            self.profile_original_names[id(self.current_profile)] = self.current_profile.name
        else:
            # Existing profile - save metadata and mappings
            # Determine if profile was renamed
            old_name = original_name if original_name != self.current_profile.name else None

            # Save profile metadata first (name, window matching)
            metadata_success = save_profile_metadata(self.current_profile, old_name)
            if not metadata_success:
                self.statusBar().showMessage("Failed to save profile metadata")
                QMessageBox.critical(
                    self,
                    "Save Failed",
                    f"Failed to save profile metadata for '{self.current_profile.name}'.\n\n"
                    "Check the logs for details."
                )
                return

            # Update the original name tracker if profile was renamed
            if old_name:
                self.profile_original_names[id(self.current_profile)] = self.current_profile.name

            # Save modifier config FIRST (before regular mappings)
            # This ensures modifiers are properly configured before writing regular mappings
            modifiers_success = True
            if self.modified_modifiers:
                modifiers_success = save_modifier_config(self.current_profile)

            # Save the control mappings if any were modified
            # Filter out buttons that are modifiers (they use base_action instead)
            mappings_success = True
            if self.modified_mappings:
                # Remove any modifier buttons from mappings to avoid conflicts
                filtered_mappings = {
                    ctrl: action for ctrl, action in self.modified_mappings.items()
                    if ctrl not in self.current_profile.modifier_buttons
                }
                if filtered_mappings:
                    mappings_success = save_profile(self.current_profile, filtered_mappings)

            # Save comments if any were modified
            comments_success = True
            if self.modified_comments:
                comments_success = save_mapping_comments(self.current_profile)

            # Save haptic config (always save since it's edited via profile settings)
            haptic_success = save_haptic_config(self.current_profile)

            success = metadata_success and mappings_success and comments_success and modifiers_success and haptic_success

        if success:
            # Clear modified state
            self.modified_mappings = {}
            self.modified_comments = {}
            self.modified_modifiers = {}
            self.modified_haptic = {}
            self.modified_haptic_speed = {}
            self.modified_combo_haptic = {}
            self.modified_combo_haptic_speed = {}
            self.is_modified = False
            self._update_window_title()

            # Disable Save button
            self.save_action.setEnabled(False)

            # Clean up old backups
            cleanup_old_backups()

            # Send SIGHUP to driver to apply new configuration
            logger.info("Applying configuration changes...")
            reload_success, reload_message = DriverManager.reload_driver()

            if reload_success:
                logger.info("Configuration applied successfully")
                self.statusBar().showMessage("Profile saved and configuration applied")
                QMessageBox.information(
                    self,
                    "Save Successful",
                    f"Profile '{self.current_profile.name}' has been saved.\n\n"
                    "The new configuration has been applied.\n"
                    "Switch to your application to test the new mappings."
                )
            else:
                logger.warning(f"Failed to apply configuration: {reload_message}")
                self.statusBar().showMessage("Profile saved (configuration not applied)")
                restart_instructions = DriverManager.get_restart_instructions()
                QMessageBox.warning(
                    self,
                    "Save Successful (Apply Failed)",
                    f"Profile '{self.current_profile.name}' has been saved.\n\n"
                    f"However, failed to apply the configuration:\n{reload_message}\n\n"
                    f"You may need to manually restart the driver:\n{restart_instructions}"
                )
        else:
            self.statusBar().showMessage("Failed to save profile")
            QMessageBox.critical(
                self,
                "Save Failed",
                f"Failed to save profile '{self.current_profile.name}'.\n\n"
                "Check the logs for details."
            )

    def _action_to_readable(self, action_str: str, display_hints: dict = None) -> str:
        """Convert action string to human-readable format

        Args:
            action_str: Action string like 'KEY_LEFTCTRL+KEY_C'
            display_hints: Optional dict of KEY_* name -> display character (locale-aware)

        Returns:
            Human-readable string like 'Ctrl+C'
        """
        if not action_str or action_str == "none" or action_str == "(none)":
            return "(unmapped)"

        # Handle simple mouse actions (no modifiers)
        if action_str.startswith("REL_WHEEL:") and "+" not in action_str:
            value = action_str.split(":")[1]
            return f"Scroll {'Up' if int(value) > 0 else 'Down'}"
        if action_str.startswith("REL_HWHEEL:") and "+" not in action_str:
            value = action_str.split(":")[1]
            return f"Scroll {'Right' if int(value) > 0 else 'Left'}"
        if action_str == "BTN_LEFT":
            return "Left Click"
        if action_str == "BTN_RIGHT":
            return "Right Click"
        if action_str == "BTN_MIDDLE":
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

        # Handle keyboard
        parts = action_str.split("+")
        readable_parts = []

        for part in parts:
            part = part.strip()
            # Convert KEY_* to readable names
            if part.startswith("KEY_"):
                original_part = part
                key_name = part.replace("KEY_", "")

                # Check display hints first (locale-aware), then symbol map
                if display_hints and original_part in display_hints:
                    key_name = display_hints[original_part]
                elif key_name in SYMBOL_MAP:
                    key_name = SYMBOL_MAP[key_name]
                else:
                    # Don't strip LEFT/RIGHT from arrow keys and navigation keys
                    if original_part not in ('KEY_LEFT', 'KEY_RIGHT', 'KEY_UP', 'KEY_DOWN'):
                        # Clean up modifier names
                        key_name = key_name.replace("LEFT", "").replace("RIGHT", "")

                    # Special cases
                    if key_name == "META":
                        key_name = "Super"
                    else:
                        # Replace underscores with spaces for readability
                        key_name = key_name.replace('_', ' ')
                        # Title case for regular keys
                        key_name = key_name.title()
                readable_parts.append(key_name)
            else:
                # Check if it's a mouse action part
                mouse_readable = mouse_part_to_readable(part)
                if mouse_readable:
                    readable_parts.append(mouse_readable)
                else:
                    readable_parts.append(part)

        return "+".join(readable_parts)

    def _check_migration(self):
        """Check if config migration is needed and perform it automatically"""
        from tuxbox.profile_io import needs_migration, migrate_legacy_config

        if not needs_migration():
            return

        # Inform user that migration will happen
        QMessageBox.information(
            self,
            "Configuration Migration",
            "TuxBox now stores profiles in individual files for easier sharing.\n\n"
            "All your existing profiles and settings will be preserved.\n"
            "A backup of your current configuration will also be created."
        )

        # Perform migration
        success, message = migrate_legacy_config()

        if success:
            QMessageBox.information(
                self,
                "Migration Complete",
                f"Your profiles have been migrated successfully.\n\n{message}"
            )
            logger.info(f"Migration completed: {message}")
        else:
            QMessageBox.warning(
                self,
                "Migration Failed",
                f"Failed to migrate profiles:\n\n{message}\n\n"
                "Your existing configuration has not been modified."
            )
            logger.error(f"Migration failed: {message}")

    def _on_menu_import_profile(self):
        """Handle Import Profile menu action"""
        # Delegate to profile manager
        self.profile_manager._on_import_profile()

    def _on_menu_export_profile(self):
        """Handle Export Profile menu action"""
        # Delegate to profile manager
        self.profile_manager._on_export_profile()

    def _on_menu_settings(self):
        """Handle Settings menu action - edit global [device] settings"""
        from .device_settings_dialog import DeviceSettingsDialog
        from .device_config_writer import save_device_settings

        dialog = DeviceSettingsDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return

        changes = dialog.get_changes()
        if not changes:
            self.statusBar().showMessage("No settings were changed")
            return

        success, message = save_device_settings(changes)

        if not success:
            QMessageBox.warning(self, "Settings Not Saved", message)
            return

        cleanup_old_backups()
        self.statusBar().showMessage("Settings saved")

        if 'controller_model' in changes:
            model = changes['controller_model'] or DEFAULT_CONTROLLER_MODEL
            self.controller_view.set_model(model)
            self.control_editor.set_model(model)
            self.controls_list.set_model(model)
        if not (set(changes) - {'controller_model'}):
            return

        # Driver settings are not re-read while the driver runs, so an
        # unrestarted driver would keep using the old ones with no sign of it.
        answer = QMessageBox.question(
            self,
            "Restart Driver?",
            "Settings saved.\n\n"
            "The driver needs to restart before they take effect. Restart it now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if answer == QMessageBox.Yes:
            self._on_restart_driver()

    def _on_restart_driver(self):
        """Handle Restart Driver menu action"""
        from PySide6.QtWidgets import QApplication

        self.statusBar().showMessage("Restarting driver...")
        QApplication.processEvents()  # Ensure UI updates before blocking call

        # Restart the driver service
        success, message = DriverManager.restart_driver()

        if success:
            # Reload profiles from disk
            self._reload_profiles_from_disk()
            self.statusBar().showMessage("Driver restarted and profiles reloaded")
            QMessageBox.information(
                self,
                "Driver Restarted",
                "The TuxBox driver has been restarted and profiles have been reloaded."
            )
        else:
            self.statusBar().showMessage(f"Failed to restart driver: {message}")
            QMessageBox.warning(
                self,
                "Restart Failed",
                f"Failed to restart the driver:\n\n{message}"
            )

    def _reload_profiles_from_disk(self):
        """Reload all profiles from disk and update the GUI"""
        from ..profile_io import load_profiles_from_directory

        try:
            # Remember current profile name
            current_name = self.current_profile.name if self.current_profile else None

            # Reload profiles
            profiles = load_profiles_from_directory()

            if profiles:
                # Update profile manager's list (this selects 'default' by default)
                self.profile_manager.load_profiles(profiles)

                # Try to re-select the previously selected profile
                if current_name and current_name != 'default':
                    for row in range(self.profile_manager.profile_table.rowCount()):
                        item = self.profile_manager.profile_table.item(row, 0)
                        if item:
                            profile = item.data(Qt.UserRole)
                            if profile and profile.name == current_name:
                                self.profile_manager.profile_table.selectRow(row)
                                break

                logger.info(f"Reloaded {len(profiles)} profiles from disk")
            else:
                logger.warning("No profiles found when reloading from disk")

        except Exception as ex:
            logger.error(f"Error reloading profiles: {ex}", exc_info=True)

    def _open_user_guide(self):
        """Open the GUI User Guide documentation on GitHub"""
        QDesktopServices.openUrl(
            QUrl("https://github.com/AndyCappDev/tuxbox/blob/master/docs/GUI_USER_GUIDE.md")
        )

    def _show_about(self):
        """Show the About dialog"""
        from . import __version__

        about_text = f"""
<h2>TuxBox</h2>
<p>Version {__version__}</p>
<p>A Linux driver for TourBox Lite, Neo, Elite and Elite Plus controllers,<br>
with full GUI configuration support.</p>
<p><b>Author:</b> Scott Bowman (<a href="https://github.com/AndyCappDev">AndyCappDev</a>)</p>
<p><a href="https://github.com/AndyCappDev/tuxbox">Project Homepage</a></p>
<hr>
<p>If you find this software useful, please consider giving it a ⭐ on GitHub<br>
(click the Star button in the top right of the <a href="https://github.com/AndyCappDev/tuxbox">project page</a>).</p>
"""

        msg = QMessageBox(self)
        msg.setWindowTitle("About TuxBox")
        msg.setTextFormat(Qt.RichText)
        msg.setText(about_text)
        msg.setIcon(QMessageBox.Information)
        msg.exec()

    def _check_for_updates(self):
        """Check GitHub for a newer version"""
        from .update_checker import UpdateChecker

        # Disable menu item during check
        self.check_updates_action.setEnabled(False)
        self.statusBar().showMessage("Checking for updates...")

        # Create and start update checker thread
        self._update_checker = UpdateChecker(self)
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.no_update.connect(self._on_no_update)
        self._update_checker.check_failed.connect(self._on_check_failed)
        self._update_checker.finished.connect(lambda: self.check_updates_action.setEnabled(True))
        self._update_checker.start()

    def _on_update_available(self, latest_version: str, current_version: str, release_notes: str):
        """Handle update available signal"""
        from pathlib import Path
        import webbrowser

        self.statusBar().showMessage(f"Update available: {latest_version}")

        # Detect install path (3 levels up from main_window.py)
        install_path = Path(__file__).parent.parent.parent

        # Create dialog with update info
        msg = QMessageBox(self)
        msg.setWindowTitle("Update Available")
        msg.setIcon(QMessageBox.Information)
        msg.setText(f"A new version is available!\n\n"
                    f"Current version: {current_version}\n"
                    f"Latest version: {latest_version}")

        # Build informative text with release notes and update instructions
        info_text = ""
        if release_notes:
            # Strip markdown formatting for plain text display
            notes = release_notes.strip()
            # Truncate if very long
            if len(notes) > 800:
                notes = notes[:800] + "..."
            info_text = f"{notes}\n\n"

        info_text += (
            f"To update, run these commands:\n\n"
            f"  cd {install_path}\n"
            f"  git pull\n"
            f"  ./install.sh"
        )
        msg.setInformativeText(info_text)

        # Add buttons
        view_btn = msg.addButton("View on GitHub", QMessageBox.ActionRole)
        msg.addButton("Close", QMessageBox.RejectRole)

        msg.exec()

        # Handle button click
        if msg.clickedButton() == view_btn:
            webbrowser.open(
                f"https://github.com/AndyCappDev/tuxbox/releases/tag/v{latest_version}"
            )

    def _on_no_update(self, current_version: str):
        """Handle no update available signal"""
        self.statusBar().showMessage("You are running the latest version")

        QMessageBox.information(
            self,
            "No Updates",
            f"You are running the latest version ({current_version})."
        )

    def _on_check_failed(self, error_message: str):
        """Handle update check failed signal"""
        self.statusBar().showMessage("Update check failed")

        QMessageBox.warning(
            self,
            "Update Check Failed",
            f"Could not check for updates:\n\n{error_message}\n\n"
            "Please check your internet connection."
        )

    def keyPressEvent(self, event):
        """Handle keyboard navigation between panes with left/right arrows"""
        from PySide6.QtWidgets import QLineEdit, QComboBox, QTextEdit

        # Don't intercept if user is typing in a text field or interacting with a dropdown
        focused_widget = QApplication.focusWidget()
        if isinstance(focused_widget, (QLineEdit, QTextEdit)):
            # Let the text field handle the key press
            super().keyPressEvent(event)
            return

        # Don't intercept if a combo box is open
        if isinstance(focused_widget, QComboBox):
            super().keyPressEvent(event)
            return

        key = event.key()
        modifiers = event.modifiers()

        # Check for meta-configuration key combinations
        # Ctrl+Alt+Shift+F1-F12 for first 12 controls
        # Ctrl+Alt+Shift+1-8 for remaining 8 controls
        # These allow the TourBox to control its own GUI - pressing a physical
        # control automatically selects it in the Controls Configuration table

        meta_key_map = None

        # Meta-configuration: Ctrl+Alt+Shift + [F1-F12 or 1-8]
        # Group 1: F1-F12 for first 12 controls
        # Group 2: 1-8 for remaining 8 controls
        if (modifiers & Qt.ControlModifier and
            modifiers & Qt.AltModifier and
            modifiers & Qt.ShiftModifier):

            meta_key_map = {
                # Group 1: F1-F12
                Qt.Key_F1: 'side',
                Qt.Key_F2: 'top',
                Qt.Key_F3: 'tall',
                Qt.Key_F4: 'short',
                Qt.Key_F5: 'c1',
                Qt.Key_F6: 'c2',
                Qt.Key_F7: 'tour',
                Qt.Key_F8: 'dpad_up',
                Qt.Key_F9: 'dpad_down',
                Qt.Key_F10: 'dpad_left',
                Qt.Key_F11: 'dpad_right',
                Qt.Key_F12: 'scroll_up',
                # Group 2: 1-8 (and their shifted symbol equivalents)
                # When Shift is held, Qt interprets number keys as symbols
                Qt.Key_1: 'scroll_down',
                Qt.Key_Exclam: 'scroll_down',          # Shift+1 = !
                Qt.Key_2: 'scroll_click',
                Qt.Key_At: 'scroll_click',             # Shift+2 = @
                Qt.Key_3: 'knob_cw',
                Qt.Key_NumberSign: 'knob_cw',          # Shift+3 = #
                Qt.Key_4: 'knob_ccw',
                Qt.Key_Dollar: 'knob_ccw',             # Shift+4 = $
                Qt.Key_5: 'knob_click',
                Qt.Key_Percent: 'knob_click',          # Shift+5 = %
                Qt.Key_6: 'dial_cw',
                Qt.Key_AsciiCircum: 'dial_cw',         # Shift+6 = ^
                Qt.Key_7: 'dial_ccw',
                Qt.Key_Ampersand: 'dial_ccw',          # Shift+7 = &
                Qt.Key_8: 'dial_click',
                Qt.Key_Asterisk: 'dial_click',         # Shift+8 = *
            }

        if meta_key_map and key in meta_key_map:
            control_name = meta_key_map[key]
            logger.info(f"Meta-configuration: Selecting control '{control_name}'")

            # Select the control in the controls list
            self.controls_list.select_control(control_name)

            # Accept the event so it doesn't propagate
            event.accept()
            return

        # Define the navigation order for the three main panes
        focusable_widgets = [
            self.profile_manager.profile_table,  # Access the QTableWidget inside ProfileManager
            self.controls_list.table,            # Access the QTableWidget inside ControlsList
            self.control_editor                  # The ControlEditor widget itself
        ]

        # Find current focus position
        current_index = -1
        for i, widget in enumerate(focusable_widgets):
            if widget.hasFocus() or widget.isAncestorOf(focused_widget) if focused_widget else False:
                current_index = i
                break

        # Handle left/right arrow keys
        if key == Qt.Key_Right:
            # Move to next pane (with wrap-around)
            next_index = (current_index + 1) % len(focusable_widgets)
            focusable_widgets[next_index].setFocus()
            logger.debug(f"Focus moved right to pane {next_index}")
        elif key == Qt.Key_Left:
            # Move to previous pane (with wrap-around)
            prev_index = (current_index - 1) % len(focusable_widgets)
            focusable_widgets[prev_index].setFocus()
            logger.debug(f"Focus moved left to pane {prev_index}")
        else:
            # Pass other keys to parent handler
            super().keyPressEvent(event)

    def closeEvent(self, event):
        """Handle window close event"""
        logger.info("Main window closing")

        # Check for unsaved changes
        if self.is_modified:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                f"Profile '{self.current_profile.name}' has unsaved changes.\n\n"
                "Do you want to save them before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save
            )

            if reply == QMessageBox.Save:
                # Apply all modifications to the profile object first
                # Apply comments
                for control_name, comment in self.modified_comments.items():
                    if comment:
                        self.current_profile.mapping_comments[control_name] = comment
                    elif control_name in self.current_profile.mapping_comments:
                        del self.current_profile.mapping_comments[control_name]

                # Apply modifier configurations
                for control_name, modifier_config in self.modified_modifiers.items():
                    if modifier_config.get('is_modifier'):
                        # Add to modifier_buttons set
                        self.current_profile.modifier_buttons.add(control_name)

                        # Set base action
                        base_action = modifier_config.get('base_action', '').strip()
                        if base_action:
                            self.current_profile.modifier_base_actions[control_name] = base_action
                        elif control_name in self.current_profile.modifier_base_actions:
                            del self.current_profile.modifier_base_actions[control_name]

                        # Set base action comment
                        base_action_comment = modifier_config.get('base_action_comment', '').strip()
                        base_action_key = f"{control_name}.base_action"
                        if base_action_comment:
                            self.current_profile.mapping_comments[base_action_key] = base_action_comment
                        elif base_action_key in self.current_profile.mapping_comments:
                            del self.current_profile.mapping_comments[base_action_key]

                        # Set combos
                        # First, remove old combos for this modifier
                        old_combos = [(mod, ctrl) for (mod, ctrl) in self.current_profile.modifier_mappings.keys() if mod == control_name]
                        for combo_key in old_combos:
                            del self.current_profile.modifier_mappings[combo_key]
                            if combo_key in self.current_profile.modifier_combo_comments:
                                del self.current_profile.modifier_combo_comments[combo_key]

                        # Add new combos
                        for ctrl, (action, combo_comment) in modifier_config.get('combos', {}).items():
                            combo_key = (control_name, ctrl)
                            self.current_profile.modifier_mappings[combo_key] = action
                            if combo_comment:
                                self.current_profile.modifier_combo_comments[combo_key] = combo_comment
                    else:
                        # is_modifier is False - remove modifier configuration
                        if control_name in self.current_profile.modifier_buttons:
                            self.current_profile.modifier_buttons.discard(control_name)
                        if control_name in self.current_profile.modifier_base_actions:
                            del self.current_profile.modifier_base_actions[control_name]
                        base_action_key = f"{control_name}.base_action"
                        if base_action_key in self.current_profile.mapping_comments:
                            del self.current_profile.mapping_comments[base_action_key]
                        # Remove all combos for this modifier
                        old_combos = [(mod, ctrl) for (mod, ctrl) in self.current_profile.modifier_mappings.keys() if mod == control_name]
                        for combo_key in old_combos:
                            del self.current_profile.modifier_mappings[combo_key]
                            if combo_key in self.current_profile.modifier_combo_comments:
                                del self.current_profile.modifier_combo_comments[combo_key]

                # Save the changes (both profile metadata and control mappings)
                from .config_writer import profile_exists_in_config
                original_name = self.profile_original_names.get(id(self.current_profile), self.current_profile.name)
                profile_exists = profile_exists_in_config(original_name)

                if not profile_exists:
                    # This is a new profile - create it
                    logger.info(f"Creating new profile on close: {self.current_profile.name}")
                    success = create_new_profile(self.current_profile)
                else:
                    # Existing profile - save metadata and mappings
                    old_name = original_name if original_name != self.current_profile.name else None

                    # Save profile metadata (name, window matching)
                    metadata_success = save_profile_metadata(self.current_profile, old_name)

                    # Save modifier config FIRST (before regular mappings)
                    modifiers_success = True
                    if self.modified_modifiers:
                        modifiers_success = save_modifier_config(self.current_profile)

                    # Save control mappings
                    mappings_success = True
                    if self.modified_mappings:
                        # Remove any modifier buttons from mappings to avoid conflicts
                        filtered_mappings = {
                            ctrl: action for ctrl, action in self.modified_mappings.items()
                            if ctrl not in self.current_profile.modifier_buttons
                        }
                        if filtered_mappings:
                            mappings_success = save_profile(self.current_profile, filtered_mappings)

                    # Save comments if any were modified
                    comments_success = True
                    if self.modified_comments:
                        comments_success = save_mapping_comments(self.current_profile)

                    # Save haptic config
                    haptic_success = save_haptic_config(self.current_profile)

                    success = metadata_success and modifiers_success and mappings_success and comments_success and haptic_success

                if not success:
                    reply2 = QMessageBox.critical(
                        self,
                        "Save Failed",
                        "Failed to save changes.\n\nClose anyway?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    if reply2 == QMessageBox.No:
                        event.ignore()
                        return
                else:
                    cleanup_old_backups()
            elif reply == QMessageBox.Cancel:
                # Cancel the close
                event.ignore()
                return
            elif reply == QMessageBox.Discard:
                # Just log that we're discarding - changes will be lost on close
                logger.info(f"Discarding changes to {self.current_profile.name} on close")

        # Accept close event
        event.accept()


def main():
    """Main entry point for GUI application"""
    # Set up logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info("Starting TuxBox Configuration GUI")

    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("TuxBox Configuration")
    app.setDesktopFileName("tuxbox-gui.desktop")

    # Detect and fix bogus font metrics. Some system fonts (e.g., "Courier Prime
    # Code") have wildly incorrect metrics (descent of 500+ pixels) which causes
    # all widgets (menu bars, toolbars, tables, etc.) to render with huge heights.
    # When detected, replace the font family entirely with a known-good sans-serif.
    _MAX_SANE_LINE_SPACING = 50
    fm = app.fontMetrics()
    if fm.lineSpacing() > _MAX_SANE_LINE_SPACING:
        logger.warning(
            "Bogus font metrics detected (lineSpacing=%d, descent=%d, font=%s), "
            "replacing with default sans-serif font",
            fm.lineSpacing(), fm.descent(), app.font().family()
        )
        from PySide6.QtGui import QFont
        app.setFont(QFont("Sans Serif", 10))

    # Create and show main window
    window = TuxBoxConfigWindow()
    window.show()

    # Run application event loop
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
