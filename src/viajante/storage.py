"""External state directory and atomic JSON writes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


def default_state_dir() -> Path:
    env = os.environ.get("VIAJANTE_STATE_DIR")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "viajante"
    return Path.home() / ".local" / "state" / "viajante"


def write_json_atomic(payload: Mapping[str, object], destination: Path) -> None:
    write_text_atomic(
        json.dumps(payload, indent=2, ensure_ascii=False),
        destination,
    )


def write_text_atomic(text: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, destination)
