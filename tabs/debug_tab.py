"""Hidden Logs tab — thin shell over the Logs V2 diagnostics console.
Keeps the historical contract every caller relies on: the `logging_enabled`
attribute, `append_log(message)` (now with optional `level`), and the
credential-diagnostics passthrough (credential lines are captured even
before Enable Logging is on, so AppImage users can inspect keyring
behavior).

The class now lives in utils/widgets/logs_console/app_log.py as
AppLogConsole (the launchpad window uses it too); DebugTab is that class."""
from __future__ import annotations

from utils.widgets.logs_console.app_log import AppLogConsole as DebugTab  # noqa: F401
