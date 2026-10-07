\
from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def tmux_has(session: str) -> bool:
    if not command_exists("tmux"):
        return False
    return run(["tmux", "has-session", "-t", session], capture=True).returncode == 0


def http_ok(url: str, timeout: float = 2.0) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": "aictl/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


def http_json(url: str, timeout: float = 3.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "aictl/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"
