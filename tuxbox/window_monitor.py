#!/usr/bin/env python3
"""Window monitoring for Wayland compositors and X11

Detects active window information to enable application-specific profiles.
Supports: Sway, Hyprland, GNOME Shell (Mutter), KDE Plasma (KWin), Niri, X11 (via xdotool)
"""

import asyncio
import logging
import signal
import subprocess
import json
import os
import re
import shutil
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Polling interval for active-window detection, in seconds.
#
# Every poll spawns a helper process (kdotool/xdotool/swaymsg/...). On KDE each
# kdotool call also loads, runs and unloads a KWin script over D-Bus, so a short
# interval turns into sustained session-bus traffic that can crowd out other
# D-Bus clients.
#
# The interval is also the worst-case delay before a profile switch takes
# effect, and that delay is perceptible in real use - the instant after
# switching apps is exactly when the device gets reached for. So the default
# stays responsive and the traffic saving comes from chaining the getters into
# one call instead of two; users who need a quieter bus can raise this.
#
# On KDE this polling loop is only a fallback: see _start_kde_event_monitor(),
# which gets focus changes pushed from KWin with no polling at all.
DEFAULT_POLL_INTERVAL = 0.2

# Guard rails for the user-configurable interval
MIN_POLL_INTERVAL = 0.2
MAX_POLL_INTERVAL = 60.0

# xprop prints one property per line, e.g. WM_CLASS(STRING) = "Navigator", "firefox"
XPROP_LINE = re.compile(r'^(\w+)\(\w+\) = (.*)$')
XPROP_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')

# --- KDE event-driven monitoring -------------------------------------------
# Instead of polling kdotool, a small script is loaded into KWin once. It calls
# back over D-Bus whenever the active window or its title changes, so there is
# no polling at all and switches take effect immediately.
KDE_DBUS_NAME = "org.tuxbox.WindowMonitor"
KDE_DBUS_INTERFACE = "org.tuxbox.WindowMonitor"
KDE_SCRIPT_NAME = "tuxbox-window-monitor"

# Seconds to wait for the script's initial "loaded" callback before giving up
# and falling back to polling.
KDE_EVENT_HANDSHAKE_TIMEOUT = 3.0

# KWin script. Feature-detects Plasma 6 (windowActivated/activeWindow) vs
# Plasma 5 (clientActivated/activeClient), and tracks caption changes on the
# focused window so title-based profiles still work without a refocus.
KDE_KWIN_SCRIPT = """
function report(window) {
    if (!window) { return; }
    callDBus("%(name)s", "/", "%(iface)s", "windowChanged",
             (window.resourceClass || "").toString(),
             (window.caption || "").toString());
}

var trackedWindow = null;
var trackedHandler = null;

function track(window) {
    // Drop the caption hook on the previously focused window
    if (trackedWindow && trackedHandler && trackedWindow.captionChanged) {
        try { trackedWindow.captionChanged.disconnect(trackedHandler); } catch (e) {}
    }
    trackedWindow = window;
    trackedHandler = null;

    if (!window) { return; }
    if (window.captionChanged) {
        trackedHandler = function() { report(window); };
        window.captionChanged.connect(trackedHandler);
    }
}

function onActivated(window) {
    track(window);
    report(window);
}

var connected = false;
if (workspace.windowActivated) {
    workspace.windowActivated.connect(onActivated);          // Plasma 6
    connected = true;
} else if (workspace.clientActivated) {
    workspace.clientActivated.connect(onActivated);          // Plasma 5
    connected = true;
}

// Handshake. Sent unconditionally and before any window report, so it works
// even when nothing is focused yet (the driver starts with the session). The
// flag tells the driver whether an activation signal was actually connected -
// without it, a KWin whose API we don't recognise would look healthy while
// never sending another event.
callDBus("%(name)s", "/", "%(iface)s", "ready", connected);

// Then report the currently focused window, if there is one
onActivated(workspace.activeWindow || workspace.activeClient);
"""


