from __future__ import annotations

import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from .settings import STATE_DIR, Settings
from .utils import run


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def url(settings: Settings) -> str:
    port = "" if settings.proxy_port == 80 else f":{settings.proxy_port}"
    return f"http://{settings.proxy_hostname}{port}"


def admin_address(settings: Settings) -> str:
    return f"127.0.0.1:{settings.proxy_admin_port}"


def validate(settings: Settings) -> None:
    hostname = settings.proxy_hostname
    if len(hostname) > 253 or not all(
        re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
        for label in hostname.split(".")
    ):
        raise ValueError(
            "AICTL_PROXY_HOSTNAME must be a hostname, such as localai or ai.test."
        )
    bind = ipaddress.ip_address(settings.proxy_bind)
    if bind.version != 4 or not bind.is_loopback:
        raise ValueError(
            "AICTL_PROXY_BIND must be an IPv4 loopback address, such as 127.0.0.2."
        )
    for name, port in (
        ("AICTL_PROXY_PORT", settings.proxy_port),
        ("AICTL_PROXY_ADMIN_PORT", settings.proxy_admin_port),
    ):
        if not 1 <= port <= 65535:
            raise ValueError(f"{name} must be between 1 and 65535.")
    if settings.proxy_bind == "127.0.0.1" and settings.proxy_port == settings.proxy_admin_port:
        raise ValueError("Proxy and Caddy admin API must use different ports.")
    upstream = urlsplit(settings.proxy_upstream)
    if (
        upstream.scheme != "http"
        or not upstream.hostname
        or upstream.username is not None
        or upstream.password is not None
        or upstream.path not in {"", "/"}
        or upstream.query
        or upstream.fragment
        or any(c.isspace() or c in '{}"#\\' for c in settings.proxy_upstream)
    ):
        raise ValueError(
            "AICTL_PROXY_UPSTREAM must be a local HTTP URL without a path, "
            "such as http://127.0.0.1:9090."
        )
    try:
        local = ipaddress.ip_address(upstream.hostname).is_loopback
    except ValueError:
        local = upstream.hostname == "localhost"
    if not local or not 1 <= (upstream.port or 80) <= 65535:
        raise ValueError("AICTL_PROXY_UPSTREAM must point to a loopback HTTP endpoint.")
    same_host = upstream.hostname in {hostname, settings.proxy_bind} or (
        upstream.hostname == "localhost" and settings.proxy_bind == "127.0.0.1"
    )
    if same_host and (upstream.port or 80) == settings.proxy_port:
        raise ValueError("Proxy upstream must not point back to the proxy itself.")


def caddyfile(settings: Settings) -> str:
    validate(settings)
    return (
        "{\n"
        f"\tadmin {admin_address(settings)}\n"
        "}\n\n"
        f"{url(settings)} {{\n"
        f"\tbind {settings.proxy_bind}\n"
        f"\treverse_proxy {settings.proxy_upstream}\n"
        "}\n"
    )


def resolved_addresses(settings: Settings) -> set[str]:
    try:
        return {
            entry[4][0]
            for entry in socket.getaddrinfo(settings.proxy_hostname, None, socket.AF_INET)
        }
    except socket.gaierror:
        return set()


def bind_available(settings: Settings) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((settings.proxy_bind, 0))
        return True
    except OSError:
        return False


def install_instructions() -> None:
    print("Caddy is not installed or is not in PATH.")
    if platform.system() == "Darwin":
        print("Install on macOS: brew install caddy")
    else:
        print("Install Caddy for your system: https://caddyserver.com/docs/install")
    print("Then rerun: aictl proxy setup")


