"""Update checker for TuxBox GUI

Fetches version information from GitHub releases and compares with installed version.
"""

import json
import logging
import urllib.request
import urllib.error

from PySide6.QtCore import QThread, Signal

from tuxbox.i18n import _

try:
    from tuxbox import VERSION
except ImportError:
    VERSION = "unknown"

logger = logging.getLogger(__name__)

# GitHub API URL for latest release
RELEASES_URL = "https://api.github.com/repos/AndyCappDev/tuxbox/releases/latest"
REQUEST_TIMEOUT = 5  # seconds


class UpdateChecker(QThread):
    """Background thread to check for updates on GitHub"""

    # Signals
    update_available = Signal(str, str, str)  # (latest_version, current_version, release_notes)
    no_update = Signal(str)                   # (current_version)
    check_failed = Signal(str)                # (error_message)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_version = VERSION

    def run(self):
        """Execute update check in background thread"""
        try:
            logger.info(f"Checking for updates (current version: {self.current_version})")

            # Fetch latest release from GitHub API
            request = urllib.request.Request(
                RELEASES_URL,
                headers={
                    'User-Agent': f'TuxBox/{self.current_version}',
                    'Accept': 'application/vnd.github.v3+json'
                }
            )
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                data = json.loads(response.read().decode('utf-8'))

            # Parse version from tag_name (e.g., "v2.2.0" -> "2.2.0")
            tag_name = data.get('tag_name', '')
            latest_version = tag_name.lstrip('v')
            if not latest_version:
                logger.error("Could not parse version from GitHub release")
                self.check_failed.emit(_("Could not parse version from GitHub release"))
                return

            release_notes = data.get('body', '') or ''
            logger.info(f"Latest version on GitHub: {latest_version}")

            # Compare versions
            if self._is_newer(latest_version, self.current_version):
                logger.info(f"Update available: {latest_version}")
                self.update_available.emit(latest_version, self.current_version, release_notes)
            else:
                logger.info("Already running latest version")
                self.no_update.emit(self.current_version)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                logger.error("No releases found on GitHub")
                self.check_failed.emit(_("No releases found on GitHub"))
            else:
                logger.error(f"GitHub API error: {e.code}")
                self.check_failed.emit(_("GitHub API error: %s") % (e.code,))
        except urllib.error.URLError as e:
            logger.error(f"Network error: {e.reason}")
            self.check_failed.emit(_("Network error: %s") % (e.reason,))
        except TimeoutError:
            logger.error("Request timed out")
            self.check_failed.emit(_("Request timed out"))
        except Exception as e:
            logger.error(f"Error checking for updates: {e}", exc_info=True)
            self.check_failed.emit(_("Error checking for updates: %s") % (e,))

    def _is_newer(self, latest: str, current: str) -> bool:
        """Compare semantic versions

        Args:
            latest: Latest version string (e.g., '2.2.0')
            current: Current version string (e.g., '2.1.0')

        Returns:
            True if latest is newer than current
        """
        try:
            latest_parts = [int(x) for x in latest.split('.')]
            current_parts = [int(x) for x in current.split('.')]
            return latest_parts > current_parts
        except ValueError:
            # If parsing fails, treat as no update
            logger.warning(f"Could not parse versions: {latest} vs {current}")
            return False
