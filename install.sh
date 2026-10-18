#!/bin/bash
# TuxBox Driver Installation Script
# This script installs the TuxBox driver for TourBox input devices as a user service

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}TuxBox Driver Installation${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo -e "${RED}Error: This driver only works on Linux${NC}"
    exit 1
fi

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python 3 is not installed${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo -e "${GREEN}✓${NC} Found Python $PYTHON_VERSION"

# Detect distribution and package manager
echo ""
echo "Detecting system..."

if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO_ID="$ID"
    DISTRO_NAME="$NAME"
else
    DISTRO_ID="unknown"
    DISTRO_NAME="Linux"
fi

# Determine package manager and package names
# Check for immutable (rpm-ostree) distros first (Bazzite, Silverblue, Kinoite, etc.)
if [ -f /run/ostree-booted ] && command -v rpm-ostree &> /dev/null; then
    PKG_MANAGER="rpm-ostree"
    PKG_INSTALL="rpm-ostree install"
    PKG_BLUEZ="bluez"
    PKG_GCC="gcc"
    PKG_PYTHON_DEV="python3-devel"
    PKG_KERNEL_HEADERS="kernel-headers"
    IMMUTABLE_DISTRO=true
elif command -v apt &> /dev/null; then
    PKG_MANAGER="apt"
    PKG_INSTALL="sudo apt install"
    PKG_BLUEZ="bluez"
    PKG_GCC="gcc"
    PKG_PYTHON_DEV="python3-dev"
    PKG_KERNEL_HEADERS="linux-headers-generic"
elif command -v dnf &> /dev/null; then
    PKG_MANAGER="dnf"
    PKG_INSTALL="sudo dnf install"
    PKG_BLUEZ="bluez"
    PKG_GCC="gcc"
    PKG_PYTHON_DEV="python3-devel"
    PKG_KERNEL_HEADERS="kernel-headers"
elif command -v pacman &> /dev/null; then
    PKG_MANAGER="pacman"
    PKG_INSTALL="sudo pacman -S"
    PKG_BLUEZ="bluez"
    PKG_GCC="gcc"
    PKG_PYTHON_DEV="python"
    PKG_KERNEL_HEADERS="linux-headers"
else
    PKG_MANAGER="unknown"
    PKG_INSTALL="# Use your package manager to install:"
fi

echo -e "${GREEN}✓${NC} Detected: $DISTRO_NAME ($PKG_MANAGER)"

# Check for required system packages
echo ""
echo "Checking system dependencies..."

MISSING_DEPS=()
MISSING_PKG_NAMES=()

# Check for bluetooth
if ! command -v bluetoothctl &> /dev/null && ! command -v bluetui &> /dev/null; then
    MISSING_DEPS+=("bluetoothctl")
    MISSING_PKG_NAMES+=("$PKG_BLUEZ")
fi

# Check for venv module by checking for ensurepip (which is what actually fails)
if ! python3 -c "import ensurepip" &> /dev/null; then
    # Extract major.minor version (e.g., 3.13 from 3.13.5)
    PYTHON_MM_VERSION=$(echo "$PYTHON_VERSION" | cut -d. -f1,2)
    MISSING_DEPS+=("venv")
    if [ "$PKG_MANAGER" = "apt" ]; then
        MISSING_PKG_NAMES+=("python${PYTHON_MM_VERSION}-venv")
    elif [ "$PKG_MANAGER" = "dnf" ]; then
        MISSING_PKG_NAMES+=("python${PYTHON_MM_VERSION}-venv")
    else
        MISSING_PKG_NAMES+=("python-venv")
    fi
fi

# Check for gcc (needed to compile Python packages like evdev)
if ! command -v gcc &> /dev/null; then
    MISSING_DEPS+=("gcc")
    MISSING_PKG_NAMES+=("$PKG_GCC")
fi

# Check for Python development headers (needed to compile Python packages)
# Check for the actual Python.h file, not just the include directory
PYTHON_INCLUDE=$(python3 -c "import sysconfig; print(sysconfig.get_path('include'))" 2>/dev/null)
if [ -z "$PYTHON_INCLUDE" ] || [ ! -f "$PYTHON_INCLUDE/Python.h" ]; then
    MISSING_DEPS+=("python-dev")
    MISSING_PKG_NAMES+=("$PKG_PYTHON_DEV")
fi

# Check for kernel headers (needed for evdev compilation)
if ! [ -d "/usr/include/linux" ]; then
    MISSING_DEPS+=("kernel-headers")
    MISSING_PKG_NAMES+=("$PKG_KERNEL_HEADERS")
fi

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo -e "${RED}Missing dependencies: ${MISSING_DEPS[*]}${NC}"
    echo ""
    echo "These packages are required to compile and run the TuxBox driver."
    echo ""
    echo "Install them with:"
    echo "  $PKG_INSTALL ${MISSING_PKG_NAMES[*]}"
    if [ "$IMMUTABLE_DISTRO" = "true" ]; then
        echo ""
        echo -e "${YELLOW}Note: You are on an immutable distro ($DISTRO_NAME).${NC}"
        echo "After installing, you must reboot for the changes to take effect."
    fi
    echo ""
    echo "Then run this installer again:"
    echo "  ./install.sh"
    exit 1
fi

echo -e "${GREEN}✓${NC} All system dependencies found"

# Check if user is in input group
echo ""
echo "Checking permissions..."

if ! groups | grep -q '\binput\b'; then
    echo -e "${YELLOW}!${NC} User '$USER' is not in the 'input' group"
    echo ""
    echo "The driver needs access to /dev/uinput to create virtual input devices."
    echo ""
    echo "Adding user to input group (requires sudo):"
    sudo usermod -a -G input $USER

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} User added to input group"
        NEED_RELOGIN=true
    else
        echo -e "${RED}Error: Failed to add user to input group${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} User is in input group"
fi

# Check if user is in a serial ports group (for USB access)
SERIAL_PORTS_GROUP=""

if getent group dialout >/dev/null; then
    SERIAL_PORTS_GROUP="dialout"
elif getent group uucp >/dev/null; then
    SERIAL_PORTS_GROUP="uucp"
else
    echo -e "${RED}Error: No serial port group found - attempted: dialout, uucp${NC}"
    exit 1
fi

if ! groups | grep -q "\b$SERIAL_PORTS_GROUP\b"; then
    echo -e "${YELLOW}!${NC} User '$USER' is not in the '$SERIAL_PORTS_GROUP' group"
    echo ""
    echo "The driver needs $SERIAL_PORTS_GROUP group for USB serial port access."
    echo ""
    echo "Adding user to $SERIAL_PORTS_GROUP group (requires sudo):"
    sudo usermod -a -G $SERIAL_PORTS_GROUP $USER

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} User added to $SERIAL_PORTS_GROUP group"
        NEED_RELOGIN=true
    else
        echo -e "${RED}Error: Failed to add user to $SERIAL_PORTS_GROUP group${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} User is in $SERIAL_PORTS_GROUP group"