def ensure_loopback(settings: Settings) -> None:
    validate(settings)
    if bind_available(settings):
        return
    if platform.system() != "Darwin":
        raise RuntimeError(
            "Automatic loopback alias setup is supported on macOS; "
            "configure the address on your system's loopback interface."
        )
    executable = shutil.which("ifconfig")
    if not executable and Path("/sbin/ifconfig").is_file():
        executable = "/sbin/ifconfig"
    if not executable:
        raise RuntimeError("ifconfig is required to create the loopback alias.")
    command = [
        executable, "lo0", "inet", settings.proxy_bind,
        "netmask", "255.255.255.255", "alias",
    ]
    if os.geteuid() != 0:
        if not shutil.which("sudo"):
            raise RuntimeError("sudo is required to create the loopback alias.")
        command.insert(0, "sudo")
    print(f"Creating loopback alias: {settings.proxy_bind}", flush=True)
    result = run(command)
    if result.returncode != 0:
        raise RuntimeError("Could not create the loopback alias; see ifconfig output above.")
    if not bind_available(settings):
        raise RuntimeError(f"Loopback alias {settings.proxy_bind} is still unavailable.")
    print(f"Loopback alias: {settings.proxy_bind} (created)")


def setup(settings: Settings, *, apply: bool = False) -> bool:
    caddy = shutil.which("caddy")
    if caddy:
        print(f"Caddy: {caddy}")
    else:
        install_instructions()
    validate(settings)

    addresses = resolved_addresses(settings)
    # All IPv4 answers must reach the intended listener, not an unrelated host.
    hosts_ok = addresses == {settings.proxy_bind}
    if hosts_ok:
        print(f"Hostname: {settings.proxy_hostname} -> {settings.proxy_bind} (ready)")
    else:
        actual = ", ".join(sorted(addresses)) or "not found"
        print(f"Hostname: {settings.proxy_hostname} -> {actual}")
        print("Edit /etc/hosts: sudo nano /etc/hosts")
        print(f"Add or correct this entry: {settings.proxy_bind} {settings.proxy_hostname}")

    bind_ok = bind_available(settings)
    if not bind_ok and apply and caddy and hosts_ok and platform.system() == "Darwin":
        ensure_loopback(settings)
        bind_ok = True
    if bind_ok:
        print(f"Loopback: {settings.proxy_bind} (ready)")
    else:
        print(f"Loopback: {settings.proxy_bind} is not available")
        if platform.system() == "Darwin":
            print("Create it with: aictl proxy setup --apply")
            print(
                "Add it on macOS: sudo ifconfig lo0 inet "
                f"{settings.proxy_bind} netmask 255.255.255.255 alias"
            )
            print("After a reboot, aictl proxy start recreates a missing alias automatically.")
        else:
            print(
                "Configure this address on your loopback interface, "
                "or use AICTL_PROXY_BIND=127.0.0.1."
            )
    print(f"URL: {url(settings)}")
    print(f"Upstream: {settings.proxy_upstream}")
    ready = bool(caddy and hosts_ok and bind_ok)
    print("Setup: ready" if ready else "Setup: incomplete; follow the instructions above")
    return ready


def opener():
    # These requests are local, regardless of HTTP_PROXY or browser settings.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def http_status(target: str) -> int | None:
    try:
        with opener().open(target, timeout=2) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None


def admin_config(settings: Settings) -> dict | None:
    try:
        with opener().open(f"http://{admin_address(settings)}/config/", timeout=1) as response:
            value = json.load(response)
        return value if isinstance(value, dict) else None
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError):
        return None


def paths() -> tuple[Path, Path]:
    directory = STATE_DIR / "proxy"
    return directory / "Caddyfile", directory / "config.json"


def managed(config: dict | None) -> bool:
    if config is None:
        return False
    _, snapshot = paths()
    try:
        return config == json.loads(snapshot.read_text())
    except (OSError, ValueError):
        return False


def require_caddy() -> str:
    executable = shutil.which("caddy")
    if not executable:
        install_instructions()
        raise RuntimeError("Caddy is required for the local proxy.")
    return executable


