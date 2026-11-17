"""Launches workbench.ps1 and collects the events it reports on stdout."""
import base64
import json
import os
import subprocess
import threading
import time

SCRIPT = os.path.join(os.path.dirname(__file__), "workbench.ps1")
READY_TIMEOUT_S = 15


class Workbench:
    def __init__(self, scenario: str):
        self.scenario = scenario
        self.events: list[dict] = []
        self._process: subprocess.Popen | None = None

    def start(self) -> None:
        self.events = []
        with open(SCRIPT, encoding="utf-8") as f:
            script = f"$Scenario = '{self.scenario}'\n" + f.read()
        # -EncodedCommand takes UTF-16LE, which sidesteps Windows PowerShell's ANSI script-file decoding.
        encoded = base64.b64encode(script.encode("utf-16-le")).decode()
        self._process = subprocess.Popen(
            ["powershell", "-NoProfile", "-STA", "-EncodedCommand", encoded],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=self._read, daemon=True).start()
        deadline = time.monotonic() + READY_TIMEOUT_S
        while not self.last("ready") and time.monotonic() < deadline:
            time.sleep(0.2)
        time.sleep(0.5)

    def _read(self) -> None:
        for raw in self._process.stdout:
            try:
                self.events.append(json.loads(raw.decode("utf-8", "replace")))
            except json.JSONDecodeError:
                continue

    def last(self, event: str) -> dict | None:
        return next((e for e in reversed(self.events) if e.get("event") == event), None)

    def stop(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.kill()
        self._process = None