fi

# Set up udev rule for /dev/uinput permissions
echo ""
echo "Configuring /dev/uinput permissions..."

UDEV_RULE="/etc/udev/rules.d/99-uinput.rules"
MODULE_CONF="/etc/modules-load.d/uinput.conf"

if [ ! -f "$UDEV_RULE" ]; then
    echo 'KERNEL=="uinput", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"' | sudo tee "$UDEV_RULE" > /dev/null

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} Created udev rule for uinput device"

        # Reload udev rules
        sudo udevadm control --reload-rules

        # Ensure uinput module is loaded
        if ! lsmod | grep -q uinput; then
            sudo modprobe uinput
            echo -e "${GREEN}✓${NC} Loaded uinput kernel module"
        fi

        # Ensure uinput module loads on boot
        if [ ! -f "$MODULE_CONF" ]; then
            echo "uinput" | sudo tee "$MODULE_CONF" > /dev/null
            echo -e "${GREEN}✓${NC} Configured uinput to load on boot"
        fi
    else
        echo -e "${RED}Error: Failed to create udev rule${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} udev rule already exists"
fi

# Stop ModemManager probing the TourBox serial port
#
# The TourBox enumerates as a CDC-ACM device (/dev/ttyACM*). ModemManager,
# pulled in by NetworkManager on most distros, probes any new CDC-ACM device
# with AT commands. That fights the driver for the port and shows up as
# "device reports readiness to read but returned no data (device disconnected
# or multiple access on port?)" with the device disconnecting in a loop.
echo ""
echo "Configuring ModemManager to ignore the TourBox..."

TOURBOX_UDEV_RULE="/etc/udev/rules.d/99-tourbox.rules"

