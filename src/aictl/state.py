\
from __future__ import annotations

import json

from .settings import STATE_DIR, STATE_FILE

DEFAULT_STATE = {"active_backend": "remote"}


def ensure_state() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps(DEFAULT_STATE, indent=2) + "\n")


def load_state() -> dict:
    ensure_state()
    return json.loads(STATE_FILE.read_text())


def save_state(state: dict) -> None:
    ensure_state()
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(STATE_FILE)


def active_backend() -> str:
    return load_state().get("active_backend", "remote")


def set_active_backend(name: str) -> None:
    state = load_state()
    state["active_backend"] = name
    save_state(state)
