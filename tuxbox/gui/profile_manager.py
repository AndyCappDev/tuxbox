#!/usr/bin/env python3
"""Profile manager widget

Displays list of profiles and allows selection, creation, and deletion.
"""

import logging
from typing import List, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QMessageBox, QInputDialog, QDialog, QHeaderView,
    QFileDialog, QCheckBox
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont

# Import from existing driver code
from tuxbox.config_loader import Profile
from tuxbox.haptic import HapticConfig
from tuxbox.i18n import _

# Import GUI dialog
from .profile_settings_dialog import ProfileSettingsDialog

# Import config writer for deletion and import/export
from .config_writer import (
    delete_profile, export_profile, import_profile, install_imported_profile,
    profile_exists_in_config
)

# Import profile I/O for saving and driver manager for reloading
from tuxbox.profile_io import save_profile_to_file, get_profile_filepath
from .driver_manager import DriverManager

# Import conflict dialog
from .import_conflict_dialog import ImportConflictDialog

# Import UI constants
from tuxbox.gui.ui_constants import TABLE_ROW_HEIGHT_MULTIPLIER

logger = logging.getLogger(__name__)


class ProfileManager(QWidget):
    """Widget for managing TuxBox profiles"""

    # Signals
    profile_selected = Signal(Profile)  # Emitted when user selects a profile
    profiles_changed = Signal()  # Emitted when profiles list changes
    profiles_reset = Signal(Profile)  # Emitted when profiles reloaded from config (clears modified state)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profiles: List[Profile] = []
        self.current_profile: Optional[Profile] = None
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout(self)

        # Header
        header = QLabel(_("Profiles"))
        header.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(header)

        # Profile table (3 columns: Name, Window, Active)
        self.profile_table = QTableWidget()
        self.profile_table.setColumnCount(3)
        self.profile_table.setHorizontalHeaderLabels(
            [_("Name"), _("Window"), _("Active")]
        )
        self.profile_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.profile_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.profile_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.profile_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.profile_table.setSelectionMode(QTableWidget.SingleSelection)
        self.profile_table.setEditTriggers(QTableWidget.NoEditTriggers)  # Read-only
        self.profile_table.verticalHeader().setVisible(False)  # Hide row numbers
        # Set row height based on font metrics for proper scaling
        fm = self.profile_table.fontMetrics()
        row_height = int(fm.lineSpacing() * TABLE_ROW_HEIGHT_MULTIPLIER)
        self.profile_table.verticalHeader().setDefaultSectionSize(row_height)
        self.profile_table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.profile_table.currentCellChanged.connect(self._on_profile_selection_changed)
        layout.addWidget(self.profile_table)

        # Buttons
        button_layout = QHBoxLayout()

        self.new_button = QPushButton("+")
        self.new_button.setToolTip(_("Create new profile"))
        self.new_button.clicked.connect(self._on_new_profile)
        button_layout.addWidget(self.new_button)

        self.edit_button = QPushButton("⚙")
        self.edit_button.setToolTip(_("Edit profile settings (window matching)"))
        self.edit_button.clicked.connect(self._on_edit_profile)
        button_layout.addWidget(self.edit_button)

        self.delete_button = QPushButton("-")
        self.delete_button.setToolTip(_("Delete selected profile"))
        self.delete_button.clicked.connect(self._on_delete_profile)
        button_layout.addWidget(self.delete_button)

        # Spacer
        button_layout.addStretch()

        # Import/Export buttons
        self.import_button = QPushButton(_("Import"))
        self.import_button.setToolTip(_("Import a profile from file"))
        self.import_button.clicked.connect(self._on_import_profile)
        button_layout.addWidget(self.import_button)

        self.export_button = QPushButton(_("Export"))
        self.export_button.setToolTip(_("Export selected profile to file"))
        self.export_button.clicked.connect(self._on_export_profile)
        button_layout.addWidget(self.export_button)

        layout.addLayout(button_layout)

    def load_profiles(self, profiles: List[Profile]):
        """Load and display profiles

        Args:
            profiles: List of Profile objects from config file
        """
        self.profiles = profiles
        self.profile_table.setRowCount(0)

        # Filter out the TuxBox GUI meta-configuration profile
        # (it's for internal use and shouldn't be edited by users)
        displayed_profiles = [p for p in profiles if p.name not in ('TuxBox GUI', 'TourBox GUI')]

        for row, profile in enumerate(displayed_profiles):
            self.profile_table.insertRow(row)

            # Column 0: Profile name (with warning icon if conflicts exist)
            conflicts = self._get_conflicting_profiles(profile)
            if conflicts:
                conflict_names = ", ".join(c.name for c in conflicts)
                tooltip = _("Conflict: Multiple active profiles match the same "
                            "application.\nConflicts with: %s\nOnly the first "
                            "alphabetically will be used.") % (conflict_names,)
                # Use a QLabel with HTML to color only the warning icon
                label = QLabel(_('<span style="color: #ffaa00;">⚠</span> %s') % (profile.name,))
                label.setToolTip(tooltip)
                label.setContentsMargins(4, 0, 0, 0)  # Left padding to match other cells
                # Store profile in a hidden item for data retrieval
                name_item = QTableWidgetItem()
                name_item.setData(Qt.UserRole, profile)
                self.profile_table.setItem(row, 0, name_item)
                self.profile_table.setCellWidget(row, 0, label)
            else:
                name_item = QTableWidgetItem(profile.name)
                name_item.setData(Qt.UserRole, profile)
                self.profile_table.setItem(row, 0, name_item)

            # Column 1: Window matching info
            match_text = self._get_window_match_text(profile)
            match_item = QTableWidgetItem(match_text)
            match_item.setData(Qt.UserRole, profile)  # Store profile object here too
            self.profile_table.setItem(row, 1, match_item)

            # Column 2: Active checkbox
            self._add_active_checkbox(row, profile)

            # Select default profile by default
            if profile.name == 'default':
                self.profile_table.selectRow(row)
                self.current_profile = profile
                self.profile_selected.emit(profile)

        logger.info(f"Loaded {len(displayed_profiles)} profiles (filtered out {len(profiles) - len(displayed_profiles)} internal profiles)")

        # Enable/disable delete button
        self._update_button_states()

    def get_selected_profile(self) -> Optional[Profile]:
        """Get the currently selected profile

        Returns:
            Selected Profile object, or None if no selection
        """
        return self.current_profile

    def reselect_current_profile(self):
        """Reselect the current profile in the list (used to cancel profile switch)"""
        if not self.current_profile:
            return

        # Find and select the current profile in the table
        for row in range(self.profile_table.rowCount()):
            name_item = self.profile_table.item(row, 0)
            profile = name_item.data(Qt.UserRole)
            if profile == self.current_profile:
                # Block signals to prevent triggering selection change
                self.profile_table.blockSignals(True)
                self.profile_table.selectRow(row)
                self.profile_table.blockSignals(False)
                logger.debug(f"Reselected profile: {self.current_profile.name}")
                break

    def _reload_profile_list(self):
        """Reload the profile list display (after editing profile settings)"""
        # Remember current selection
        current_profile = self.current_profile

        # Block signals to prevent triggering selection events
        self.profile_table.blockSignals(True)

        # Clear and rebuild table
        self.profile_table.setRowCount(0)
        # Filter out the TuxBox GUI meta-configuration profile
        displayed_profiles = [p for p in self.profiles if p.name not in ('TuxBox GUI', 'TourBox GUI')]
        for row, profile in enumerate(displayed_profiles):
            self.profile_table.insertRow(row)

            # Column 0: Profile name (with warning icon if conflicts exist)
            conflicts = self._get_conflicting_profiles(profile)
            if conflicts:
                conflict_names = ", ".join(c.name for c in conflicts)
                tooltip = _("Conflict: Multiple active profiles match the same "
                            "application.\nConflicts with: %s\nOnly the first "
                            "alphabetically will be used.") % (conflict_names,)
                # Use a QLabel with HTML to color only the warning icon
                label = QLabel(_('<span style="color: #ffaa00;">⚠</span> %s') % (profile.name,))
                label.setToolTip(tooltip)
                label.setContentsMargins(4, 0, 0, 0)  # Left padding to match other cells
                # Store profile in a hidden item for data retrieval
                name_item = QTableWidgetItem()
                name_item.setData(Qt.UserRole, profile)
                self.profile_table.setItem(row, 0, name_item)
                self.profile_table.setCellWidget(row, 0, label)
            else:
                name_item = QTableWidgetItem(profile.name)
                name_item.setData(Qt.UserRole, profile)
                self.profile_table.setItem(row, 0, name_item)

            # Column 1: Window matching info
            match_text = self._get_window_match_text(profile)
            match_item = QTableWidgetItem(match_text)
            match_item.setData(Qt.UserRole, profile)
            self.profile_table.setItem(row, 1, match_item)

            # Column 2: Active checkbox
            self._add_active_checkbox(row, profile)

            # Reselect the current profile
            if profile == current_profile:
                self.profile_table.selectRow(row)

        # Re-enable signals
        self.profile_table.blockSignals(False)

        logger.debug("Profile list reloaded")

    def _on_profile_selection_changed(self, currentRow, currentColumn, previousRow, previousColumn):
        """Handle profile selection change (mouse click or keyboard navigation)"""
        if currentRow < 0:
            return

        # Get profile from the name column (column 0)
        name_item = self.profile_table.item(currentRow, 0)
        if name_item is None:
            return

        profile = name_item.data(Qt.UserRole)
        self.current_profile = profile
        logger.info(f"Selected profile: {profile.name}")
        self.profile_selected.emit(profile)
        self._update_button_states()

    def _on_edit_profile(self):
        """Handle edit profile button click"""
        if not self.current_profile:
            return

        logger.info(f"Edit profile requested: {self.current_profile.name}")

        # Open profile settings dialog
        dialog = ProfileSettingsDialog(self.current_profile, self, is_new=False)
        if dialog.exec() == QDialog.Accepted:
            # Get results
            name, app_id, window_class, haptic_strength, haptic_speed, double_click_timeout, modifier_delay = dialog.get_results()

            # Update profile object
            old_name = self.current_profile.name
            self.current_profile.name = name
            self.current_profile.app_id = app_id if app_id else None
            self.current_profile.window_class = window_class if window_class else None
            self.current_profile.window_title = None  # No longer used

            # Update haptic config (Phase 1: global setting with speed)
            self.current_profile.haptic_config.set_global(haptic_strength, haptic_speed)

            # Update double-click timeout
            self.current_profile.double_click_timeout = double_click_timeout

            # Update modifier delay override
            self.current_profile.modifier_delay = modifier_delay

            logger.info(f"Profile updated: {self.current_profile}")
            logger.info(f"  Haptic: {haptic_strength}, Speed: {haptic_speed}")
            logger.info(f"  Double-click timeout: {double_click_timeout}ms")
            logger.info(f"  Modifier delay: {modifier_delay if modifier_delay is not None else 'global'}")

            # Reload the list to show updated info
            self._reload_profile_list()

            # Emit signal that profiles changed (so main window can mark as modified)
            self.profiles_changed.emit()

            # Show success message if name changed
            if name != old_name:
                QMessageBox.information(
                    self,
                    _("Profile Updated"),
                    _("Profile renamed from '%(old)s' to '%(new)s'.\n\n"
                      "Remember to save to apply changes.") % {'old': old_name, 'new': name}
                )

    def _on_new_profile(self):
        """Handle new profile button click"""
        logger.info("New profile requested")

        # Ask for profile name
        name, ok = QInputDialog.getText(
            self,
            _("New Profile"),
            _("Enter a name for the new profile:"),
            # Translators: default name offered for a new profile; the user can edit it.
            text=_("new_profile")
        )

        if not ok or not name.strip():
            return

        name = name.strip()

        # Validate name
        if ':' in name or '[' in name or ']' in name:
            QMessageBox.warning(
                self,
                _("Invalid Name"),
                _("Profile name cannot contain ':', '[', or ']' characters.")
            )
            return

        # Check if name already exists
        for profile in self.profiles:
            if profile.name == name:
                QMessageBox.warning(
                    self,
                    _("Name Exists"),
                    _("A profile named '%s' already exists.\nPlease choose a different name.") % (name,)
                )
                return

        # Ask if they want to copy current profile or start empty
        reply = QMessageBox.question(
            self,
            _("Copy Profile?"),
            _("Do you want to copy settings from the current profile ('%s')?\n\nClick 'Yes' to copy all button mappings.\nClick 'No' to start with empty mappings.") % (self.current_profile.name,),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        # Create new profile
        if reply == QMessageBox.Yes:
            # Copy from current profile
            new_profile = Profile(
                name=name,
                window_class=None,
                window_title=None,
                app_id=None,
                mapping=self.current_profile.mapping.copy() if self.current_profile.mapping else {},
                capabilities=self.current_profile.capabilities.copy() if self.current_profile.capabilities else {}
            )
            logger.info(f"Created new profile '{name}' based on '{self.current_profile.name}'")
        else:
            # Start with empty mappings
            new_profile = Profile(
                name=name,
                window_class=None,
                window_title=None,
                app_id=None,
                mapping={},
                capabilities={}
            )
            logger.info(f"Created new empty profile '{name}'")

        # Add to profiles list
        self.profiles.append(new_profile)

        # Reload the list
        self._reload_profile_list()

        # Select the new profile
        for row in range(self.profile_table.rowCount()):
            name_item = self.profile_table.item(row, 0)
            profile = name_item.data(Qt.UserRole)
            if profile.name == name:
                self.profile_table.selectRow(row)
                break

        # Emit signal that profiles changed
        self.profiles_changed.emit()

        # Ask if they want to set window matching now
        reply = QMessageBox.question(
            self,
            _("Window Matching"),
            _("Profile '%s' created successfully!\n\nWould you like to set up window matching rules now?") % (name,),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self._on_edit_profile()

    def _on_delete_profile(self):
        """Handle delete profile button click"""
        if not self.current_profile:
            return

        # Prevent deleting default profile
        if self.current_profile.name == 'default':
            QMessageBox.warning(
                self,
                _("Cannot Delete"),
                _("The default profile cannot be deleted.")
            )
            return

        # Confirm deletion
        reply = QMessageBox.question(
            self,
            _("Delete Profile"),
            _("Are you sure you want to delete profile '%s'?") % (self.current_profile.name,),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            logger.info(f"Deleting profile: {self.current_profile.name}")

            profile_to_delete = self.current_profile

            # Check if profile exists in config file (may be new, unsaved profile)
            from .config_writer import profile_exists_in_config
            profile_was_in_config = profile_exists_in_config(profile_to_delete.name)

            if profile_was_in_config:
                # Delete from config file
                success = delete_profile(profile_to_delete.name)
            else:
                # Profile doesn't exist in config yet (new, unsaved)
                logger.info(f"Profile '{profile_to_delete.name}' not in config, removing from memory only")
                success = True

            if success:
                if profile_was_in_config:
                    # Profile was saved - deletion is already saved to config file by delete_profile()
                    # Remove from memory
                    self.profiles.remove(profile_to_delete)

                    # Select default profile
                    default_profile = None
                    for i, profile in enumerate(self.profiles):
                        if profile.name == 'default':
                            self.current_profile = profile
                            default_profile = profile
                            break

                    # Reload the list
                    self._reload_profile_list()

                    # Emit profiles_reset to update main window without unsaved changes check
                    # Deletion was already saved, no need to prompt
                    if default_profile:
                        self.profiles_reset.emit(default_profile)
                else:
                    # Profile was never saved - reload from config to reset state
                    from tuxbox.config_loader import load_profiles
                    self.profiles = load_profiles()

                    # Select default profile
                    for profile in self.profiles:
                        if profile.name == 'default':
                            self.current_profile = profile
                            break

                    # Reload the list
                    self._reload_profile_list()

                    # Emit reset signal to clear modified state without unsaved changes check
                    self.profiles_reset.emit(self.current_profile)

                # Show success message
                QMessageBox.information(
                    self,
                    _("Profile Deleted"),
                    _("Profile '%s' has been deleted successfully.") % (profile_to_delete.name,)
                )

                logger.info(f"Profile deleted: {profile_to_delete.name}")
            else:
                QMessageBox.critical(
                    self,
                    _("Deletion Failed"),
                    _("Failed to delete profile '%s'.\n\nCheck the logs for details.") % (profile_to_delete.name,)
                )

    def _get_window_match_text(self, profile: Profile) -> str:
        """Get window matching display text for a profile

        Args:
            profile: Profile object

        Returns:
            Formatted window matching text
        """
        # Leave default profile's window column blank
        if profile.name == 'default':
            return ""

        # Prefer window_class, but show which one is being used
        if profile.window_class:
            return f"class: {profile.window_class}"
        elif profile.app_id:
            return f"app_id: {profile.app_id}"
        else:
            return ""

    def _get_conflicting_profiles(self, profile: Profile) -> List[Profile]:
        """Find other enabled profiles that match the same application

        Args:
            profile: Profile to check for conflicts

        Returns:
            List of conflicting Profile objects (excluding the profile itself)
        """
        if not profile.enabled or profile.name == 'default':
            return []

        # Get all matching values for this profile (window_class and/or app_id)
        profile_values = {v.lower() for v in [profile.window_class, profile.app_id] if v}

        # Skip profiles with no window matching
        if not profile_values:
            return []

        conflicts = []
        for other in self.profiles:
            # Skip self, disabled profiles, and default
            if other.name == profile.name or not other.enabled or other.name == 'default':
                continue

            # Get all matching values for the other profile
            other_values = {v.lower() for v in [other.window_class, other.app_id] if v}

            # Conflict if any values overlap
            if profile_values & other_values:
                conflicts.append(other)

        return conflicts

    def _add_active_checkbox(self, row: int, profile: Profile):
        """Add active checkbox to a table row

        Args:
            row: Table row index
            profile: Profile object
        """
        # Create a container widget to center the checkbox
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)

        checkbox = QCheckBox()
        checkbox.setChecked(profile.enabled)
        checkbox.setProperty("profile_name", profile.name)

        # Default profile is always enabled - disable the checkbox
        if profile.name == 'default':
            checkbox.setEnabled(False)
            checkbox.setToolTip(_("Default profile is always active"))
        else:
            checkbox.setToolTip(_("Enable/disable this profile for automatic window matching"))
            checkbox.stateChanged.connect(self._on_active_toggled)

        layout.addWidget(checkbox)
        self.profile_table.setCellWidget(row, 2, container)

    def _on_active_toggled(self, state: int):
        """Handle active checkbox state change

        Args:
            state: Qt.Checked or Qt.Unchecked
        """
        checkbox = self.sender()
        if not checkbox:
            return

        profile_name = checkbox.property("profile_name")
        enabled = state == Qt.Checked.value

        # Find the profile
        profile = None
        for p in self.profiles:
            if p.name == profile_name:
                profile = p
                break

        if not profile:
            logger.error(f"Could not find profile: {profile_name}")
            return

        # Update profile enabled state
        profile.enabled = enabled
        logger.info(f"Profile '{profile_name}' enabled: {enabled}")

        # Save the profile
        filepath = get_profile_filepath(profile_name)
        if save_profile_to_file(profile, filepath):
            logger.info(f"Saved profile: {profile_name}")

            # Reload driver config via SIGHUP
            success, message = DriverManager.reload_driver()
            if success:
                logger.info(f"Driver reloaded: {message}")
            else:
                logger.warning(f"Failed to reload driver: {message}")

            # Refresh the profile list to update conflict warnings
            self._reload_profile_list()
        else:
            logger.error(f"Failed to save profile: {profile_name}")
            # Revert the checkbox state
            checkbox.blockSignals(True)
            checkbox.setChecked(not enabled)
            checkbox.blockSignals(False)
            QMessageBox.critical(
                self,
                _("Save Failed"),
                _("Failed to save profile '%s'.") % (profile_name,)
            )

    def _update_button_states(self):
        """Update button enabled/disabled states"""
        has_selection = self.current_profile is not None
        is_default = has_selection and self.current_profile.name == 'default'

        # Can't edit default profile (no point in setting window matching for it)
        self.edit_button.setEnabled(has_selection and not is_default)

        # Can't delete if nothing selected or if default profile
        self.delete_button.setEnabled(has_selection and not is_default)

        # Export requires a selection
        self.export_button.setEnabled(has_selection)

    def _on_import_profile(self):
        """Handle Import button click"""
        # Open file dialog
        file_path, _unused = QFileDialog.getOpenFileName(
            self,
            _("Import Profile"),
            "",
            _("Profile Files (*.profile);;All Files (*)")
        )

        if not file_path:
            return  # User cancelled

        # Import the profile
        profile, error = import_profile(file_path)

        if profile is None:
            QMessageBox.critical(
                self,
                _("Import Failed"),
                _('Failed to import profile:\n\n%s') % (error,)
            )
            return

        # Check for name conflict
        if profile_exists_in_config(profile.name):
            # Show conflict dialog
            dialog = ImportConflictDialog(profile.name, self)
            if dialog.exec() != QDialog.Accepted:
                return  # User cancelled

            action, new_name = dialog.get_result()

            if action == ImportConflictDialog.CANCEL:
                return

            if action == ImportConflictDialog.RENAME:
                # Check new name doesn't also conflict
                if profile_exists_in_config(new_name):
                    QMessageBox.critical(
                        self,
                        _("Import Failed"),
                        _("A profile named '%s' also already exists.") % (new_name,)
                    )
                    return

                # Update profile name
                profile.name = new_name

            elif action == ImportConflictDialog.REPLACE:
                # Delete existing profile first
                if not delete_profile(profile.name):
                    QMessageBox.critical(
                        self,
                        _("Import Failed"),
                        _("Failed to replace existing profile '%s'.") % (profile.name,)
                    )
                    return

        # Install the profile
        if install_imported_profile(profile):
            # Reload profiles
            from tuxbox.config_loader import load_profiles
            self.profiles = load_profiles()
            self._reload_profile_list()

            # Select the imported profile
            for row in range(self.profile_table.rowCount()):
                name_item = self.profile_table.item(row, 0)
                if name_item and name_item.text() == profile.name:
                    self.profile_table.selectRow(row)
                    break

            QMessageBox.information(
                self,
                _("Import Successful"),
                _("Profile '%s' has been imported successfully.") % (profile.name,)
            )

            # Emit signal to notify of changes
            self.profiles_changed.emit()
        else:
            QMessageBox.critical(
                self,
                _("Import Failed"),
                _("Failed to save imported profile.")
            )

    def _on_export_profile(self):
        """Handle Export button click"""
        if not self.current_profile:
            return

        # Suggest a filename based on profile name
        from tuxbox.profile_io import sanitize_profile_filename
        suggested_name = f"{sanitize_profile_filename(self.current_profile.name)}.profile"

        # Open file dialog
        file_path, _unused = QFileDialog.getSaveFileName(
            self,
            _("Export Profile"),
            suggested_name,
            _("Profile Files (*.profile);;All Files (*)")
        )

        if not file_path:
            return  # User cancelled

        # Ensure .profile extension
        if not file_path.endswith('.profile'):
            file_path += '.profile'

        # Export the profile
        if export_profile(self.current_profile, file_path):
            QMessageBox.information(
                self,
                _("Export Successful"),
                _("Profile '%(profile)s' has been exported to:\n\n%(path)s") % {
                    'profile': self.current_profile.name, 'path': file_path,
                }
            )
        else:
            QMessageBox.critical(
                self,
                _("Export Failed"),
                _("Failed to export profile '%s'.") % (self.current_profile.name,)
            )