# Rewrite the rule when it's missing or predates the newest ID below, so
# existing installs pick up added IDs too.
if [ ! -f "$TOURBOX_UDEV_RULE" ] || ! grep -q 'idVendor}=="cafe", ATTRS{idProduct}=="4001"' "$TOURBOX_UDEV_RULE"; then
    # c251:2005 = Elite / Elite Plus. 2e3c:5740 and cafe:4001 = Neo (generic
    # ArteryTek AT32 and TinyUSB CDC IDs, so this also tells ModemManager to
    # skip other boards on them — harmless, as those are not modems either).
    sudo tee "$TOURBOX_UDEV_RULE" > /dev/null <<'UDEV_EOF'
# TourBox controllers - keep ModemManager off the serial port
SUBSYSTEM=="tty", ATTRS{idVendor}=="c251", ATTRS{idProduct}=="2005", ENV{ID_MM_DEVICE_IGNORE}="1"
SUBSYSTEM=="tty", ATTRS{idVendor}=="2e3c", ATTRS{idProduct}=="5740", ENV{ID_MM_DEVICE_IGNORE}="1"
SUBSYSTEM=="tty", ATTRS{idVendor}=="cafe", ATTRS{idProduct}=="4001", ENV{ID_MM_DEVICE_IGNORE}="1"
UDEV_EOF

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} Wrote udev rule to keep ModemManager off the TourBox"
        sudo udevadm control --reload-rules
        echo -e "${YELLOW}!${NC} Replug the USB cable for this to take effect"
    else
        echo -e "${RED}Error: Failed to write TourBox udev rule${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓${NC} TourBox udev rule already up to date"
fi

# Create and activate virtual environment
echo ""
echo "Setting up Python virtual environment..."

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓${NC} Created virtual environment"
else
    echo -e "${YELLOW}!${NC} Virtual environment already exists"
fi

# ==========================================
# Migration from tourbox-linux to tuxbox
# ==========================================
echo ""
echo "Checking for previous tourbox-linux installation..."

MIGRATED_SOMETHING=false

# Stop and disable old tourbox.service if present
OLD_SERVICE_FILE="$HOME/.config/systemd/user/tourbox.service"
if [ -f "$OLD_SERVICE_FILE" ]; then
    if command -v systemctl &> /dev/null && systemctl --user status &> /dev/null; then
        systemctl --user stop tourbox 2>/dev/null || true
        systemctl --user disable tourbox 2>/dev/null || true
        systemctl --user daemon-reload
    fi
    rm -f "$OLD_SERVICE_FILE"
    echo -e "${GREEN}✓${NC} Removed old tourbox.service"
    MIGRATED_SOMETHING=true
fi

# Remove old launcher
if [ -f "/usr/local/bin/tourbox-gui" ]; then
    if sudo rm -f "/usr/local/bin/tourbox-gui" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Removed old launcher: /usr/local/bin/tourbox-gui"
        MIGRATED_SOMETHING=true
    else
        echo -e "${YELLOW}!${NC} Could not remove old launcher (read-only filesystem)"
    fi
fi

# Remove old desktop file
if [ -f "/usr/share/applications/tourbox-gui.desktop" ]; then
    if sudo rm -f "/usr/share/applications/tourbox-gui.desktop" 2>/dev/null; then
        sudo update-desktop-database /usr/share/applications/ 2>/dev/null || true
        echo -e "${GREEN}✓${NC} Removed old desktop entry: /usr/share/applications/tourbox-gui.desktop"
        MIGRATED_SOMETHING=true
    else
        echo -e "${YELLOW}!${NC} Could not remove old desktop entry (read-only filesystem)"
    fi
fi

# Remove old icon
if [ -f "/usr/share/pixmaps/tourbox-icon.png" ]; then
    if sudo rm -f "/usr/share/pixmaps/tourbox-icon.png" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} Removed old icon: /usr/share/pixmaps/tourbox-icon.png"
        MIGRATED_SOMETHING=true
    else
        echo -e "${YELLOW}!${NC} Could not remove old icon (read-only filesystem)"
    fi
fi

# Remove old PID file
OLD_PID_FILE="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/tourbox.pid"
if [ -f "$OLD_PID_FILE" ]; then
    rm -f "$OLD_PID_FILE"
    echo -e "${GREEN}✓${NC} Removed old PID file: $OLD_PID_FILE"
    MIGRATED_SOMETHING=true
fi

