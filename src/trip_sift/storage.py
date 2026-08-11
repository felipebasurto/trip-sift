from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


def default_state_dir() -> Path:
    env = os.environ.get("TRIP_SIFT_STATE_DIR")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "trip-sift"
    return Path.home() / ".local" / "state" / "trip-sift"


def write_json_atomic(payload: Mapping[str, object], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, destination)
