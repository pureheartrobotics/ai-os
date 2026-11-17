"""Reads DeepSeek Harness session logs (~/.dsh/sessions/**/session.v4.jsonl.zstd) to measure a run."""
import glob
import io
import json
import os
from dataclasses import dataclass, field

import zstandard

SESSIONS_DIR = os.path.expanduser(r"~\.dsh\sessions")
AI_OS_PREFIX = "mcp__ai-os__"


@dataclass
class RunMetrics:
    turns: int = 0
    seconds: float = 0.0
    tool_calls: list[str] = field(default_factory=list)
    tokens: int = 0
    retries: int = 0
    outcome: str = "none"

    @property
    def ai_os_calls(self) -> int:
        return sum(name.startswith(AI_OS_PREFIX) for name in self.tool_calls)


def _records(path: str):
    """Yields records, tolerating a frame that DSH is still writing."""
    with open(path, "rb") as f:
        reader = zstandard.ZstdDecompressor().stream_reader(f, read_across_frames=True)
        buf = io.BytesIO()
        try:
            while chunk := reader.read(1 << 16):
                buf.write(chunk)
        except zstandard.ZstdError:
            pass
    for line in buf.getvalue().decode("utf-8", "replace").splitlines():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def collect(since: float) -> RunMetrics:
    """Aggregates every DSH event recorded after `since` (unix seconds)."""
    since_ms = since * 1000
    metrics = RunMetrics()
    first_start = last_end = None
    for path in glob.glob(os.path.join(SESSIONS_DIR, "*", "*", "session.v4.jsonl.zstd")):
        if os.path.getmtime(path) < since:
            continue
        for record in _records(path):
            time_ms = record.get("time", 0)
            if time_ms < since_ms:
                continue
            kind, data = record.get("type"), record.get("data") or {}
            if kind == "turn/start":
                metrics.turns += 1
                first_start = time_ms if first_start is None else min(first_start, time_ms)
            elif kind == "turn/end":
                if last_end is None or time_ms > last_end:
                    last_end = time_ms
                    metrics.outcome = (data.get("reason") or {}).get("kind", "?")
            elif kind == "tool/call":
                metrics.tool_calls.append(data.get("name", ""))
            elif kind == "assistant/message":
                metrics.tokens += (data.get("usage") or {}).get("totalTokens", 0)
            elif kind == "llm/retry":
                metrics.retries += 1
    if first_start is not None and last_end is not None:
        metrics.seconds = round((last_end - first_start) / 1000, 1)
    return metrics
