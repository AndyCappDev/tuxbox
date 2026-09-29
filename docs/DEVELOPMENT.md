# TuxBox Driver - Development Guide

This guide is for developers who want to work on, debug, or contribute to the TuxBox driver.

## Table of Contents

- [Development Setup](#development-setup)
- [Running the Driver](#running-the-driver)
- [Running the GUI](#running-the-gui)
- [Debugging](#debugging)
- [Project Structure](#project-structure)
- [Development Workflow](#development-workflow)
- [GUI Development](#gui-development)
- [Testing](#testing)
- [Contributing](#contributing)

## Development Setup

### Installation

For complete installation instructions including prerequisites, system dependencies, and setup, see the [README.md](../README.md).

The README covers:
- System requirements and dependencies
- Finding your TourBox MAC address
- Installation via `install.sh`
- Manual installation steps
- Additional requirements for KDE Plasma and GNOME

### Developer-Specific Setup

For development work, install the package in editable mode:

```bash
# Navigate to repository
cd /path/to/tuxbox

# Install in editable/development mode
./venv/bin/pip install -e .
```

This allows you to modify the code and test changes without reinstalling the package.

### GUI Dependencies

The GUI requires additional PySide6 (Qt 6) dependencies:

```bash
# Install GUI dependencies
./venv/bin/pip install -r tuxbox/gui/requirements.txt
```

GUI dependencies include:
- `PySide6` - Qt 6 Python bindings
- `qasync` - Asyncio integration for Qt event loop

## Running the Driver

### Running Directly (Recommended for Development)

Stop the systemd service first to avoid conflicts:

```bash
# Stop the service if it's running
systemctl --user stop tuxbox
```

Run directly in your terminal:

```bash
# Basic run (auto-detects USB if connected, falls back to BLE)
./venv/bin/python -m tuxbox

# With verbose logging (shows all button events)
./venv/bin/python -m tuxbox -v

# Force USB mode (even if BLE would work)
./venv/bin/python -m tuxbox --usb -v

# Force BLE mode (even if USB is connected)
./venv/bin/python -m tuxbox --ble -v

# Specify MAC address via command line (overrides config, BLE only)
./venv/bin/python -m tuxbox --ble D9:BE:1E:CC:40:D7

# Specify custom config file
./venv/bin/python -m tuxbox -c /path/to/custom/config.conf

# Combine options
./venv/bin/python -m tuxbox -v -c custom.conf
```

**Press `Ctrl+C` to stop.**

### Running as a Service (Production Mode)

```bash
# Start service
systemctl --user start tuxbox

# View live logs
journalctl --user -u tuxbox -f

# Stop service
systemctl --user stop tuxbox

# Restart service (after code changes)
systemctl --user restart tuxbox
```

### Command Line Options

```bash
./venv/bin/python -m tuxbox --help
```

Available options:
- `mac_address` - Bluetooth MAC address (optional, overrides config file, BLE only)
- `--usb` - Force USB mode (use /dev/ttyACM0)
- `--ble` - Force Bluetooth LE mode
- `-c, --config` - Path to custom config file
- `-v, --verbose` - Enable verbose/debug logging

**Auto-detection:** If neither `--usb` nor `--ble` is specified, the driver automatically detects the connection type:
- If `/dev/ttyACM0` exists -> uses USB
- Otherwise -> uses Bluetooth LE

## Running the GUI

### Running the GUI for Development

The GUI can be run directly from your development directory:

```bash
# Run GUI using development virtual environment
./venv/bin/python -m tuxbox.gui

# Or if you have a development launcher script
tuxbox-gui
```

The GUI provides:
- Visual profile management (create, edit, delete profiles)
- Button mapping configuration with visual TourBox controller view
- Live testing of button mappings
- Profile settings (window matching rules)
- Driver management (start/stop/restart systemd service)

### GUI for End Users

After installation via `install.sh`, users can launch the GUI with:

```bash
tuxbox-gui
```

The installation script creates a launcher at `/usr/local/bin/tuxbox-gui`.

For complete GUI usage instructions, see [GUI_USER_GUIDE.md](GUI_USER_GUIDE.md).

## Debugging

### Verbose Logging

Enable verbose logging to see detailed button events:

```bash
./venv/bin/python -m tuxbox -v
```

Output shows:
- Button press/release events with hex codes
- Profile switching events
- Window focus changes
- USB/BLE connection status
- Input event generation

Example output:
```
2025-11-01 21:56:19,217 - tuxbox.config_loader - INFO - Loading profiles from /home/scott/.config/tuxbox/mappings.conf
2025-11-01 21:56:19,218 - __main__ - INFO - Loaded 4 profiles
2025-11-01 21:56:19,234 - tuxbox.window_monitor - INFO - Detected Wayland compositor: kde
2025-11-01 21:56:19,234 - __main__ - INFO - Connecting to TourBox at D9:BE:1E:CC:40:D7...

Button #1: 44 -> 4 events  # Knob CW rotation
Button #2: c4 -> 2 events  # Knob CW stop
```

### Debug Button Codes

To see raw button codes without mapping them, use the test scripts:

```bash
# Stop the service first
systemctl --user stop tuxbox

# Run the USB test script (if connected via USB)
cd /path/to/tuxbox
./venv/bin/python usb_test_tuxbox.py

# Or run the BLE test script (if using Bluetooth)
./venv/bin/python ble_test_tuxbox.py

# Press buttons and observe hex codes
# Press Ctrl+C when done

# Restart the service
systemctl --user start tuxbox
```

See the [BUTTON_MAPPING_GUIDE.md](BUTTON_MAPPING_GUIDE.md) for complete instructions on capturing and documenting button codes.

### Test Window Detection

Test window focus detection without running the full driver:

```bash
./venv/bin/python -m tuxbox.window_monitor
```

This shows:
- Current focused window
- Window class/app_id
- Window title
- Which profile would be activated

### Monitor Bluetooth Events

```bash
# Watch Bluetooth logs
journalctl -f | grep -i blue

# Monitor BLE connection
bluetoothctl
# Then: info D9:BE:1E:CC:40:D7
```

### Check Input Device

```bash
# List input devices (TuxBox should appear when driver is running)
ls -la /dev/input/by-id/

# Monitor events from TuxBox
sudo evtest
# Select "TuxBox" from the list
```

## Project Structure

```
tuxbox/
├── tuxbox/                                        # Main package
│   ├── __init__.py                                 # Version info
│   ├── __main__.py                                 # Unified entry point with auto-detection
│   ├── device_base.py                              # Abstract base class with shared logic
│   ├── device_ble.py                               # Bluetooth LE driver (TuxBoxBLE class)
│   ├── device_usb.py                               # USB serial driver (TuxBoxUSB class)
│   ├── config_loader.py                            # Config file parsing and profile management
│   ├── window_monitor.py                           # Wayland window detection
│   ├── default_mappings.conf                       # Default configuration template
│   └── gui/                                        # GUI package
│       ├── __init__.py                             # GUI package init
│       ├── __main__.py                             # GUI entry point
│       ├── main_window.py                          # Main window (orchestrates all components)
│       ├── profile_manager.py                      # Profile list widget (CRUD operations)
│       ├── controls_list.py                        # Controls table widget (displays mappings)
│       ├── control_editor.py                       # Control mapping editor widget
│       ├── controller_view.py                      # Visual TourBox controller view (SVG-based)
│       ├── profile_settings_dialog.py              # Profile settings dialog (window matching)
│       ├── device_settings_dialog.py               # Global [device] settings dialog
│       ├── driver_manager.py                       # Driver service management widget
│       ├── ble_listener.py                         # BLE event listener for live testing
│       ├── config_writer.py                        # Config file write operations (atomic saves)
│       ├── device_config_writer.py                 # [device] section writes (preserves comments)
│       ├── README.md                               # GUI package documentation
│       ├── requirements.txt                        # GUI-specific dependencies (PySide6, qasync)
│       └── assets/                                 # GUI assets
│           ├── tourbox_elite.svg                   # Main controller SVG image (Text converted to paths)
│           ├── tourbox_elite_org.svg               # Original controller SVG
│           ├── tourbox-icon.svg                    # Application icon (SVG)
│           └── tourbox-icon.png                    # Application icon (PNG)
├── docs/                                           # Documentation
│   ├── CONFIG_GUIDE.md                             # Configuration documentation
│   ├── DEVELOPMENT.md                              # This file
│   ├── GUI_USER_GUIDE.md                           # GUI user documentation
│   ├── BUTTON_MAPPING_GUIDE.md                     # Button reference for protocol work
│   ├── images/                                     # Documentation images
│   │   └── gui-screenshot.png                      # GUI screenshot
│   └── technical/                                  # Technical documentation
│       ├── TOURBOX_ELITE_PROTOCOL_SOLVED.md        # BLE protocol docs
│       ├── KDOTOOL_INFO.md                         # KDE window detection info
│       ├── LOG_MANAGEMENT.md                       # Logging documentation
│       └── WINDOWS_BLE_CAPTURE_GUIDE.md            # Windows BLE capture guide
├── ble_test_tuxbox.py                             # BLE test script for capturing button codes
├── usb_test_tuxbox.py                             # USB test script for capturing button codes
├── ble_test_events.py                              # Test script to find TourBox input device
├── monitor_keys.py                                 # Utility to monitor key events
├── install.sh                                      # Installation script (includes GUI deps & launcher)
├── uninstall.sh                                    # Uninstallation script (removes GUI launcher)
├── install_config.sh                               # Config installer (for manual setup)
├── tuxbox-gui.desktop                              # Desktop integration file for GUI launcher
├── setup.py                                        # Python package setup
├── setup.cfg                                       # Python package metadata (includes GUI entry point)
├── requirements.txt                                # Python dependencies
├── LICENSE.txt                                     # License file
├── .gitignore                                      # Git ignore patterns
└── README.md                                       # User documentation
```

### Key Files

#### Core Driver Files

**`__main__.py`** - Unified entry point
- Auto-detects USB vs BLE connection
- Checks for `/dev/ttyACM0` existence
- Command-line argument parsing
- Launches appropriate driver (USB or BLE)

**`device_base.py`** - Abstract base class
- `TuxBoxBase` abstract class with shared logic
- Button event processing (`process_button_code()`)
- Modifier key state machine
- Profile switching
- Virtual input device creation via UInput
- Window monitoring integration

**`device_ble.py`** - Bluetooth LE driver
- `TuxBoxBLE` class (inherits from TuxBoxBase)
- BLE connection handling via Bleak
- GATT characteristic setup
- BLE-specific unlock sequence

**`device_usb.py`** - USB serial driver
- `TuxBoxUSB` class (inherits from TuxBoxBase)
- USB serial connection via pyserial
- `/dev/ttyACM0` communication
- USB-specific initialization

**`config_loader.py`** - Configuration
- Parse INI config files
- Profile management
- Button mapping creation
- Button code definitions
- Capability detection

**`window_monitor.py`** - Window detection (Wayland)
- KDE/Plasma support (KWin via D-Bus)
- GNOME support (Mutter via D-Bus extension)
- Sway support
- Hyprland support

**`ble_test_tuxbox.py`** - BLE test script
- Captures raw button codes via Bluetooth LE
- Sends unlock and config commands
- Used for BLE protocol debugging

**`usb_test_tuxbox.py`** - USB test script
- Captures raw button codes via USB serial
- Sends unlock and config commands
- Used for USB protocol debugging

#### GUI Files

**`gui/main_window.py`** - Main GUI window (~900 LOC)
- Central coordinator for all GUI components
- Orchestrates profile management, control editing, testing
- Handles unsaved changes detection and prompts
- Manages signal flow between components
- Implements save/test/close workflows

**`gui/profile_manager.py`** - Profile management widget (~455 LOC)
- Profile list display (name, window matching rules)
- Profile CRUD operations (create, edit, delete)
- Emits signals: `profile_selected`, `profiles_changed`, `profiles_reset`
- Prevents deletion of default profile
- Handles both saved and unsaved profile states

**`gui/controls_list.py`** - Controls table widget (~303 LOC)
- Displays all 20 TourBox controls and their mappings
- Shows human-readable action names (e.g., "Ctrl+Z", "Wheel Up")
- Converts evdev key codes to friendly names
- Emits `control_selected` signal when user clicks a control

**`gui/control_editor.py`** - Control mapping editor widget (~350 LOC)
- Edit button/rotary mappings with key capture
- Dropdown for common actions (copy, paste, undo, etc.)
- Multi-key capture for combinations (Ctrl+Alt+X)
- Wheel direction selection for rotary controls
- Clear/reset functionality

**`gui/controller_view.py`** - Visual controller view (~200 LOC)
- SVG-based visual representation of TourBox controller
- Shows which control is currently selected
- Highlights controls with colored overlays
- Click-to-select functionality

**`gui/profile_settings_dialog.py`** - Profile settings dialog (~120 LOC)
- Edit profile name and window matching rules
- Window class and app_id configuration
- Used when creating/editing profiles
- Input validation for profile names

**`gui/device_settings_dialog.py`** - Global settings dialog (~230 LOC)
- Edit the `[device]` section: connection mode, USB port, haptics, timings
- Returns only the settings the user actually changed
- Offers a driver restart, since none of these are re-read while running

**`gui/device_config_writer.py`** - `[device]` section writes (~200 LOC)
- Edits config.conf line by line, preserving comments and unrecognised keys
- Uncomments template placeholders in place instead of appending duplicates
- Atomic replace with timestamped backup and restore-on-failure

**`gui/driver_manager.py`** - Driver service management (~150 LOC)
- Start/stop/restart systemd service
- Display service status (running/stopped/not installed)
- Real-time status updates
- Service log viewing

**`gui/ble_listener.py`** - BLE event listener (~120 LOC)
- Listens for button events from TourBox during live testing
- Async BLE connection and event monitoring
- Used by Test functionality in main window
- Runs concurrently with GUI to provide real-time feedback

**`gui/config_writer.py`** - Config file operations (~250 LOC)
- Atomic config file saves with backup rotation
- Create new profiles
- Save profile metadata (name, window matching)
- Save button mappings
- Delete profiles
- Keeps 5 backup files (.bak.1 through .bak.5)

## Development Workflow

### Making Changes

1. **Stop the service** to avoid conflicts:
   ```bash
   systemctl --user stop tuxbox
   ```

2. **Make your changes** to the code

3. **Test directly** with verbose logging:
   ```bash
   ./venv/bin/python -m tuxbox -v
   ```

4. **Test your changes** by pressing buttons on the TourBox

5. **Verify** the output shows expected behavior

6. **Restart service** when done testing:
   ```bash
   systemctl --user restart tuxbox
   ```

### Editing Configuration

```bash
# Edit a profile (new format)
nano ~/.config/tuxbox/profiles/default.profile

# Or edit device settings
nano ~/.config/tuxbox/config.conf

# Test changes immediately
./venv/bin/python -m tuxbox -v

# Or restart service
systemctl --user restart tuxbox
```

### Adding New Button Mappings

1. **Find the button code** - Run with verbose mode and press the button:
   ```bash
   ./venv/bin/python -m tuxbox -v
   # Press the button
   # Look for: "Unknown button code: XX" or "Button #N: XX -> Y events"
   ```

2. **Add to `config_loader.py`** in the `BUTTON_CODES` dict:
   ```python
   BUTTON_CODES = {
       'new_button': (0xXX, 0xYY),  # press, release
       # or for rotary:
       'new_rotary_cw': (0xXX, 0xYY),  # rotate, stop
   }
   ```

3. **Add to config file** `default_mappings.conf`:
   ```ini
   [buttons]
   new_button = KEY_SOMETHING

   [rotary]
   new_rotary_cw = KEY_VOLUMEUP
   ```

4. **Test** the new mapping

### Adding New Keys

If you need a key that's not in `KEY_NAMES`:

1. **Find the evdev key code**:
   ```python
   import evdev.ecodes as e
   print(e.KEY_YOURKEY)  # Get the code
   ```

2. **Add to `config_loader.py`** in the `KEY_NAMES` dict:
   ```python
   KEY_NAMES = {
       'KEY_YOURKEY': e.KEY_YOURKEY,
   }
   ```

3. **Use in config**:
   ```ini
   side = KEY_YOURKEY
   ```

### Adding Profile Support for New Compositor

Edit `window_monitor.py`:

1. **Detect the compositor** in `detect_compositor()`:
   ```python
   def detect_compositor():
       # Add detection logic
       if os.environ.get('YOUR_COMPOSITOR_VAR'):
           return 'your_compositor'
   ```

2. **Implement window monitoring**:
   ```python
   async def monitor_your_compositor(self):
       # Implement window focus detection
       # Call self.callback(window_info) when window changes
   ```

3. **Add to `start_monitoring()`**:
   ```python
   if self.compositor == 'your_compositor':
       await self.monitor_your_compositor()
   ```

## GUI Development

### GUI Architecture

The GUI uses a signal-based architecture built with PySide6 (Qt 6):

- **Signal Flow**: Components communicate via Qt signals
  - `profile_selected` - User selects a different profile (triggers unsaved changes check)
  - `profiles_changed` - Profile metadata changed (marks as modified)
  - `profiles_reset` - Profiles reloaded from config (clears modified state)
  - `control_selected` - User clicks a control in the table
  - `mapping_changed` - User changes a control mapping

- **State Management**: Main window tracks:
  - `current_profile` - Currently selected profile
  - `is_modified` - Has profile metadata changed?
  - `modified_mappings` - Dict of changed button mappings
  - `profile_original_names` - Tracks profile renames using `id(profile)` as key

- **Atomic Saves**: Config writer implements atomic writes with backup rotation
  - Writes to temporary file first
  - Rotates existing backups (.bak.1 -> .bak.2, etc.)
  - Moves temp file to final location
  - Keeps 5 backup files

### Making GUI Changes

1. **Stop the GUI** if running

2. **Make your changes** to GUI code

3. **Test directly**:
   ```bash
   ./venv/bin/python -m tuxbox.gui
   ```

4. **Check for errors** in terminal output (Qt errors, Python exceptions)

5. **Test all workflows**:
   - Create/edit/delete profiles
   - Edit button mappings
   - Save changes
   - Test button mappings
   - Handle unsaved changes prompts

### Adding a New Control Type

If adding support for a new TourBox model with different controls:

1. **Update `BUTTON_CODES`** in `config_loader.py`:
   ```python
   BUTTON_CODES = {
       'new_control': (0xXX, 0xYY),  # press/release codes
   }
   ```

2. **Add to `CONTROL_NAMES`** in `controls_list.py`:
   ```python
   CONTROL_NAMES = [
       'side', 'top', 'tall', 'short',
       'new_control',  # Add here
   ]
   ```

3. **Add display name** to `CONTROL_DISPLAY_NAMES`:
   ```python
   CONTROL_DISPLAY_NAMES = {
       'new_control': 'New Control Button',
   }
   ```

4. **Update SVG assets** in `gui/assets/` if adding visual elements

5. **Test** with the GUI

### GUI Development Tips

- **Use Qt Designer?** No - all layouts are built programmatically for easier version control
- **Debugging signals**: Add logging to signal handlers to trace signal flow
- **Testing dialogs**: Use `dialog.exec()` to test modal dialogs interactively
- **PySide6 docs**: https://doc.qt.io/qtforpython-6/
- **Qt signals/slots**: Signals connect components without tight coupling

### Common GUI Tasks

**Add a new signal to a widget:**
```python
from PySide6.QtCore import Signal

class MyWidget(QWidget):
    # Define signal
    something_changed = Signal(str)  # str argument

    def some_method(self):
        # Emit signal
        self.something_changed.emit("value")
```

**Connect a signal in main window:**
```python
self.my_widget.something_changed.connect(self._on_something_changed)

def _on_something_changed(self, value: str):
    logger.info(f"Something changed: {value}")
```

**Show a message box:**
```python
from PySide6.QtWidgets import QMessageBox

QMessageBox.information(self, "Title", "Message text")
QMessageBox.warning(self, "Title", "Warning text")
QMessageBox.critical(self, "Title", "Error text")

# Ask a question
reply = QMessageBox.question(
    self, "Title", "Question?",
    QMessageBox.Yes | QMessageBox.No,
    QMessageBox.No  # Default button
)
if reply == QMessageBox.Yes:
    # User clicked Yes
```

**Update table contents:**
```python
# Clear table
self.table.setRowCount(0)

# Add rows
for row, item in enumerate(items):
    self.table.insertRow(row)
    self.table.setItem(row, 0, QTableWidgetItem(str(item)))

# Force update
self.table.viewport().update()
```

**Block signals temporarily:**
```python
# Prevent triggering signals during updates
self.widget.blockSignals(True)
# Make changes...
self.widget.blockSignals(False)
```

### GUI Testing Workflows

**Test unsaved changes handling:**
1. Create new profile
2. Edit a button mapping
3. Click another profile -> should prompt to save
4. Test all three options: Save, Discard, Cancel

**Test profile operations:**
1. Create profile (copy vs. empty)
2. Edit profile settings (name, window matching)
3. Delete profile (saved vs. unsaved)
4. Verify default profile cannot be deleted/edited

**Test button mapping:**
1. Select control in table
2. Change mapping in editor
3. Test mapping (should auto-save)
4. Verify mapping persists after app restart

**Test driver integration:**
1. Start/stop/restart driver
2. Check status updates
3. Verify driver uses saved config

## Testing

### Manual Testing Checklist

#### Core Driver Testing
- [ ] All buttons respond correctly
- [ ] Rotary controls (knob, scroll, dial) work smoothly
- [ ] Keys don't get stuck when rotating knobs
- [ ] Profile switching works (if using Wayland)
- [ ] Window detection is accurate
- [ ] Service starts on login
- [ ] Config changes apply after restart
- [ ] Driver reconnects after TourBox power cycle

#### GUI Testing
- [ ] GUI launches successfully (`tuxbox-gui`)
- [ ] All profiles load and display correctly
- [ ] Profile creation works (both copy and empty)
- [ ] Profile editing (name, window matching) works
- [ ] Profile deletion works (with confirmation)
- [ ] Cannot delete or edit default profile
- [ ] Controls list displays 20 controls for Elite and 12 for Lite
- [ ] Control mappings display correctly (readable names)
- [ ] Control editor captures key presses
- [ ] Multi-key combinations work (Ctrl+Alt+X)
- [ ] Wheel direction selection works for rotary controls
- [ ] Unsaved changes prompt appears when switching profiles
- [ ] Save button saves all changes to config file
- [ ] Test button saves and tests mappings
- [ ] Close without saving prompts correctly
- [ ] Controller view highlights selected control
- [ ] Driver status shows correct state
- [ ] Start/stop/restart driver buttons work
- [ ] Config backups are created (.bak.1 through .bak.5)

### Test Profile Switching

```bash
# Run with verbose logging
./venv/bin/python -m tuxbox -v

# Switch between applications (VSCode, Firefox, etc.)
# Watch console for profile switch messages:
# "Switched to profile: vscode"
```

### Test Button Events

```bash
# Run driver
./venv/bin/python -m tuxbox -v

# In another terminal, monitor input events
sudo evtest
# Select "TuxBox"
# Press buttons and verify events are generated
```

### Test Configuration Parsing

```python
# Quick test in Python
from tuxbox.config_loader import load_profiles

profiles = load_profiles()  # Automatically finds config location
for p in profiles:
    print(f"Profile: {p.name}")
    print(f"  Mapping: {p.mapping}")
```

### Test GUI

```bash
# Launch GUI
./venv/bin/python -m tuxbox.gui

# Check terminal for any errors or warnings
```

**Test workflow:**
1. Create a new profile (test both copy and empty options)
2. Edit the new profile's name and window matching
3. Select a control and change its mapping
4. Click another profile -> should prompt about unsaved changes
5. Test "Save", "Discard", and "Cancel" options
6. Use Test button to test mappings live
7. Verify changes persist after closing and reopening GUI
8. Delete the test profile
9. Check that config backups were created in `~/.config/tuxbox/`

**Test edge cases:**
- Try to delete default profile (should be prevented)
- Try to edit default profile settings (button should be disabled)
- Create profile without saving, then close GUI (should prompt)
- Create profile, change mappings, test (should auto-save)
- Rapidly switch between profiles (check for race conditions)

## Reverse Engineering & Protocol Work

### Button Mapping Guide

If you're working on supporting a new TourBox model or reverse-engineering the protocol, see [BUTTON_MAPPING_GUIDE.md](BUTTON_MAPPING_GUIDE.md).

This guide explains how to:
- Discover which raw BLE hex codes correspond to physical buttons
- Map button codes to Linux input events
- Test and document a new TourBox device
- Contribute protocol documentation

**Note:** This is a developer guide for protocol work, not for end users configuring their buttons (that's [CONFIG_GUIDE.md](CONFIG_GUIDE.md)).

### Protocol Documentation

See [TOURBOX_ELITE_PROTOCOL_SOLVED.md](technical/TOURBOX_ELITE_PROTOCOL_SOLVED.md) for complete BLE protocol documentation.

## Common Development Tasks

### Capture Raw Button Data

```python
# Temporarily add to device_ble.py handle_button_event():
def handle_button_event(self, sender: int, data: bytearray):
    data_bytes = bytes(data)
    print(f"RAW: {data_bytes.hex()}")  # See all raw data
```

### Test BLE Connection Only

```python
# Simple test script
import asyncio
from bleak import BleakClient

async def test_connection():
    mac = "D9:BE:1E:CC:40:D7"
    async with BleakClient(mac) as client:
        print(f"Connected: {client.is_connected}")
        services = await client.get_services()
        for service in services:
            print(f"Service: {service.uuid}")

asyncio.run(test_connection())
```

### Dump Current Config

```bash
# See profiles directory
ls -la ~/.config/tuxbox/profiles/

# View a specific profile
cat ~/.config/tuxbox/profiles/default.profile

# Or parse it programmatically
./venv/bin/python -c "
from tuxbox.config_loader import load_profiles
import pprint
profiles = load_profiles()
for p in profiles:
    print(f'\n{p.name}:')
    pprint.pprint(p.mapping)
"
```

### Check Dependencies

```bash
# List installed packages
./venv/bin/pip list

# Check specific package version
./venv/bin/pip show bleak
```

## Code Style

- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Add docstrings to functions and classes
- Keep functions focused and concise
- Add comments for complex logic

Example:
```python
async def handle_button_event(self, sender: int, data: bytearray):
    """Handle button press/release events from TourBox

    Args:
        sender: GATT characteristic handle
        data: Raw button data (1 byte indicating button/state)
    """
    # Implementation
```

## Contributing

### Controller artwork

The controller view loads `tuxbox/gui/assets/tourbox_<model>.svg` according
to the saved `controller_model` display preference. Elite remains the default.
The SVGs are included in distributions by the existing `assets/*.svg` rule.

Artwork must contain layers labelled `controls` and `modifiers` using the
same Inkscape namespace as the Elite asset. Each selectable control has a
hidden group with its internal control name as the ID; modifier groups use
the `m_` prefix. The view reveals these groups to highlight a selection.
Lite has no Side, D-Pad or Dial overlays. Outline ink uses `#000000` in
style attributes so the existing dark-theme recolouring applies.

`gui/controller_models.py` defines the controls for each model. The controls
and combination tables hide unavailable rows rather than deleting them, so
switching models preserves both saved mappings and pending edits. Combination
dialogs use the same model inventory.

The Lite SVG is an original vector drawing based on this supplied reference:
https://cdn.tourboxtech.com/prod/uploads/lite-bluetooth-bk-1_260907171449.webp
The reference photograph is not bundled with the package.

Also check model switching, individual and combination highlights, resizing,
and light/dark themes in the GUI. Record desktop and hardware testing
separately from the offscreen checks in the PR.

### Before Submitting

1. Test your changes thoroughly
   - Core driver: Test all buttons, rotary controls, profile switching
   - GUI: Test all workflows (create/edit/delete profiles, button mapping, save/test)
2. Update documentation if needed
   - README.md for user-facing changes
   - CONFIG_GUIDE.md or GUI_USER_GUIDE.md for configuration changes
   - DEVELOPMENT.md for developer-facing changes
3. Follow existing code style
4. Add comments for non-obvious code
5. Test with both simple mode and profile mode (if driver changes)
6. If GUI changes: Test on different Qt themes/desktop environments if possible

### Commit Messages

Use clear, descriptive commit messages:
```
Good (Driver):
- "Fix rotary control key release for knob zoom"
- "Add support for Hyprland window detection"
- "Update config parser to handle inline comments"

Good (GUI):
- "Fix infinite discard dialog loop when canceling profile switch"
- "Add visual controller view with SVG highlighting"
- "Implement atomic config saves with backup rotation"

Bad:
- "fix bug"
- "update"
- "changes"
```

## Getting Help

### Enable Maximum Logging

```python
# Edit __main__.py or device_base.py main():
logging.basicConfig(
    level=logging.DEBUG,  # Change from INFO to DEBUG
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### Common Issues

**"No module named 'tuxbox'"**
```bash
# Install in editable mode
./venv/bin/pip install -e .
```

**"Permission denied: /run/tuxbox.pid"**
```bash
# Use user runtime directory (already fixed in code)
# Or set manually:
pidfile=/tmp/tuxbox.pid ./venv/bin/python -m tuxbox
```

**"Connection failed"**
- Check TourBox is powered on
- Check Bluetooth is enabled: `bluetoothctl power on`
- Try pairing: `bluetoothctl pair D9:BE:1E:CC:40:D7`
- Check MAC address is correct in config

**Keys get stuck after rotation**
- This was fixed - make sure you have latest `config_loader.py`
- Rotary controls should have stop events: `(0x44, 0xc4)`

**GUI won't launch / "No module named 'PySide6'"**
```bash
# Install GUI dependencies
./venv/bin/pip install -r tuxbox/gui/requirements.txt
```

**GUI crashes on startup**
- Check terminal output for Qt errors
- Verify PySide6 is compatible with your Python version
- Try: `./venv/bin/python -m PySide6.QtCore` to test Qt installation

**"tuxbox-gui: command not found"**
```bash
# Check if launcher exists
ls -la /usr/local/bin/tuxbox-gui

# If not, reinstall or create manually:
# See install.sh for launcher script creation
```

**GUI shows empty profile list**
- Check profiles directory exists: `ls ~/.config/tuxbox/profiles/`
- Check config file permissions: `ls -la ~/.config/tuxbox/`
- Try loading profiles manually:
  ```python
  from tuxbox.config_loader import load_profiles
  profiles = load_profiles()
  print(profiles)
  ```

**Changes not saving in GUI**
- Check terminal output for save errors
- Verify config directory is writable: `ls -la ~/.config/tuxbox/`
- Check profile backups exist: `ls ~/.config/tuxbox/profiles/*.backup.*`
- Look for errors in profile files in `~/.config/tuxbox/profiles/`

## Additional Resources

### Core Driver Resources
- [Bleak Documentation](https://bleak.readthedocs.io/) - Python BLE library
- [evdev Documentation](https://python-evdev.readthedocs.io/) - Linux input events
- [D-Bus Tutorial](https://dbus.freedesktop.org/doc/dbus-tutorial.html) - For window detection
- [systemd Service Guide](https://www.freedesktop.org/software/systemd/man/systemd.service.html)

### GUI Development Resources
- [PySide6 Documentation](https://doc.qt.io/qtforpython-6/) - Qt 6 Python bindings
- [Qt Documentation](https://doc.qt.io/qt-6/) - Qt framework reference
- [qasync Documentation](https://github.com/CabbageDevelopment/qasync) - Asyncio integration for Qt
- [Qt Signals & Slots](https://doc.qt.io/qt-6/signalsandslots.html) - Signal/slot mechanism

## License

MIT License - See [LICENSE.txt](../LICENSE.txt) file for details.
