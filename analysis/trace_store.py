"""Persist and load RunTrace records as JSONL files."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from models import RunTrace

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path("traces")


def save_trace(trace: RunTrace, directory: str | Path = DEFAULT_DIR) -> Path:
    """Append *trace* as a single JSON line to ``{directory}/{date}.jsonl``."""
    dirpath = Path(directory)
    dirpath.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filepath = dirpath / f"{date_str}.jsonl"

    with open(filepath, "a", encoding="utf-8") as fh:
        fh.write(trace.model_dump_json() + "\n")

    logger.info("Saved trace %s to %s", trace.run_id, filepath)
    return filepath


def load_traces(directory: str | Path = DEFAULT_DIR) -> list[RunTrace]:
    """Read every RunTrace from all JSONL files in *directory*."""
    dirpath = Path(directory)
    if not dirpath.exists():
        return []

    traces: list[RunTrace] = []
    for filepath in sorted(dirpath.glob("*.jsonl")):
        with open(filepath, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    traces.append(RunTrace.model_validate_json(line))
    return traces


def load_traces_for_task(
    task: str, directory: str | Path = DEFAULT_DIR
) -> list[RunTrace]:
    """Return only traces whose task string matches *task* exactly."""
    return [t for t in load_traces(directory) if t.task == task]