def start(settings: Settings, *, foreground: bool = False) -> bool:
    if not setup(settings, apply=True):
        return False
    executable = require_caddy()

    active = admin_config(settings)
    if active is not None:
        if not managed(active):
            raise RuntimeError(
                f"Another Caddy instance uses {admin_address(settings)}; "
                "choose a different AICTL_PROXY_ADMIN_PORT."
            )
        config_path, _ = paths()
        try:
            unchanged = config_path.read_text() == caddyfile(settings)
        except OSError:
            unchanged = False
        if not unchanged:
            raise RuntimeError(
                "Proxy settings changed; run aictl proxy stop, then aictl proxy start."
            )
        print("proxy: already running; using the existing proxy")
        print(f"URL: {url(settings)}")
        return True
    code = http_status(url(settings))
    if code is not None:
        print(f"proxy: existing HTTP listener responds (HTTP {code}); leaving it running")
        print(f"URL: {url(settings)}")
        return True

    config_path, snapshot = paths()
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(caddyfile(settings))
        result = run(
            [
                executable, "adapt", "--config", str(config_path),
                "--adapter", "caddyfile", "--validate",
            ],
            capture=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Caddy rejected the proxy configuration.")
        expected = json.loads(result.stdout)
        snapshot.write_text(json.dumps(expected, indent=2) + "\n")
    except OSError as exc:
        raise RuntimeError(f"Could not write proxy config at {config_path}: {exc}") from exc

    command = [
        executable, "run" if foreground else "start", "--config", str(config_path),
        "--adapter", "caddyfile",
    ]
    if settings.proxy_port < 1024 and os.geteuid() != 0:
        if not shutil.which("sudo"):
            raise RuntimeError(
                "sudo is required to listen on a privileged port; "
                "use AICTL_PROXY_PORT=8081 instead."
            )
        command.insert(0, "sudo")
        print("Port below 1024: sudo may ask for your password.", flush=True)
    action = "running in the foreground (Ctrl-C to stop)" if foreground else "starting"
    print(f"proxy: {action}", flush=True)
    print(f"URL: {url(settings)}", flush=True)
    print(f"Upstream: {settings.proxy_upstream}", flush=True)
    result = run(command)
    if result.returncode != 0:
        raise RuntimeError("Caddy did not start successfully; see its output above.")
    if not foreground:
        print("proxy: Caddy started in the background")
        code = http_status(url(settings))
        if code is None:
            print("Proxy HTTP: not responding yet; check aictl proxy status")
        elif code == 502:
            print("Proxy HTTP: HTTP 502; start or check the upstream application")
        else:
            print(f"Proxy HTTP: HTTP {code}")
    return True


def stop(settings: Settings) -> None:
    executable = require_caddy()
    validate(settings)
    active = admin_config(settings)
    if active is None:
        print("proxy: managed Caddy is already stopped")
        return
    if not managed(active):
        raise RuntimeError("This Caddy instance was not started by aictl; leaving it running.")
    result = run([executable, "stop", "--address", admin_address(settings)], capture=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to stop the managed proxy.")
    print("proxy: stopped")


def status(settings: Settings) -> None:
    validate(settings)
    executable = shutil.which("caddy")
    print(f"Caddy: {executable or 'NOT FOUND (run aictl proxy setup)'}")
    addresses = resolved_addresses(settings)
    print(f"Hostname: {settings.proxy_hostname} -> {', '.join(sorted(addresses)) or 'not found'}")
    active = admin_config(settings)
    state = "running" if managed(active) else "stopped" if active is None else "another Caddy instance"
    print(f"Managed proxy: {state}")
    for label, target in (("Proxy HTTP", url(settings)), ("Upstream HTTP", settings.proxy_upstream)):
        code = http_status(target)
        print(f"{label}: {'unreachable' if code is None else f'HTTP {code}'}")
    print(f"URL: {url(settings)}")
    print(f"Upstream: {settings.proxy_upstream}")
