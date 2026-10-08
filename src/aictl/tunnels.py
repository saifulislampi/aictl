from __future__ import annotations

import fcntl
import hashlib
import sys
import time
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

from .settings import STATE_DIR, Settings
from .utils import command_exists, http_ok, run


def control_path(settings: Settings) -> Path:
    name = hashlib.sha256(settings.remote_tunnel_name.encode()).hexdigest()[:16]
    path = STATE_DIR / "tunnels" / f"{name}.sock"
    if len(str(path).encode()) > 100:
        raise ValueError(
            "SSH control socket path is too long; "
            "set AICTL_STATE_DIR to a shorter path."
        )
    return path


def control_command(settings: Settings, action: str) -> list[str]:
    # -O sends a local socket request; this placeholder host is never contacted.
    return [
        "ssh", "-F", "/dev/null", "-S", str(control_path(settings)),
        "-O", action, "aictl-tunnel",
    ]


def running(settings: Settings) -> bool:
    if not command_exists("ssh") or not control_path(settings).exists():
        return False
    return run(control_command(settings, "check"), capture=True).returncode == 0


def legacy_running(settings: Settings) -> bool:
    if not command_exists("tmux"):
        return False
    return run(
        ["tmux", "has-session", "-t", f"={settings.remote_tunnel_name}"],
        capture=True,
    ).returncode == 0


@contextmanager
def tunnel_lock(settings: Settings) -> Iterator[None]:
    path = control_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.with_suffix(".lock").open("a") as lock:
            # Serialize connect/disconnect, including interactive authentication.
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("remote: waiting for another tunnel command to finish", flush=True)
                fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    except OSError as exc:
        raise RuntimeError(f"Could not manage SSH tunnel at {path}: {exc}") from exc


def reachable(settings: Settings) -> bool:
    return http_ok(settings.remote_ollama_url + "/api/tags")


def ssh_command(settings: Settings, *, interactive: bool = True) -> list[str]:
    host = settings.remote_ssh_host
    if not host or host.startswith("-") or any(c.isspace() for c in host):
        raise ValueError(
            "Set AICTL_REMOTE_SSH_HOST to a real SSH hostname or IP address."
        )
    if not settings.remote_ollama_host or any(
        c.isspace() for c in settings.remote_ollama_host
    ):
        raise ValueError("AICTL_REMOTE_OLLAMA_HOST must be a hostname or IP address.")
    if not settings.remote_tunnel_name or any(
        c in settings.remote_tunnel_name for c in ":.\n"
    ):
        raise ValueError(
            "AICTL_REMOTE_TUNNEL_NAME must be a nonempty tunnel name "
            "without dots or colons."
        )
    for name, port in (
        ("AICTL_REMOTE_SSH_PORT", settings.remote_ssh_port),
        ("AICTL_REMOTE_OLLAMA_PORT", settings.remote_ollama_port),
    ):
        if not 1 <= port <= 65535:
            raise ValueError(f"{name} must be between 1 and 65535.")

    endpoint = urlsplit(settings.remote_ollama_url)
    if (
        endpoint.scheme != "http"
        or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.path not in {"", "/"}
        or endpoint.query
        or endpoint.fragment
    ):
        raise ValueError(
            "AICTL_REMOTE_OLLAMA_URL must be a loopback HTTP URL, "
            "such as http://127.0.0.1:11435."
        )
    local_host = endpoint.hostname
    local_port = endpoint.port or 80
    if not 1 <= local_port <= 65535:
        raise ValueError("AICTL_REMOTE_OLLAMA_URL must have a valid port.")
    remote_host = settings.remote_ollama_host
    if ":" in remote_host and not remote_host.startswith("["):
        remote_host = f"[{remote_host}]"
    if ":" in local_host:
        local_host = f"[{local_host}]"

    command = [
        "ssh", "-F", "/dev/null", "-N", "-T", "-f", "-M",
        "-S", str(control_path(settings)),
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "ConnectTimeout=10",
        "-p", str(settings.remote_ssh_port),
        "-L", f"{local_host}:{local_port}:{remote_host}:{settings.remote_ollama_port}",
    ]
    if not interactive:
        command.extend(["-o", "BatchMode=yes"])
    if settings.remote_ssh_user:
        command.extend(["-l", settings.remote_ssh_user])
    if settings.remote_ssh_identity_file:
        command.extend([
            "-i", str(settings.remote_ssh_identity_file), "-o", "IdentitiesOnly=yes",
        ])
    command.append(host)
    return command


