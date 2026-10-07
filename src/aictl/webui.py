\
from __future__ import annotations

import os
import shlex
import time

from .backends import BackendError, get_backend, reachable
from .settings import Settings
from .utils import command_exists, http_ok, run, tmux_has


def url(settings: Settings) -> str:
    return f"http://{settings.webui_host}:{settings.webui_port}"


def running(settings: Settings) -> bool:
    return tmux_has(settings.webui_session)


def start(settings: Settings) -> None:
    if running(settings):
        print("open-webui: already running")
        print(f"URL: {url(settings)}")
        return

    backend = get_backend(settings)

    if not reachable(backend):
        raise BackendError(f"Active backend '{backend.name}' is unreachable.")

    if not command_exists("uvx"):
        raise RuntimeError("uvx not found. Install it with: brew install uv")

    if not command_exists("tmux"):
        raise RuntimeError("tmux not found.")

    settings.webui_data_dir.mkdir(parents=True, exist_ok=True)

    command = [
        "env",
        f"DATA_DIR={settings.webui_data_dir}",
        "ENABLE_PERSISTENT_CONFIG=false",
        f"OLLAMA_BASE_URL={backend.url}",
        "uvx",
        "--python",
        settings.webui_python,
        "open-webui@latest",
        "serve",
        "--host",
        settings.webui_host,
        "--port",
        str(settings.webui_port),
    ]

    result = run(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            settings.webui_session,
            shlex.join(command),
        ],
        capture=True,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to start Open WebUI.")

    print("open-webui: starting")
    print(f"Backend: {backend.name} ({backend.url})")
    print(f"URL: {url(settings)}")

    for _ in range(20):
        if http_ok(url(settings), timeout=1):
            print("Status: ready")
            return
        time.sleep(0.5)

    print("Status: tmux session is running; Open WebUI is still starting.")


def stop(settings: Settings) -> None:
    if tmux_has(settings.webui_session):
        run(["tmux", "kill-session", "-t", settings.webui_session])
        print("open-webui: stopped")
    else:
        print("open-webui: already stopped")


def restart(settings: Settings) -> None:
    stop(settings)
    time.sleep(0.5)
    start(settings)


def status(settings: Settings) -> None:
    backend = get_backend(settings)

    print(f"Open WebUI tmux: {'running' if running(settings) else 'stopped'}")
    print(f"Open WebUI HTTP: {'reachable' if http_ok(url(settings)) else 'unreachable'}")
    print(f"URL: {url(settings)}")
    print(f"Backend: {backend.name}")
    print(f"Backend URL: {backend.url}")
    print(f"Backend status: {'reachable' if reachable(backend) else 'unreachable'}")


def attach(settings: Settings) -> None:
    if not tmux_has(settings.webui_session):
        raise RuntimeError("open-webui is not running.")

    os.execvp("tmux", ["tmux", "attach", "-t", settings.webui_session])


def logs(settings: Settings, lines: int = 100) -> None:
    if not tmux_has(settings.webui_session):
        raise RuntimeError("open-webui is not running.")

    result = run(
        [
            "tmux",
            "capture-pane",
            "-p",
            "-t",
            settings.webui_session,
            "-S",
            f"-{lines}",
        ],
        capture=True,
    )

    print(result.stdout, end="")
