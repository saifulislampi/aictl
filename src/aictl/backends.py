\
from __future__ import annotations

import os
import shlex
import time
from dataclasses import dataclass
from typing import Literal

from . import tunnels
from .settings import Settings
from .state import active_backend, set_active_backend
from .utils import command_exists, http_json, http_ok, human_bytes, run, tmux_has

BackendName = Literal["local", "remote"]


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class Backend:
    name: BackendName
    url: str
    kind: str = "ollama"


def get_backend(settings: Settings, name: str | None = None) -> Backend:
    selected = name or active_backend()
    aliases = {
        "local": "local",
        "local-ollama": "local",
        "remote": "remote",
        "remote-ollama": "remote",
    }
    selected = aliases.get(selected, selected)

    if selected == "local":
        return Backend(name="local", url=settings.local_ollama_url)
    if selected == "remote":
        return Backend(name="remote", url=settings.remote_ollama_url)

    raise BackendError(f"Unknown backend: {selected}")


def health_url(backend: Backend) -> str:
    return backend.url + "/api/tags"


def reachable(backend: Backend) -> bool:
    return http_ok(health_url(backend))


def wait_until_reachable(backend: Backend, seconds: int = 10) -> bool:
    for _ in range(seconds * 2):
        if reachable(backend):
            return True
        time.sleep(0.5)
    return False


def start(settings: Settings, name: str) -> bool:
    backend = get_backend(settings, name)

    if reachable(backend):
        print(f"{backend.name}: already reachable")
        print(f"Endpoint: {backend.url}")
        return True

    if backend.name == "remote":
        return tunnels.start(settings)

    command = settings.local_ollama_start_command
    session = settings.local_ollama_session

    if not command_exists(command[0]):
        raise BackendError(
            f"Cannot start local backend: '{command[0]}' was not found in PATH."
        )

    if not command_exists("tmux"):
        raise BackendError("tmux is required for an aictl-managed local Ollama.")

    if not tmux_has(session):
        result = run(
            ["tmux", "new-session", "-d", "-s", session, shlex.join(command)],
            capture=True,
        )
        if result.returncode != 0:
            raise BackendError(result.stderr.strip() or "Failed to start local Ollama.")

    if wait_until_reachable(backend):
        print("local: started")
        print(f"Endpoint: {backend.url}")
        return True

    print("local: tmux session exists, but Ollama is not responding.")
    print(f"Inspect: tmux attach -t {session}")
    return False


def stop(settings: Settings, name: str) -> None:
    backend = get_backend(settings, name)

    if backend.name == "remote":
        tunnels.stop(settings)
        return

    session = settings.local_ollama_session

    if tmux_has(session):
        run(["tmux", "kill-session", "-t", session])
        print("local: stopped")
    elif reachable(backend):
        print(
            "local: Ollama is reachable but is not running in the "
            "aictl-managed tmux session. Leaving it untouched."
        )
    else:
        print("local: stopped")


def attach(settings: Settings, name: str) -> None:
    backend = get_backend(settings, name)

    if backend.name == "remote":
        tunnels.attach(settings)
        return

    session = settings.local_ollama_session

    if not tmux_has(session):
        raise BackendError(f"tmux session '{session}' does not exist.")

    os.execvp("tmux", ["tmux", "attach", "-t", session])


def use(settings: Settings, name: str) -> None:
    backend = get_backend(settings, name)
    set_active_backend(backend.name)

    print(f"Active backend: {backend.name}")
    print(f"Endpoint: {backend.url}")
    print(f"Status: {'reachable' if reachable(backend) else 'unreachable'}")


def switch(settings: Settings, name: str) -> bool:
    backend = get_backend(settings, name)

    if not reachable(backend):
        if not start(settings, backend.name):
            return False

    set_active_backend(backend.name)

    print(f"Active backend: {backend.name}")
    print(f"Endpoint: {backend.url}")
    return True


def status(settings: Settings, name: str | None = None) -> None:
    backend = get_backend(settings, name)

    print(f"Backend:  {backend.name}")
    print(f"Type:     {backend.kind}")
    print(f"Endpoint: {backend.url}")
    print(f"Status:   {'reachable' if reachable(backend) else 'unreachable'}")


def list_backends(settings: Settings) -> None:
    current = active_backend()

    for name in ("remote", "local"):
        backend = get_backend(settings, name)
        marker = "*" if name == current else " "
        state = "up" if reachable(backend) else "down"
        print(f"{marker} {name:<8} {state:<4} {backend.url}")


def list_models(settings: Settings, name: str | None = None) -> None:
    backend = get_backend(settings, name)

    try:
        payload = http_json(backend.url + "/api/tags")
    except Exception as exc:
        raise BackendError(f"Could not query {backend.name}: {exc}") from exc

    models = payload.get("models", [])
    if not models:
        print(f"No models found on {backend.name}.")
        return

    print(f"Models on {backend.name}:")
    for model in models:
        model_name = model.get("name") or model.get("model") or "unknown"
        size = model.get("size")
        size_text = human_bytes(size) if isinstance(size, int) else "?"
        print(f"  {model_name:<42} {size_text:>9}")
