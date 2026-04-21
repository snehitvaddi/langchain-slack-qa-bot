"""Per-request timing tracker for observability.

Records elapsed time per stage (agent, slack_post, etc.) and emits one
summary log line per request. Complements LangSmith's LLM traces with
grep-able local logs that include non-LLM stages (Slack API, memory, etc.).
"""

from __future__ import annotations

import time
from contextlib import contextmanager


class TimingTracker:
    """Lightweight per-request timer. Records ms per named stage."""

    def __init__(self):
        self.stages: dict[str, int] = {}
        self.start_total = time.perf_counter()

    @contextmanager
    def stage(self, name: str):
        """Context manager that records elapsed ms under `name`."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = int((time.perf_counter() - start) * 1000)

    def total_ms(self) -> int:
        return int((time.perf_counter() - self.start_total) * 1000)

    def format_summary(self, **extra) -> str:
        """Format as structured key=value log line.

        Extra fields (thread, query, tools, etc.) are appended inline.
        """
        parts = []
        for k, v in extra.items():
            if isinstance(v, str):
                # Quote strings that contain spaces
                v = v.replace("\n", " ")[:80]
                if " " in v:
                    v = f'"{v}"'
            parts.append(f"{k}={v}")
        for name, ms in self.stages.items():
            parts.append(f"{name}_ms={ms}")
        parts.append(f"total_ms={self.total_ms()}")
        return " ".join(parts)
