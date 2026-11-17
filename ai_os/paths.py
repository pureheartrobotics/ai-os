import os
from pathlib import Path

STATE_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ai-os"
LOG_DIR = STATE_DIR / "logs"
STATE_FILE = STATE_DIR / "daemon.json"
PID_FILE = STATE_DIR / "service.pid"
STOP_FILE = STATE_DIR / "stop"
HEADLESS_PATCH = STATE_DIR / "headless.patch.yml"

# Named mutex held by the running daemon; the MCP server checks it so both don't fight over the hotkey.
DAEMON_MUTEX = "Local\\ai-os-daemon"
