from __future__ import annotations

import os
import shlex
import time
from urllib.parse import urlsplit

from .settings import Settings
from .utils import command_exists, http_ok, run


def running(settings: Settings) -> bool:
    if not command_exists("tmux"):
        return False
    return run(
        ["tmux", "has-session", "-t", f"={settings.remote_tunnel_name}"],
        capture=True,
    ).returncode == 0


def reachable(settings: Settings) -> bool:
    return http_ok(settings.remote_ollama_url + "/api/tags")


def ssh_command(settings: Settings) -> list[str]:
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
            "AICTL_REMOTE_TUNNEL_NAME must be a nonempty tmux session name "
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
        "ssh", "-F", "/dev/null", "-N", "-T",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "ConnectTimeout=10",
        "-p", str(settings.remote_ssh_port),
        "-L", f"{local_host}:{local_port}:{remote_host}:{settings.remote_ollama_port}",
    ]
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
        print(f"remote: already reachable ({settings.remote_ollama_url})")
        return True

    if not running(settings):
        command = ssh_command(settings)
        for executable in ("ssh", "tmux"):
            if not command_exists(executable):
                raise RuntimeError(f"{executable} is required for the remote SSH tunnel.")
        # A tmux terminal preserves SSH prompts; the loop reconnects after a drop.
        script = (
            f"while true; do {shlex.join(command)}; "
            "echo 'SSH disconnected; retrying in 5 seconds...'; sleep 5; done"
        )
        result = run(
            ["tmux", "new-session", "-d", "-s", settings.remote_tunnel_name,
             shlex.join(["sh", "-c", script])],
            capture=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to start SSH tunnel.")
        print("remote: SSH tunnel starting")
    else:
        print("remote: SSH tunnel session already exists")

    for _ in range(20):
        if reachable(settings):
            print(f"remote: reachable ({settings.remote_ollama_url})")
            return True
        time.sleep(0.5)

    print("remote: tunnel session exists, but Ollama is not responding.")
    print("Inspect or complete SSH authentication: aictl tunnel attach")
    print("Detach with Ctrl-b then d; retry your command after authentication.")
    return False


def stop(settings: Settings) -> None:
    if not running(settings):
        print("remote: tunnel already stopped")
        return
    result = run(
        ["tmux", "kill-session", "-t", f"={settings.remote_tunnel_name}"],
        capture=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to stop SSH tunnel.")
    print("remote: tunnel stopped")


def status(settings: Settings) -> None:
    print(f"Tunnel tmux: {'running' if running(settings) else 'stopped'}")
    print(f"Ollama HTTP: {'reachable' if reachable(settings) else 'unreachable'}")
    print(f"Endpoint: {settings.remote_ollama_url}")
    user = settings.remote_ssh_user or "(current user)"
    host = settings.remote_ssh_host or "(not configured)"
    print(f"SSH: {user}@{host}:{settings.remote_ssh_port}")
    print(f"Forward to: {settings.remote_ollama_host}:{settings.remote_ollama_port}")


def attach(settings: Settings) -> None:
    if not running(settings):
        raise RuntimeError(
            "Remote tunnel is not running. Start it with: aictl tunnel connect"
        )
    os.execvp("tmux", ["tmux", "attach", "-t", f"={settings.remote_tunnel_name}"])