@dataclass
class WindowInfo:
    """Information about the active window"""
    app_id: str = ""
    title: str = ""
    wm_class: str = ""

    def __repr__(self):
        return f"WindowInfo(app_id='{self.app_id}', title='{self.title}', class='{self.wm_class}')"


class WindowMonitor:
    """Monitor active window on Wayland compositors and X11"""

    def __init__(self):
        self.compositor = None
        self.last_window = None
        self._kwin_script_path = None
        # None until the first query verifies the tool's chained output, then
        # True/False for the rest of the session
        self._supports_chaining = None
        # How X11 windows are queried, decided on the first query: 'xdotool',
        # 'xprop' (xdotool too old for getwindowclassname) or 'title' (neither)
        self._x11_mode = None
        self._kdotool_path = self._find_kdotool()
        self._detect_compositor()

    def _find_kdotool(self) -> Optional[str]:
        """Find kdotool in common locations"""
        # Check common installation paths
        possible_paths = ['kdotool']  # In PATH

        # If running under sudo, check real user's home first
        sudo_user = os.environ.get('SUDO_USER')
        if sudo_user:
            sudo_home = os.path.expanduser(f'~{sudo_user}')
            possible_paths.append(os.path.join(sudo_home, '.cargo/bin/kdotool'))

        # Then check current user's home
        home = os.path.expanduser('~')
        possible_paths.extend([
            os.path.join(home, '.cargo/bin/kdotool'),  # Cargo default
            '/usr/local/bin/kdotool',  # System-wide
            '/usr/bin/kdotool',  # Package manager
        ])

        for path in possible_paths:
            try:
                result = subprocess.run(
                    [path, '--version'],
                    capture_output=True,
                    timeout=1
                )
                if result.returncode == 0:
                    return path
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

        return None

    def _detect_compositor(self):
        """Auto-detect which Wayland compositor or X11 session is running"""

        # Check environment variables
        session = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
        session_type = os.environ.get('XDG_SESSION_TYPE', '').lower()
        wayland_display = os.environ.get('WAYLAND_DISPLAY', '')

        if not wayland_display and session_type != 'x11':
            logger.warning("WAYLAND_DISPLAY not set and not X11 - may not be running a supported session")

        # Try to detect compositor by testing commands
        # X11 is last as a generic fallback after all Wayland-specific detectors
        detectors = [
            ('sway', self._test_sway),
            ('hyprland', self._test_hyprland),
            ('gnome', self._test_gnome),
            ('kde', self._test_kde),
            ('niri', self._test_niri),
            ('mango', self._test_mango),
            ('x11', self._test_x11),
        ]

        for name, test_func in detectors:
            if test_func():
                self.compositor = name
                logger.info(f"Detected window manager: {name}")
                return

        logger.warning(f"Could not detect compositor or window manager (session={session}, type={session_type})")
        logger.warning("Profile switching will be disabled")

    def _test_sway(self) -> bool:
        """Test if Sway is running"""
        try:
            result = subprocess.run(
                ['swaymsg', '-t', 'get_version'],
                capture_output=True,
                timeout=1
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _test_niri(self) -> bool:
        """Test if Niri is running"""
        try:
            result = subprocess.run(
                ['niri', 'msg', 'version'],
                capture_output=True,
                timeout=1
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
            
    def _test_mango(self) -> bool:
        """Test if Mango is running"""
        try:
            result = subprocess.run(
                ['mmsg', 'get', 'version'],
                capture_output=True,
                timeout=1
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _test_hyprland(self) -> bool:
        """Test if Hyprland is running"""
        try:
            result = subprocess.run(
                ['hyprctl', 'version'],
                capture_output=True,
                timeout=1
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _test_gnome(self) -> bool:
        """Test if GNOME Shell is running"""
        try:
            result = subprocess.run(
                ['gdbus', 'introspect', '--session', '--dest', 'org.gnome.Shell',
                 '--object-path', '/org/gnome/Shell'],
                capture_output=True,
                timeout=1
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _test_kde(self) -> bool:
        """Test if KDE Plasma (KWin) is running"""
        # Check if kdotool is available (required for KDE window detection)
        if not self._kdotool_path:
            return False

        try:
            result = subprocess.run(
                [self._kdotool_path, 'getactivewindow'],
                capture_output=True,
                timeout=1
            )
            # If kdotool works, KDE is running
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _test_x11(self) -> bool:
        """Test if running on X11 with xdotool available"""
        session_type = os.environ.get('XDG_SESSION_TYPE', '').lower()
        if session_type != 'x11':
            return False

        try:
            result = subprocess.run(
                ['xdotool', 'getactivewindow'],
                capture_output=True,
                timeout=1
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def get_active_window(self) -> Optional[WindowInfo]:
        """Get information about the currently active window"""

        if not self.compositor:
            return None

        try:
            if self.compositor == 'sway':
                return self._get_sway_window()
            elif self.compositor == 'hyprland':
                return self._get_hyprland_window()
            elif self.compositor == 'gnome':
                return self._get_gnome_window()
            elif self.compositor == 'kde':
                return self._get_kde_window()
            elif self.compositor == 'niri':
                return self._get_niri_window()
            elif self.compositor == 'mango':
                return self._get_mango_window()
            elif self.compositor == 'x11':
                return self._get_x11_window()
        except Exception as e:
            logger.error(f"Error getting active window: {e}")
            return None

        return None

    def _get_sway_window(self) -> Optional[WindowInfo]:
        """Get active window from Sway"""
        try:
            result = subprocess.run(
                ['swaymsg', '-t', 'get_tree'],
                capture_output=True,
                text=True,
                timeout=1
            )

            if result.returncode != 0:
                return None

            tree = json.loads(result.stdout)
            focused = self._find_focused_node(tree)

            if focused:
                return WindowInfo(
                    app_id=focused.get('app_id', ''),
                    title=focused.get('name', ''),
                    wm_class=focused.get('window_properties', {}).get('class', '')
                )
        except Exception as e:
            logger.debug(f"Sway window detection error: {e}")

        return None

    def _find_focused_node(self, node):
        """Recursively find the focused node in Sway tree"""
        if node.get('focused'):
            return node

        for child in node.get('nodes', []) + node.get('floating_nodes', []):
            result = self._find_focused_node(child)
            if result:
                return result

        return None

    def _get_hyprland_window(self) -> Optional[WindowInfo]:
        """Get active window from Hyprland"""
        try:
            result = subprocess.run(
                ['hyprctl', 'activewindow', '-j'],
                capture_output=True,
                text=True,
                timeout=1
            )

            if result.returncode != 0:
                return None

            window = json.loads(result.stdout)

            return WindowInfo(
                app_id=window.get('class', ''),
                title=window.get('title', ''),
                wm_class=window.get('class', '')
            )
        except Exception as e:
            logger.debug(f"Hyprland window detection error: {e}")

        return None

    def _get_niri_window(self) -> Optional[WindowInfo]:
        """Get active window from Niri"""
        try:
            result = subprocess.run(
                ['niri', 'msg', '--json', "focused-window"],
                capture_output=True,
                text=True,
                timeout=1
            )

            if result.returncode != 0:
                return None

            window = json.loads(result.stdout)

            return WindowInfo(
                app_id=window.get('app_id', ''),
                title=window.get('title', ''),
                wm_class=window.get('app_id', '')
            )
        except Exception as e:
            logger.debug(f"Niri window detection error: {e}")

        return None
    
    def _get_mango_window(self) -> Optional[WindowInfo]:
        """Get active window from Mango"""
        try:
            result = subprocess.run(
                ['mmsg', 'get', "focusing-client"],
                capture_output=True,
                text=True,
                timeout=1
            )

            if result.returncode != 0:
                return None

            window = json.loads(result.stdout)

            return WindowInfo(
                app_id=window.get('appid', ''),
                title=window.get('title', ''),
                wm_class=window.get('appid', '')
            )
        except Exception as e:
            logger.debug(f"Mango window detection error: {e}")

        return None
 
    def _get_gnome_window(self) -> Optional[WindowInfo]:
        """Get active window from GNOME Shell

        Requires the "Focused Window D-Bus" extension:
        https://extensions.gnome.org/extension/5592/focused-window-d-bus/
        """
        try:
            # Try the "Focused Window D-Bus" extension first (works on modern GNOME)
            result = subprocess.run([
                'gdbus', 'call', '--session',
                '--dest', 'org.gnome.Shell',
                '--object-path', '/org/gnome/shell/extensions/FocusedWindow',
                '--method', 'org.gnome.shell.extensions.FocusedWindow.Get'
            ], capture_output=True, text=True, timeout=2)

            if result.returncode == 0 and result.stdout:
                # Parse the returned JSON from gdbus
                # Output format: ('{"wm_class": "...", "title": "...", ...}',)
                import re

                # Extract JSON string from gdbus tuple output
                json_match = re.search(r'\(\'(.+)\',\)', result.stdout)
                if json_match:
                    json_str = json_match.group(1)
                    # Parse JSON
                    try:
                        data = json.loads(json_str)
                        wm_class = data.get('wm_class', '')
                        title = data.get('title', '')

                        if wm_class or title:
                            return WindowInfo(
                                app_id=wm_class,
                                title=title,
                                wm_class=wm_class
                            )
                    except json.JSONDecodeError:
                        logger.debug("Failed to parse JSON from Focused Window D-Bus")

        except Exception as e:
            logger.debug(f"GNOME Focused Window D-Bus extension error: {e}")

        # Extension not installed - GNOME 40+ blocks Shell.Eval for security
        logger.warning("GNOME: Focused Window D-Bus extension not detected")
        logger.warning("Install from: https://extensions.gnome.org/extension/5592/focused-window-d-bus/")
        return None

    def _get_kde_window(self) -> Optional[WindowInfo]:
        """Get active window from KDE Plasma (KWin)

        Uses kdotool as a command-line tool (subprocess).
        kdotool internally uses D-Bus to communicate with KWin.

        Class and title are fetched in a SINGLE chained invocation. Each
        kdotool call loads, runs and unloads a KWin script over D-Bus, so a
        second call would double that traffic for no benefit - chaining the
        getters costs nothing measurable (~12ms either way).

        Requires: cargo install kdotool
        """
        if not self._kdotool_path:
            return None

        try:
            return self._query_window_tool([self._kdotool_path])
        except Exception as e:
            logger.debug(f"KDE window detection error: {e}")

        return None

    def _query_window_tool(self, base_argv) -> Optional[WindowInfo]:
        """Ask an xdotool-compatible tool for the active window's class and title

        Prefers a single chained invocation, which halves the process spawns.
        Not every version of every tool chains two getters the same way, so the
        first successful query verifies the chained result against separate
        calls and permanently falls back to those if they disagree. Detection
        therefore never becomes less reliable than the one-call-per-getter form.
        """
        if self._supports_chaining is None:
            return self._verify_chaining(base_argv)

        if self._supports_chaining:
            window = self._query_window_tool_chained(base_argv)
            if window:
                return window
            # Nothing from the chained call. Expected when no window is focused,
            # so only blame chaining if separate calls do better.
            window = self._query_window_tool_split(base_argv)
            if window:
                self._disable_chaining(base_argv, "chained call returned nothing")
            return window

        return self._query_window_tool_split(base_argv)

    def _verify_chaining(self, base_argv) -> Optional[WindowInfo]:
        """Decide once whether this tool's chained output can be trusted

        Runs both forms and compares. Anything other than an exact match - a
        tool that rejects the chain, prints only the last getter, or prints them
        in a different order - disables chaining for the rest of the session.
        """
        chained = self._query_window_tool_chained(base_argv)
        split = self._query_window_tool_split(base_argv)

        # No focused window: nothing to compare yet, try again on the next call
        if split is None:
            return None

        if chained == split:
            self._supports_chaining = True
            logger.debug(
                f"{os.path.basename(base_argv[0])} chained getters verified"
            )
        else:
            self._disable_chaining(
                base_argv, f"chained result {chained} != {split}"
            )

        return split

    def _disable_chaining(self, base_argv, reason: str):
        """Stop using chained getters for this session"""
        self._supports_chaining = False
        logger.info(
            f"{os.path.basename(base_argv[0])} does not support chained getters "
            "- using one call per getter"
        )
        logger.debug(f"Chaining disabled: {reason}")

    def _query_window_tool_chained(self, base_argv) -> Optional[WindowInfo]:
        """Fetch class and title in a single invocation"""
        result = subprocess.run(
            base_argv + ['getactivewindow', 'getwindowclassname', 'getwindowname'],
            capture_output=True, text=True, timeout=1
        )
        if result.returncode != 0:
            return None
        return self._parse_chained_output(result.stdout)

    def _query_window_tool_split(self, base_argv) -> Optional[WindowInfo]:
        """Fetch class and title with one call each (pre-chaining behaviour)"""
        class_result = subprocess.run(
            base_argv + ['getactivewindow', 'getwindowclassname'],
            capture_output=True, text=True, timeout=1
        )
        title_result = subprocess.run(
            base_argv + ['getactivewindow', 'getwindowname'],
            capture_output=True, text=True, timeout=1
        )

        # Either one succeeding is enough to identify the window
        if class_result.returncode != 0 and title_result.returncode != 0:
            return None

        window_class = class_result.stdout.strip() if class_result.returncode == 0 else ''
        window_title = title_result.stdout.strip() if title_result.returncode == 0 else ''

        if not window_class and not window_title:
            return None

        return WindowInfo(
            app_id=window_class,
            title=window_title,
            wm_class=window_class
        )

    @staticmethod
    def _parse_chained_output(stdout: str) -> Optional[WindowInfo]:
        """Parse the output of a chained 'classname then name' invocation

        Both kdotool and xdotool print one line per chained getter. A missing
        title (some windows have none) still yields a usable class match.
        """
        lines = stdout.split('\n')
        window_class = lines[0].strip() if lines else ''
        window_title = lines[1].strip() if len(lines) > 1 else ''

        if not window_class and not window_title:
            return None

        return WindowInfo(
            app_id=window_class,
            title=window_title,
            wm_class=window_class
        )

    def _get_x11_window(self) -> Optional[WindowInfo]:
        """Get active window on X11 using xdotool

        Old xdotool builds (e.g. 3.20160805.1, still shipped by Linux Mint) have
        no getwindowclassname, which leaves the class empty. Those read WM_CLASS
        with xprop instead; without xprop only the title is available.

        Requires: xdotool (available in most distro repositories), plus xprop
        when xdotool is too old
        """
        try:
            if self._x11_mode is None:
                self._x11_mode = self._detect_x11_mode()

            if self._x11_mode == 'xprop':
                return self._query_x11_xprop()
            if self._x11_mode == 'title':
                return self._query_x11_title()
            return self._query_window_tool(['xdotool'])
        except Exception as e:
            logger.debug(f"X11 window detection error: {e}")

        return None

    def _detect_x11_mode(self) -> str:
        """Decide once how to query X11 windows, based on xdotool's command list"""
        try:
            result = subprocess.run(
                ['xdotool', 'help'],
                capture_output=True, text=True, timeout=1
            )
            commands = result.stdout + result.stderr
        except (FileNotFoundError, subprocess.TimeoutExpired):
            commands = ''

        # Only act on something that looks like a command list, otherwise keep
        # the normal path
        if 'getactivewindow' not in commands or 'getwindowclassname' in commands:
            return 'xdotool'

        if shutil.which('xprop'):
            logger.info("xdotool has no getwindowclassname - reading window class with xprop")
            return 'xprop'

        logger.warning(
            "xdotool has no getwindowclassname and xprop is not installed - "
            "profiles can only match on window title. Install xprop "
            "(x11-utils on Debian/Ubuntu/Mint, xorg-xprop on Arch) to match on "
            "window class"
        )
        return 'title'

    def _query_x11_xprop(self) -> Optional[WindowInfo]:
        """Fetch class and title with xprop, for xdotool without getwindowclassname"""
        result = subprocess.run(
            ['xdotool', 'getactivewindow'],
            capture_output=True, text=True, timeout=1
        )
        window_id = result.stdout.strip()
        if result.returncode != 0 or not window_id:
            return None

        result = subprocess.run(
            ['xprop', '-id', window_id, 'WM_CLASS', '_NET_WM_NAME', 'WM_NAME'],
            capture_output=True, text=True, timeout=1
        )
        if result.returncode != 0:
            return None
        return self._parse_xprop_output(result.stdout)

    @staticmethod
    def _parse_xprop_output(stdout: str) -> Optional[WindowInfo]:
        """Parse xprop's WM_CLASS / _NET_WM_NAME / WM_NAME output

        WM_CLASS holds "instance", "class". xdotool's getwindowclassname reports
        the class, so that is used for both app_id and wm_class to keep profiles
        matching the same way whichever tool supplied them.
        """
        props = {}
        for line in stdout.splitlines():
            match = XPROP_LINE.match(line)
            if match:
                props[match.group(1)] = [
                    re.sub(r'\\(.)', r'\1', value)
                    for value in XPROP_STRING.findall(match.group(2))
                ]

        wm_class = props.get('WM_CLASS')
        window_class = wm_class[-1] if wm_class else ''
        # Same preference as xdotool's getwindowname
        titles = props.get('_NET_WM_NAME') or props.get('WM_NAME')
        window_title = titles[0] if titles else ''

        if not window_class and not window_title:
            return None

        return WindowInfo(
            app_id=window_class,
            title=window_title,
            wm_class=window_class
        )

    def _query_x11_title(self) -> Optional[WindowInfo]:
        """Fetch only the title, for xdotool without getwindowclassname or xprop"""
        result = subprocess.run(
            ['xdotool', 'getactivewindow', 'getwindowname'],
            capture_output=True, text=True, timeout=1
        )
        window_title = result.stdout.strip()
        if result.returncode != 0 or not window_title:
            return None

        return WindowInfo(app_id='', title=window_title, wm_class='')

    # --- KDE event-driven monitoring ---------------------------------------

    async def _run_kde_event_monitor(self, callback) -> bool:
        """Run event-driven window monitoring on KDE until cancelled

        Owns a D-Bus name, loads a KWin script that pushes focus and title
        changes to it, then dispatches them to callback. No polling involved.

        Returns:
            True if event monitoring ran (and has now been cancelled),
            False if it could not be set up and polling should be used
        """
        try:
            from dbus_fast.aio import MessageBus
            from dbus_fast.service import ServiceInterface, method
            from dbus_fast import BusType, Message, MessageType, RequestNameReply
        except ImportError as e:
            logger.info(f"dbus-fast unavailable, cannot use KDE event monitoring: {e}")
            return False

        queue: asyncio.Queue = asyncio.Queue()
        ready = asyncio.get_running_loop().create_future()

        class _Receiver(ServiceInterface):
            """Receives handshake and windowChanged calls from the KWin script"""

            def __init__(self):
                super().__init__(KDE_DBUS_INTERFACE)

            @method(name='ready')
            def script_ready(self, signal_connected: 'b'):
                if not ready.done():
                    ready.set_result(signal_connected)

            @method(name='windowChanged')
            def window_changed(self, window_class: 's', title: 's'):
                queue.put_nowait((window_class, title))

        bus = None
        script_loaded = False
        try:
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            bus.export('/', _Receiver())

            reply = await bus.request_name(KDE_DBUS_NAME)
            # Another driver instance already owns the name - do not fight over it
            if reply != RequestNameReply.PRIMARY_OWNER:
                logger.warning(
                    f"Could not own {KDE_DBUS_NAME} ({reply.name}) - "
                    "is another TuxBox instance running?"
                )
                return False

            script_loaded = await self._load_kwin_script(bus, Message, MessageType)
            if not script_loaded:
                return False

            # Handshake. Proves two things before we commit to event mode:
            # that D-Bus callbacks reach us at all, and that the script found an
            # activation signal to connect to. Without the second check a KWin
            # with an unrecognised API would look healthy while silently never
            # reporting another window change.
            try:
                signal_connected = await asyncio.wait_for(
                    ready, timeout=KDE_EVENT_HANDSHAKE_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "KWin script loaded but did not call back "
                    f"within {KDE_EVENT_HANDSHAKE_TIMEOUT}s"
                )
                return False

            if not signal_connected:
                logger.warning(
                    "KWin exposes no window-activation signal "
                    "(unsupported Plasma version?)"
                )
                return False

            logger.info("KDE event-driven window monitoring active (no polling)")

            while True:
                await self._dispatch_kde_event(await queue.get(), callback)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"KDE event monitoring failed: {e}")
            return False
        finally:
            # Cleanup on shutdown. Awaiting during cancellation can itself be
            # interrupted, so this is best-effort - a script left registered is
            # cleared by the defensive unload in _load_kwin_script() next run.
            if script_loaded:
                try:
                    await asyncio.shield(
                        self._unload_kwin_script(bus, Message, MessageType)
                    )
                except (Exception, asyncio.CancelledError):
                    logger.debug("KWin script cleanup interrupted")
            if bus is not None:
                try:
                    bus.disconnect()
                except Exception:
                    pass

    async def _dispatch_kde_event(self, event, callback):
        """Turn a (class, title) event into a callback, skipping duplicates"""
        window_class, title = event
        if not window_class and not title:
            return

        window = WindowInfo(app_id=window_class, title=title, wm_class=window_class)
        if window != self.last_window:
            logger.debug(f"Window changed: {window}")
            self.last_window = window
            await callback(window)

    async def _load_kwin_script(self, bus, Message, MessageType) -> bool:
        """Write the KWin script to disk and load it into KWin via D-Bus"""
        script = KDE_KWIN_SCRIPT % {
            'name': KDE_DBUS_NAME,
            'iface': KDE_DBUS_INTERFACE,
        }

        # KWin reads the script from a path, so it needs a real file. The name is
        # fixed rather than per-PID: only one instance can hold the D-Bus name
        # anyway, so a hard-killed run leaves at most one file, overwritten here.
        runtime_dir = os.environ.get('XDG_RUNTIME_DIR') or '/tmp'
        self._kwin_script_path = os.path.join(runtime_dir, f'{KDE_SCRIPT_NAME}.js')
        try:
            with open(self._kwin_script_path, 'w') as f:
                f.write(script)
        except OSError as e:
            logger.warning(f"Could not write KWin script: {e}")
            return False

        # A previous run that died without cleaning up may have left the script
        # registered under this name; unloading first keeps loads idempotent.
        await self._kwin_call(bus, Message, MessageType,
                              'unloadScript', 's', [KDE_SCRIPT_NAME])

        reply = await self._kwin_call(
            bus, Message, MessageType, 'loadScript', 'ss',
            [self._kwin_script_path, KDE_SCRIPT_NAME]
        )
        if reply is None or not reply.body:
            logger.warning("KWin loadScript failed")
            return False

        script_id = reply.body[0]
        run_reply = await self._kwin_call(
            bus, Message, MessageType, 'run', '', [],
            path=f'/Scripting/Script{script_id}',
            interface='org.kde.kwin.Script'
        )
        if run_reply is None:
            logger.warning(f"Could not start KWin script {script_id}")
            return False

        return True

    async def _unload_kwin_script(self, bus, Message, MessageType):
        """Unload the KWin script and remove its file"""
        try:
            await self._kwin_call(bus, Message, MessageType,
                                  'unloadScript', 's', [KDE_SCRIPT_NAME])
            logger.debug("Unloaded KWin script")
        except Exception as e:
            logger.debug(f"Error unloading KWin script: {e}")

        if self._kwin_script_path:
            try:
                os.unlink(self._kwin_script_path)
            except OSError:
                pass
            self._kwin_script_path = None

    @staticmethod
    async def _kwin_call(bus, Message, MessageType, member, signature, body,
                         path='/Scripting', interface='org.kde.kwin.Scripting'):
        """Make a single D-Bus call to KWin, returning None on failure"""
        msg = Message(
            destination='org.kde.KWin',
            path=path,
            interface=interface,
            member=member,
            signature=signature,
            body=body,
        )
        try:
            reply = await asyncio.wait_for(bus.call(msg), timeout=2.0)
        except Exception as e:
            logger.debug(f"KWin call {member} failed: {e}")
            return None

        # An error reply carries the error name, not a usable body (see #53)
        if reply is None or reply.message_type == MessageType.ERROR:
            logger.debug(f"KWin call {member} returned error: "
                         f"{getattr(reply, 'error_name', 'unknown')}")
            return None
        return reply

    async def monitor_window_changes(self, callback, interval: float = DEFAULT_POLL_INTERVAL):
        """Monitor for window changes and call callback when window changes

        On KDE this first tries event-driven monitoring (KWin pushes changes, no
        polling, switches apply immediately) and only falls back to polling if
        that cannot be set up.

        Args:
            callback: Async function to call with WindowInfo when window changes
            interval: Polling interval in seconds (default 0.2s)
        """
        if not self.compositor:
            logger.warning("No compositor detected - window monitoring disabled")
            return

        if self.compositor == 'kde':
            if await self._run_kde_event_monitor(callback):
                return  # Ran event-driven until cancelled
            logger.warning("KDE event monitoring unavailable - falling back to polling")

        logger.info(f"Starting window monitor (compositor: {self.compositor}, interval: {interval}s)")

        while True:
            try:
                # get_active_window() spawns a subprocess and blocks for ~10-25ms.
                # Run it in a thread so button events are not delayed by polling.
                current_window = await asyncio.to_thread(self.get_active_window)

                # Check if window changed
                if current_window != self.last_window:
                    if current_window:
                        logger.debug(f"Window changed: {current_window}")
                        await callback(current_window)
                    self.last_window = current_window

                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Error in window monitor: {e}")
                await asyncio.sleep(interval)


# Backward compatibility alias
WaylandWindowMonitor = WindowMonitor


# Convenience function for testing
async def test_monitor():
    """Test window monitoring"""
    monitor = WindowMonitor()

    if not monitor.compositor:
        print("No compositor or window manager detected!")
        return

    print(f"Monitoring windows on {monitor.compositor}...")
    print("Switch between applications to see window changes")
    print("Press Ctrl+C to exit")
    print()

    async def print_window(window: WindowInfo):
        print(f"Active window: {window}")

    task = asyncio.create_task(monitor.monitor_window_changes(print_window))

    # Cancel on SIGTERM as well as Ctrl-C. Without this, being killed by e.g.
    # `timeout` skips cleanup and leaves the KWin script loaded.
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, task.cancel)
        except (NotImplementedError, RuntimeError):
            pass  # Not available on this platform

    try:
        await task
    except asyncio.CancelledError:
        print("\nExiting...")


if __name__ == '__main__':
    try:
        asyncio.run(test_monitor())
    except KeyboardInterrupt:
        print("\nExiting...")
        pass