def start(settings: Settings) -> bool:
    if reachable(settings):
        print(
            "remote: already reachable; using the existing connection "
            f"({settings.remote_ollama_url})"
        )
        return True
    if not command_exists("ssh"):
        raise RuntimeError("ssh is required for the remote SSH tunnel.")

    with tunnel_lock(settings):
        # Another command may have connected while we were waiting for the lock.
        if reachable(settings):
            print(
                "remote: already reachable; using the existing connection "
                f"({settings.remote_ollama_url})"
            )
            return True
        if running(settings):
            print("remote: SSH tunnel already running; checking Ollama")
        else:
            command = ssh_command(settings, interactive=sys.stdin.isatty())
            if legacy_running(settings):
                print("remote: replacing the unresponsive tmux tunnel")
                _stop_legacy(settings)
            # A dead master may leave a socket behind. Under the lock it is safe
            # to remove it before starting a replacement with the same name.
            control_path(settings).unlink(missing_ok=True)
            print("remote: connecting SSH tunnel", flush=True)
            if sys.stdin.isatty():
                print(
                    "Answer SSH prompts here; the tunnel will continue in the background.",
                    flush=True,
                )
            # OpenSSH authenticates on this terminal, then -f backgrounds the
            # connection. Keeping stdio inherited makes prompts/errors visible.
            result = run(command)
            if result.returncode != 0:
                print(
                    f"remote: SSH connection failed (exit {result.returncode}); "
                    "see SSH output above."
                )
                return False
            print("remote: SSH connected; tunnel running in the background", flush=True)

        for _ in range(20):
            if reachable(settings):
                print("remote: Ollama is ready")
                print(f"Endpoint: {settings.remote_ollama_url}")
                return True
            time.sleep(0.5)

        if running(settings):
            print("remote: SSH tunnel is running, but Ollama is not responding.")
            print("Check Ollama on the remote server and AICTL_REMOTE_OLLAMA_HOST/PORT.")
        else:
            print("remote: SSH tunnel disconnected before Ollama became reachable.")
            print("Retry: aictl tunnel connect")
        return False


def _stop_legacy(settings: Settings) -> None:
    result = run(
        ["tmux", "kill-session", "-t", f"={settings.remote_tunnel_name}"],
        capture=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to stop the old tmux tunnel.")


def stop(settings: Settings) -> None:
    with tunnel_lock(settings):
        stopped = False
        if running(settings):
            result = run(control_command(settings, "exit"), capture=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "Failed to stop SSH tunnel.")
            stopped = True
        if legacy_running(settings):
            _stop_legacy(settings)
            stopped = True
        print("remote: tunnel stopped" if stopped else "remote: tunnel already stopped")


def status(settings: Settings) -> None:
    managed = running(settings)
    legacy = legacy_running(settings)
    print(f"SSH tunnel: {'running' if managed else 'stopped'}")
    if legacy:
        print("Legacy tmux tunnel: running")
    print(f"Ollama HTTP: {'reachable' if reachable(settings) else 'unreachable'}")
    print(f"Endpoint: {settings.remote_ollama_url}")
    user = settings.remote_ssh_user or "(current user)"
    host = settings.remote_ssh_host or "(not configured)"
    print(f"SSH: {user}@{host}:{settings.remote_ssh_port}")
    print(f"Forward to: {settings.remote_ollama_host}:{settings.remote_ollama_port}")


def attach(settings: Settings) -> None:
    # Preserve the old command as a diagnostic; authentication now happens
    # during connect and there is no tmux terminal to attach to.
    print("SSH authentication happens in your terminal during: aictl tunnel connect")
    status(settings)