# Migrate config directory
OLD_CONFIG_DIR="$HOME/.config/tourbox"
NEW_CONFIG_DIR="$HOME/.config/tuxbox"
if [ -d "$OLD_CONFIG_DIR" ] && [ ! -d "$NEW_CONFIG_DIR" ]; then
    cp -a "$OLD_CONFIG_DIR" "$NEW_CONFIG_DIR"
    mv "$OLD_CONFIG_DIR" "$HOME/.config/tourbox.pre-v3-backup"
    echo -e "${GREEN}✓${NC} Migrated config from ~/.config/tourbox/ to ~/.config/tuxbox/"
    echo -e "${GREEN}✓${NC} Old config backed up to ~/.config/tourbox.pre-v3-backup/"
    MIGRATED_SOMETHING=true
fi

# Update git remote URL if it still references tourbox-linux
ORIGIN_URL=$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || true)
if [[ "$ORIGIN_URL" == *"tourbox-linux"* ]]; then
    NEW_URL="${ORIGIN_URL//tourbox-linux/tuxbox}"
    git -C "$SCRIPT_DIR" remote set-url origin "$NEW_URL"
    echo -e "${GREEN}✓${NC} Updated git origin URL to: $NEW_URL"
    MIGRATED_SOMETHING=true
fi

if [ "$MIGRATED_SOMETHING" = "true" ]; then
    echo -e "${GREEN}✓${NC} Migration from tourbox-linux complete"
else
    echo -e "${GREEN}✓${NC} No old installation found - clean install"
fi

# Check for leftover files from old tuxbox system installation
echo ""
echo "Checking for leftover system files from previous installation..."

OLD_SYSTEM_FILES_FOUND=false

if [ -f "/usr/local/bin/tuxbox-gui" ]; then
    echo -e "${YELLOW}!${NC} Found old system launcher: /usr/local/bin/tuxbox-gui"
    OLD_SYSTEM_FILES_FOUND=true
fi

if [ -f "/usr/share/applications/tuxbox-gui.desktop" ]; then
    echo -e "${YELLOW}!${NC} Found old desktop entry: /usr/share/applications/tuxbox-gui.desktop"
    OLD_SYSTEM_FILES_FOUND=true
fi

if [ -f "/usr/share/pixmaps/tuxbox-icon.png" ]; then
    echo -e "${YELLOW}!${NC} Found old icon: /usr/share/pixmaps/tuxbox-icon.png"
    OLD_SYSTEM_FILES_FOUND=true
fi

if [ "$OLD_SYSTEM_FILES_FOUND" = "true" ]; then
    echo ""
    echo "Your system has leftover files from a previous tuxbox installation."
    echo ""
    echo "These old files will be ignored. The new installation uses:"
    echo "  Launcher:  ~/.local/bin/tuxbox-gui"
    echo "  Icon:      ~/.local/share/icons/hicolor/256x256/apps/tuxbox-icon.png"
    echo "  Desktop:   ~/.local/share/applications/tuxbox-gui.desktop"
    echo ""
    echo "To clean them up manually, run:"
    echo "  sudo rm -f /usr/local/bin/tuxbox-gui"
    echo "  sudo rm -f /usr/share/applications/tuxbox-gui.desktop"
    echo "  sudo rm -f /usr/share/pixmaps/tuxbox-icon.png"
    echo ""
fi

# Install package and dependencies
echo ""
echo "Installing TuxBox driver..."
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -e .

echo -e "${GREEN}✓${NC} Driver installed successfully"

# Install GUI dependencies
echo ""
echo "Installing GUI dependencies..."
./venv/bin/pip install -q -r tuxbox/gui/requirements.txt

echo -e "${GREEN}✓${NC} GUI dependencies installed successfully"

# Create GUI launcher script
echo ""
echo "Creating GUI launcher..."

LAUNCHER_FILE="$HOME/.local/bin/tuxbox-gui"
mkdir -p "$HOME/.local/bin"

cat > "$LAUNCHER_FILE" <<EOF
#!/bin/bash
# TuxBox Configuration GUI Launcher
# Auto-generated by install.sh

exec "$SCRIPT_DIR/venv/bin/python" -m tuxbox.gui "\$@"
EOF

chmod +x "$LAUNCHER_FILE"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Created launcher: $LAUNCHER_FILE"
else
    echo -e "${RED}Error: Failed to create launcher${NC}"
    exit 1
fi

