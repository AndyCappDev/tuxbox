#!/usr/bin/env python3
"""Driver service management for TuxBox

Handles starting, stopping, and checking status of the driver service.
Supports both systemd and non-systemd init systems via configurable commands.
"""

import subprocess
import logging
import shutil
import os
from pathlib import Path
from typing import Tuple, Optional

from tuxbox.i18n import _

logger = logging.getLogger(__name__)


class DriverManager:
    """Manages the TuxBox driver service

    This class provides init-system-agnostic control of the driver:
    - reload_driver(): Uses direct SIGHUP signal (works on any system)
    - restart_driver(): Uses configurable command, falls back to systemctl
    - is_running(): Uses pgrep (works on any system)

    For non-systemd systems (OpenRC, runit, etc.), users can configure
    a custom restart_command in ~/.config/tuxbox/config.conf:

    [service]
    restart_command = rc-service tuxbox restart
    """

    SERVICE_NAME = "tuxbox"
    DRIVER_MODULE = "tuxbox"

    _restart_command_cache: Optional[str] = None
    _systemctl_available: Optional[bool] = None

    @staticmethod
    def _get_config_path() -> Path:
        """Get path to config.conf"""
        return Path.home() / '.config' / 'tuxbox' / 'config.conf'

    @staticmethod
    def _get_restart_command() -> Optional[str]:
        """Get custom restart command from config, if configured

        Returns:
            Custom restart command string, or None if not configured
        """
        if DriverManager._restart_command_cache is not None:
            return DriverManager._restart_command_cache if DriverManager._restart_command_cache else None

        config_path = DriverManager._get_config_path()
        if not config_path.exists():
            DriverManager._restart_command_cache = ""
            return None

        try:
            import configparser
            config = configparser.ConfigParser()
            config.read(config_path)

            if config.has_option('service', 'restart_command'):
                cmd = config.get('service', 'restart_command').strip()
                DriverManager._restart_command_cache = cmd
                if cmd:
                    logger.info(f"Using custom restart command: {cmd}")
                    return cmd
        except Exception as e:
            logger.warning(f"Error reading restart_command from config: {e}")

        DriverManager._restart_command_cache = ""
        return None

    @staticmethod
    def _is_systemctl_available() -> bool:
        """Check if systemctl is available on this system"""
        if DriverManager._systemctl_available is not None:
            return DriverManager._systemctl_available

        DriverManager._systemctl_available = shutil.which('systemctl') is not None
        return DriverManager._systemctl_available

    # Patterns to match driver processes via pgrep -f (full command line match).
    # Multiple patterns cover different invocation methods:
    #   - "python -m tuxbox [args]"         (standard / systemd service)
    #   - "/path/to/tuxbox [args]"          (pip entry point)
    #   - "/path/to/.tuxbox-wrapped [args]" (NixOS wrapper)
    # The patterns intentionally exclude GUI processes (tuxbox-gui, tuxbox.gui).
    DRIVER_PGREP_PATTERNS = [
        r'python.*-m\s+tuxbox(\s|$)',
        r'[/.]tuxbox(-wrapped)?(\s|$)',
    ]

    @staticmethod
    def _get_driver_pids() -> list:
        """Get PIDs of running driver processes

        Returns:
            List of PID strings for running tuxbox processes
        """
        all_pids = set()
        our_pid = str(os.getpid())
        parent_pid = str(os.getppid())

        for pattern in DriverManager.DRIVER_PGREP_PATTERNS:
            try:
                result = subprocess.run(
                    ['pgrep', '-f', pattern],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0 and result.stdout.strip():
                    for pid in result.stdout.strip().split('\n'):
                        if pid and pid != our_pid and pid != parent_pid:
                            all_pids.add(pid)

            except Exception as e:
                logger.debug(f"pgrep failed for pattern '{pattern}': {e}")

        return list(all_pids)

    @staticmethod
    def stop_driver() -> Tuple[bool, str]:
        """Stop the TuxBox driver service

        Returns:
            Tuple of (success, message)
        """
        # Try systemctl first if available
        if DriverManager._is_systemctl_available():
            try:
                result = subprocess.run(
                    ['systemctl', '--user', 'stop', DriverManager.SERVICE_NAME],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    logger.info("Driver stopped successfully via systemctl")
                    return True, _("Driver stopped successfully")
                else:
                    logger.error(f"Failed to stop driver: {result.stderr}")
                    return False, _("Failed to stop driver: %s") % (result.stderr,)

            except subprocess.TimeoutExpired:
                logger.error("Timeout stopping driver")
                return False, _("Timeout stopping driver")
            except Exception as e:
                logger.error(f"Error stopping driver: {e}")
                return False, _("Error stopping driver: %s") % (e,)
        else:
            # No systemctl - try to kill the process directly
            pids = DriverManager._get_driver_pids()
            if not pids:
                return True, _("Driver is not running")

            try:
                for pid in pids:
                    subprocess.run(['kill', pid], timeout=5)
                logger.info("Driver stopped via kill signal")
                return True, _("Driver stopped successfully")
            except Exception as e:
                return False, _("Failed to stop driver: %s") % (e,)

    @staticmethod
    def start_driver() -> Tuple[bool, str]:
        """Start the TuxBox driver service

        Returns:
            Tuple of (success, message)
        """
        if DriverManager._is_systemctl_available():
            try:
                result = subprocess.run(
                    ['systemctl', '--user', 'start', DriverManager.SERVICE_NAME],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    logger.info("Driver started successfully")
                    return True, _("Driver started successfully")
                else:
                    logger.error(f"Failed to start driver: {result.stderr}")
                    return False, _("Failed to start driver: %s") % (result.stderr,)

            except subprocess.TimeoutExpired:
                logger.error("Timeout starting driver")
                return False, _("Timeout starting driver")
            except Exception as e:
                logger.error(f"Error starting driver: {e}")
                return False, _("Error starting driver: %s") % (e,)
        else:
            return False, _(
                "Cannot start driver: systemctl not available.\n"
                "Please start the driver using your init system's commands."
            )

    @staticmethod
    def reload_driver() -> Tuple[bool, str]:
        """Apply new configuration to the TuxBox driver via SIGHUP

        Sends SIGHUP signal directly to the driver process to reload its
        configuration without restarting the service. This method works
        regardless of init system (systemd, OpenRC, runit, etc.).

        Returns:
            Tuple of (success, message)
        """
        try:
            # Find the driver process(es) and send SIGHUP directly
            pids = DriverManager._get_driver_pids()

            if not pids:
                logger.warning("No driver process found to reload")
                return False, _("Driver is not running")

            # Send SIGHUP to each driver process
            for pid in pids:
                try:
                    subprocess.run(
                        ['kill', '-HUP', pid],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    logger.info(f"Sent SIGHUP to driver process {pid}")
                except Exception as e:
                    logger.warning(f"Failed to send SIGHUP to {pid}: {e}")

            logger.info("Configuration reload signal sent successfully")
            return True, _("Configuration applied")

        except Exception as e:
            logger.error(f"Error applying configuration: {e}")
            return False, _("Error applying configuration: %s") % (e,)

    @staticmethod
    def restart_driver() -> Tuple[bool, str]:
        """Restart the TuxBox driver service

        Uses custom restart_command from config if configured,
        otherwise falls back to systemctl if available.

        Returns:
            Tuple of (success, message)
        """
        # Check for custom restart command first
        custom_cmd = DriverManager._get_restart_command()

        if custom_cmd:
            try:
                logger.info(f"Using custom restart command: {custom_cmd}")
                result = subprocess.run(
                    custom_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode == 0:
                    logger.info("Driver restarted successfully via custom command")
                    return True, _("Driver restarted successfully")
                else:
                    logger.error(f"Failed to restart driver: {result.stderr or result.stdout}")
                    return False, _("Failed to restart driver: %s") % (result.stderr or result.stdout,)

            except subprocess.TimeoutExpired:
                logger.error("Timeout restarting driver")
                return False, _("Timeout restarting driver")
            except Exception as e:
                logger.error(f"Error restarting driver: {e}")
                return False, _("Error restarting driver: %s") % (e,)

        # Fall back to systemctl if available
        if DriverManager._is_systemctl_available():
            try:
                result = subprocess.run(
                    ['systemctl', '--user', 'restart', DriverManager.SERVICE_NAME],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    logger.info("Driver restarted successfully via systemctl")
                    return True, _("Driver restarted successfully")
                else:
                    logger.error(f"Failed to restart driver: {result.stderr}")
                    return False, _("Failed to restart driver: %s") % (result.stderr,)

            except subprocess.TimeoutExpired:
                logger.error("Timeout restarting driver")
                return False, _("Timeout restarting driver")
            except Exception as e:
                logger.error(f"Error restarting driver: {e}")
                return False, _("Error restarting driver: %s") % (e,)

        # Neither custom command nor systemctl available
        return False, _(
            "Cannot restart driver: no restart command configured and systemctl not available.\n\n"
            "To configure a custom restart command, add to ~/.config/tuxbox/config.conf:"
        ) + (
            "\n\n[service]\n"
            "restart_command = your-restart-command-here\n\n"
        ) + _("Examples:") + (
            "\n  OpenRC: rc-service tuxbox restart\n"
            "  Manual: pkill -f 'python.*tuxbox' ; /path/to/start-tuxbox.sh"
        )

    @staticmethod
    def is_running() -> bool:
        """Check if the driver service is currently running

        Uses pgrep to check for running driver processes, which works
        regardless of init system.

        Returns:
            True if running, False otherwise
        """
        try:
            pids = DriverManager._get_driver_pids()
            is_active = len(pids) > 0
            logger.debug(f"Driver running status: {is_active} (pids: {pids})")
            return is_active

        except Exception as e:
            logger.error(f"Error checking driver status: {e}")
            return False

    @staticmethod
    def get_restart_instructions() -> str:
        """Get appropriate restart instructions for the current system

        Returns:
            String with restart instructions appropriate for the init system
        """
        custom_cmd = DriverManager._get_restart_command()
        if custom_cmd:
            return f"  {custom_cmd}"
        elif DriverManager._is_systemctl_available():
            return "  systemctl --user restart tuxbox"
        else:
            return (
                _("Configure a restart command in ~/.config/tuxbox/config.conf:")
                + "\n  [service]\n  restart_command = your-restart-command-here"
            )
