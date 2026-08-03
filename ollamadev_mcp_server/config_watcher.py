"""Configuration file watcher for hot-reload.

Monitors the settings file for changes and automatically reloads the
configuration when modifications are detected.  Uses polling (not inotify)
for cross-platform compatibility.

Usage::

    from ollamadev_mcp_server.config_watcher import start_config_watcher

    start_config_watcher()  # Starts background thread
    # ... server runs ...
    stop_config_watcher()   # Clean shutdown
"""

import threading
import time
from pathlib import Path

from ollamadev_mcp_server.config import get_config, reload_config
from ollamadev_mcp_server.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Watcher state
# ---------------------------------------------------------------------------

_watcher_thread: threading.Thread | None = None
_watcher_stop_event: threading.Event = threading.Event()
_last_mtime: float = 0.0
_poll_interval: float = 5.0  # seconds


# ---------------------------------------------------------------------------
# Watcher implementation
# ---------------------------------------------------------------------------


def _watcher_loop() -> None:
    """Background loop that polls the settings file for changes."""
    global _last_mtime

    config = get_config()
    settings_file = config.settings_file

    # Initialize last modification time
    if settings_file.exists():
        _last_mtime = settings_file.stat().st_mtime
        logger.debug("Config watcher initialized: mtime=%.3f", _last_mtime)

    while not _watcher_stop_event.is_set():
        try:
            if settings_file.exists():
                current_mtime = settings_file.stat().st_mtime
                if current_mtime > _last_mtime:
                    logger.info(
                        "Settings file changed (mtime %.3f -> %.3f), reloading config",
                        _last_mtime,
                        current_mtime,
                    )
                    reload_config()
                    _last_mtime = current_mtime
            elif _last_mtime > 0:
                # File was deleted
                logger.info("Settings file deleted, reloading config")
                reload_config()
                _last_mtime = 0.0
        except Exception:
            logger.exception("Error in config watcher loop")

        _watcher_stop_event.wait(_poll_interval)


def start_config_watcher(poll_interval: float = 5.0) -> None:
    """Start the configuration file watcher in a background thread.

    Args:
        poll_interval: How often to check for file changes (seconds).
    """
    global _watcher_thread, _poll_interval

    if _watcher_thread is not None and _watcher_thread.is_alive():
        logger.warning("Config watcher already running")
        return

    _poll_interval = poll_interval
    _watcher_stop_event.clear()
    _watcher_thread = threading.Thread(
        target=_watcher_loop,
        name="config-watcher",
        daemon=True,
    )
    _watcher_thread.start()
    logger.info("Config watcher started (poll_interval=%.1fs)", poll_interval)


def stop_config_watcher(timeout: float = 2.0) -> None:
    """Stop the configuration file watcher.

    Args:
        timeout: Maximum time to wait for the thread to stop (seconds).
    """
    global _watcher_thread

    if _watcher_thread is None or not _watcher_thread.is_alive():
        logger.debug("Config watcher not running")
        return

    logger.info("Stopping config watcher")
    _watcher_stop_event.set()
    _watcher_thread.join(timeout=timeout)

    if _watcher_thread.is_alive():
        logger.warning("Config watcher thread did not stop within %.1fs", timeout)
    else:
        logger.info("Config watcher stopped")

    _watcher_thread = None


def is_watcher_running() -> bool:
    """Check if the config watcher is currently running."""
    return _watcher_thread is not None and _watcher_thread.is_alive()


def get_watcher_status() -> dict:
    """Get the current status of the config watcher.

    Returns:
        Dict with ``running``, ``poll_interval``, ``last_mtime``, and
        ``settings_file``.
    """
    config = get_config()
    return {
        "running": is_watcher_running(),
        "poll_interval": _poll_interval,
        "last_mtime": _last_mtime,
        "settings_file": str(config.settings_file),
    }