# Warn if the launcher's directory is not on PATH
LAUNCHER_DIR="$(cd "$(dirname "$LAUNCHER_FILE")" && pwd -P)"
PATH_HAS_LAUNCHER_DIR=false
IFS=':' read -ra _PATH_DIRS <<< "$PATH"
for _dir in "${_PATH_DIRS[@]}"; do
    _dir_normalized="$(cd "$_dir" 2>/dev/null && pwd -P)"
    if [ "$_dir_normalized" = "$LAUNCHER_DIR" ]; then
        PATH_HAS_LAUNCHER_DIR=true
        break
    fi
done

if [ "$PATH_HAS_LAUNCHER_DIR" = "true" ]; then
    echo -e "${GREEN}✓${NC} Launcher directory is in PATH - 'tuxbox-gui' will work from a terminal"
else
    echo ""
    echo -e "${YELLOW}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  NOTE: ~/.local/bin is not in your PATH                        ║${NC}"
    echo -e "${YELLOW}║                                                                ║${NC}"
    echo -e "${YELLOW}║  The 'TuxBox Configuration' entry in your app menu will still  ║${NC}"
    echo -e "${YELLOW}║  launch the GUI, but 'tuxbox-gui' will not be available from   ║${NC}"
    echo -e "${YELLOW}║  the command line until you add it to PATH.                    ║${NC}"
    echo -e "${YELLOW}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "Add the following line to your shell startup file:"
    echo "  bash:  ~/.bashrc"
    echo "  zsh:   ~/.zshrc"
    echo "  fish:  ~/.config/fish/config.fish"
    echo ""
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
    echo "Then restart your shell or run: source ~/.bashrc  (or the equivalent for your shell)"
    echo ""
fi

# Install application icon
echo ""
echo "Installing application icon..."
ICON_SOURCE="$SCRIPT_DIR/tuxbox/gui/assets/tuxbox-icon.png"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
ICON_DEST="$ICON_DIR/tuxbox-icon.png"

if [ -f "$ICON_SOURCE" ]; then
    mkdir -p "$ICON_DIR"
    cp "$ICON_SOURCE" "$ICON_DEST"
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} Installed icon: $ICON_DEST"
        # Update icon cache
        if command -v gtk-update-icon-cache &> /dev/null; then
            gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
        fi
    else
        echo -e "${YELLOW}!${NC} Warning: Failed to install icon"
    fi
else
    echo -e "${YELLOW}!${NC} Warning: Icon file not found: $ICON_SOURCE"
fi

# Install desktop entry
echo "Installing desktop entry..."
DESKTOP_SOURCE="$SCRIPT_DIR/tuxbox-gui.desktop"
DESKTOP_DEST="$HOME/.local/share/applications/tuxbox-gui.desktop"

if [ -f "$DESKTOP_SOURCE" ]; then
    mkdir -p "$HOME/.local/share/applications"
    # Create desktop file with updated icon and exec paths
    sed -e "s|^Icon=.*|Icon=tuxbox-icon|" \
        -e "s|^Exec=.*|Exec=$HOME/.local/bin/tuxbox-gui|" \
        "$DESKTOP_SOURCE" > "$DESKTOP_DEST"
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} Installed desktop entry: $DESKTOP_DEST"
        echo -e "${GREEN}✓${NC} Application added to system menu"
    else
        echo -e "${YELLOW}!${NC} Warning: Failed to install desktop entry"
    fi
else
    echo -e "${YELLOW}!${NC} Warning: Desktop file not found: $DESKTOP_SOURCE"
fi

# Install config file
echo ""
echo "=========================================="
echo "Configuration Setup"
echo "=========================================="
echo ""

CONFIG_DIR="$HOME/.config/tuxbox"
PROFILES_DIR="$CONFIG_DIR/profiles"
CONFIG_FILE="$CONFIG_DIR/config.conf"
LEGACY_CONFIG_FILE="$CONFIG_DIR/mappings.conf"
DEFAULT_CONFIG="tuxbox/default_mappings.conf"

# Create config directory
mkdir -p "$CONFIG_DIR"

# Check which config format exists
if [ -d "$PROFILES_DIR" ] && [ "$(ls -A "$PROFILES_DIR"/*.profile 2>/dev/null)" ]; then
    # New format: profiles directory exists with .profile files
    echo -e "${GREEN}✓${NC} Found existing profiles in: $PROFILES_DIR"
    echo -e "${GREEN}✓${NC} Keeping existing configuration"

    # Ensure required profiles exist
    if [ ! -f "$PROFILES_DIR/default.profile" ]; then
        echo -e "${YELLOW}!${NC} Default profile missing - recreating..."
        ./venv/bin/python -c "from tuxbox.profile_io import ensure_default_profile; success, msg = ensure_default_profile(); print(msg); exit(0 if success else 1)"
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓${NC} Default profile restored"
        else
            echo -e "${YELLOW}!${NC} Warning: Could not restore default profile"
        fi
    fi

    if [ ! -f "$PROFILES_DIR/tuxbox_gui.profile" ]; then
        echo -e "${YELLOW}!${NC} TuxBox GUI profile missing - recreating..."
        ./venv/bin/python -c "from tuxbox.profile_io import ensure_tuxbox_gui_profile; success, msg = ensure_tuxbox_gui_profile(); print(msg); exit(0 if success else 1)"
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓${NC} TuxBox GUI profile restored"
        else
            echo -e "${YELLOW}!${NC} Warning: Could not restore TuxBox GUI profile"
        fi
    fi
elif [ -f "$LEGACY_CONFIG_FILE" ]; then
    # Legacy format: mappings.conf exists (will be migrated by GUI)
    echo -e "${YELLOW}!${NC} Legacy config file found: $LEGACY_CONFIG_FILE"
    echo -e "${GREEN}✓${NC} Keeping existing config (will be migrated when you run the GUI)"
else
    # Fresh install: create new format directly
    echo "The driver supports both USB and Bluetooth connections."
    echo ""
    echo "  USB:       Just plug in the cable - auto-detected"
    echo "  Bluetooth: Auto-detected - just turn on your TourBox"
    echo ""

    # Create initial configuration using Python
    ./venv/bin/python -c "from tuxbox.profile_io import create_initial_config; success, msg = create_initial_config(); print(msg); exit(0 if success else 1)"
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} Configuration created"
    else
        echo -e "${RED}✗${NC} Failed to create configuration"
    fi
fi

# Check if systemd is available
HAS_SYSTEMD=false
if command -v systemctl &> /dev/null && systemctl --user status &> /dev/null; then
    HAS_SYSTEMD=true
fi

if [ "$HAS_SYSTEMD" = "true" ]; then
    # Install systemd service
    echo ""
    echo "=========================================="
    echo "Systemd Service Setup"
    echo "=========================================="
    echo ""

    SYSTEMD_DIR="$HOME/.config/systemd/user"
    SERVICE_FILE="$SYSTEMD_DIR/tuxbox.service"

    mkdir -p "$SYSTEMD_DIR"

    # Stop service if it's currently running
    if systemctl --user is-active --quiet tuxbox; then
        echo -e "${YELLOW}!${NC} Stopping running service..."
        systemctl --user stop tuxbox
        echo -e "${GREEN}✓${NC} Service stopped"
    fi

    # Create service file
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=TuxBox Driver for TourBox Devices
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=$SCRIPT_DIR/venv/bin/python -m tuxbox
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
EOF

    echo -e "${GREEN}✓${NC} Installed systemd service"

    # Reload systemd
    systemctl --user daemon-reload
    echo -e "${GREEN}✓${NC} Reloaded systemd daemon"

    # Ask about enabling service
    echo ""
    read -p "Enable TuxBox service to start on login? (Y/n): " -n 1 -r
    echo ""

    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        systemctl --user enable tuxbox
        echo -e "${GREEN}✓${NC} Service enabled (will start on login)"
        SERVICE_ENABLED=true
    else
        echo -e "${YELLOW}!${NC} Service not enabled (won't start automatically)"
        SERVICE_ENABLED=false
    fi

    # Ask about starting service now (only if no relogin required)
    if [ "$NEED_RELOGIN" != "true" ]; then
        echo ""
        read -p "Start TuxBox service now? (Y/n): " -n 1 -r
        echo ""

        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            systemctl --user restart tuxbox
            sleep 2

            if systemctl --user is-active --quiet tuxbox; then
                echo -e "${GREEN}✓${NC} Service is running"
            else
                echo -e "${RED}✗${NC} Service failed to start"
                echo ""
                echo "Check logs with: journalctl --user -u tuxbox -n 50"
                exit 1
            fi
        else
            echo -e "${YELLOW}!${NC} Service not started"
        fi
    fi
else
    # Non-systemd system (OpenRC, runit, etc.)
    echo ""
    echo "=========================================="
    echo "Service Setup (Non-Systemd)"
    echo "=========================================="
    echo ""
    echo -e "${YELLOW}!${NC} systemd not detected - skipping automatic service setup"
    echo ""
    echo "You will need to create an init script for your init system."
    echo ""
    echo "The driver can be started manually with:"
    echo "  $SCRIPT_DIR/venv/bin/python -m tuxbox"
    echo ""
    echo "For the GUI to restart the driver, configure a restart command in"
    echo "~/.config/tuxbox/config.conf:"
    echo ""
    echo "  [service]"
    echo "  restart_command = your-restart-command-here"
    echo ""
    echo "Examples:"
    echo "  OpenRC:  rc-service tuxbox restart"
    echo "  runit:   sv restart tuxbox"
    echo "  s6:      s6-svc -r /run/service/tuxbox"
    echo ""
fi

# Final summary
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ Installation Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Installed to: $SCRIPT_DIR"
echo "Config file:  $CONFIG_FILE"

if [ "$HAS_SYSTEMD" = "true" ]; then
    echo "Service file: $SERVICE_FILE"
    echo ""
    echo "Useful commands:"
    echo "  Start:   systemctl --user start tuxbox"
    echo "  Stop:    systemctl --user stop tuxbox"
    echo "  Status:  systemctl --user status tuxbox"
    echo "  Logs:    journalctl --user -u tuxbox -f"
    echo "  Restart: systemctl --user restart tuxbox"
else
    echo ""
    echo "Driver command: $SCRIPT_DIR/venv/bin/python -m tuxbox"
fi
echo ""
echo "To customize button mappings:"
echo "  Option 1 - Use the GUI (recommended):"
echo "    - Run from terminal: tuxbox-gui"
echo "    - Or find 'TuxBox Configuration' in your app menu"
echo "    - Launcher installed at: $HOME/.local/bin/tuxbox-gui"
echo ""
echo "  Option 2 - Edit config file manually:"
echo "    nano $CONFIG_FILE"
if [ "$HAS_SYSTEMD" = "true" ]; then
    echo "    systemctl --user restart tuxbox  # Apply changes"
else
    echo "    # Then restart your driver service to apply changes"
fi
echo ""

if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
    echo -e "${GREEN}✓${NC} Wayland detected - Profile mode is available!"
    echo "  Edit your config to enable app-specific profiles"
    echo ""

    # Check for kdotool on KDE Plasma
    if [ "$XDG_CURRENT_DESKTOP" = "KDE" ] || [ "$DESKTOP_SESSION" = "plasma" ]; then
        echo "  Detected compositor: KDE Plasma"
        if ! command -v kdotool &> /dev/null; then
            echo ""
            echo -e "${YELLOW}╔════════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${YELLOW}║  ATTENTION KDE PLASMA USERS:                                   ║${NC}"
            echo -e "${YELLOW}║  kdotool is NOT installed - Profile mode will NOT work!        ║${NC}"
            echo -e "${YELLOW}╚════════════════════════════════════════════════════════════════╝${NC}"
            echo ""
            echo -e "${BLUE}To enable profile mode (app-specific button mappings), install kdotool:${NC}"
            echo ""
            echo -e "${GREEN}1. Install build dependencies:${NC}"
            echo "   sudo apt install build-essential pkg-config libdbus-1-dev libxcb1-dev"
            echo ""
            echo -e "${GREEN}2. Install Rust (if not already installed):${NC}"
            echo "   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
            echo "   (Choose option 1 for standard installation when prompted)"
            echo "   source \$HOME/.cargo/env"
            echo ""
            echo -e "${GREEN}3. Install kdotool:${NC}"
            echo "   cargo install kdotool"
            echo ""
            echo -e "${GREEN}4. Verify installation:${NC}"
            echo "   kdotool --version"
            echo ""
            echo -e "${YELLOW}Note: Simple mode (single mapping) works without kdotool.${NC}"
            echo ""
        else
            KDOTOOL_VERSION=$(kdotool --version 2>&1 | head -1)
            echo -e "  ${GREEN}✓${NC} kdotool found: $KDOTOOL_VERSION"
        fi
    elif [ "$XDG_CURRENT_DESKTOP" = "GNOME" ] || [[ "$XDG_CURRENT_DESKTOP" == *"GNOME"* ]]; then
        # GNOME requires an extension for window detection
        echo "  Detected compositor: GNOME"

        # Check if Focused Window D-Bus extension is installed
        if gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/shell/extensions/FocusedWindow --method org.gnome.shell.extensions.FocusedWindow.Get &>/dev/null; then
            echo -e "  ${GREEN}✓${NC} Focused Window D-Bus extension is installed"
        else
            echo ""
            echo -e "${YELLOW}╔════════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${YELLOW}║  ATTENTION GNOME USERS:                                        ║${NC}"
            echo -e "${YELLOW}║  Profile mode requires a GNOME Shell extension!                ║${NC}"
            echo -e "${YELLOW}╚════════════════════════════════════════════════════════════════╝${NC}"
            echo ""
            echo -e "${BLUE}To enable profile mode (app-specific button mappings):${NC}"
            echo ""
            echo "1. Visit: https://extensions.gnome.org/extension/5592/focused-window-d-bus/"
            echo "2. Click the install button to install the extension"
            echo "3. Verify installation with:"
            echo "   gnome-extensions list | grep focused-window-dbus"
            echo "   (Should show: focused-window-dbus@flexagoon.com)"
            echo ""
            echo -e "${YELLOW}Note: Without this extension, use Simple Mode (single mapping for all apps)${NC}"
            echo ""
        fi
    else
        # Other Wayland compositors (Sway, Hyprland, etc.)
        echo "  Detected compositor: ${XDG_CURRENT_DESKTOP:-Unknown}"
        echo -e "  ${GREEN}✓${NC} Window detection works natively"
    fi
elif [ "$XDG_SESSION_TYPE" = "x11" ]; then
    echo -e "${GREEN}✓${NC} X11 detected - Profile mode is available with xdotool!"
    echo ""

    if ! command -v xdotool &> /dev/null; then
        echo -e "${YELLOW}╔════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${YELLOW}║  ATTENTION X11 USERS:                                          ║${NC}"
        echo -e "${YELLOW}║  xdotool is NOT installed - Profile mode will NOT work!        ║${NC}"
        echo -e "${YELLOW}╚════════════════════════════════════════════════════════════════╝${NC}"
        echo ""
        echo -e "${BLUE}To enable profile mode (app-specific button mappings), install xdotool:${NC}"
        echo ""
        echo -e "${GREEN}Debian/Ubuntu/Mint:${NC}"
        echo "   sudo apt install xdotool"
        echo ""
        echo -e "${GREEN}Fedora/RHEL:${NC}"
        echo "   sudo dnf install xdotool"
        echo ""
        echo -e "${GREEN}Arch:${NC}"
        echo "   sudo pacman -S xdotool"
        echo ""
        echo -e "${YELLOW}Note: Simple mode (single mapping) works without xdotool.${NC}"
        echo ""
    else
        XDOTOOL_VERSION=$(xdotool --version 2>&1 | head -1)
        echo -e "  ${GREEN}✓${NC} xdotool found: $XDOTOOL_VERSION"
    fi
fi

if [ "$NEED_RELOGIN" = "true" ]; then
    echo ""
    echo -e "${YELLOW}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${YELLOW}║  IMPORTANT: You must LOG OUT and LOG BACK IN (or reboot)       ║${NC}"
    echo -e "${YELLOW}║  before the TuxBox driver will work!                           ║${NC}"
    echo -e "${YELLOW}║                                                                ║${NC}"
    echo -e "${YELLOW}║  This is required for the input group membership to activate.  ║${NC}"
    if [ "$HAS_SYSTEMD" = "true" ]; then
        if [ "$SERVICE_ENABLED" = "true" ]; then
            echo -e "${YELLOW}║                                                                ║${NC}"
            echo -e "${YELLOW}║  The service will start automatically when you log back in.    ║${NC}"
        else
            echo -e "${YELLOW}║                                                                ║${NC}"
            echo -e "${YELLOW}║  After logging back in, start the service with:                ║${NC}"
            echo -e "${YELLOW}║    systemctl --user start tuxbox                               ║${NC}"
        fi
    else
        echo -e "${YELLOW}║                                                                ║${NC}"
        echo -e "${YELLOW}║  After logging back in, start the driver using your init       ║${NC}"
        echo -e "${YELLOW}║  system or run it manually.                                     ║${NC}"
    fi
    echo -e "${YELLOW}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
fi

echo "Enjoy your TourBox!"
echo ""
