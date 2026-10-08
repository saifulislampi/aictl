\
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path(
    os.environ.get("AICTL_CONFIG_DIR", Path.home() / ".config" / "aictl")
).expanduser()

ENV_FILE = Path(
    os.environ.get("AICTL_ENV_FILE", CONFIG_DIR / ".env")
).expanduser()

STATE_DIR = Path(
    os.environ.get("AICTL_STATE_DIR", Path.home() / ".local" / "state" / "aictl")
).expanduser()

STATE_FILE = STATE_DIR / "state.json"

DEFAULT_ENV = """\
# aictl personal configuration

AICTL_REMOTE_OLLAMA_URL=http://127.0.0.1:11435
# Name identifying the managed SSH connection.
AICTL_REMOTE_TUNNEL_NAME=remote-llm
# Use a real hostname/IP; SSH config aliases are not used.
AICTL_REMOTE_SSH_HOST=
AICTL_REMOTE_SSH_USER=
AICTL_REMOTE_SSH_PORT=22
AICTL_REMOTE_SSH_IDENTITY_FILE=
AICTL_REMOTE_OLLAMA_HOST=127.0.0.1
AICTL_REMOTE_OLLAMA_PORT=11434

AICTL_LOCAL_OLLAMA_URL=http://127.0.0.1:11434
AICTL_LOCAL_OLLAMA_SESSION=local-ollama
AICTL_LOCAL_OLLAMA_START_COMMAND=ollama serve

AICTL_WEBUI_HOST=127.0.0.1
AICTL_WEBUI_PORT=8080
AICTL_WEBUI_SESSION=open-webui
AICTL_WEBUI_DATA_DIR=~/.local-ai/open-webui
AICTL_WEBUI_PYTHON=3.11

# Local hostname proxy (HTTP, accessible only on this machine).
AICTL_PROXY_HOSTNAME=localai
AICTL_PROXY_BIND=127.0.0.2
AICTL_PROXY_PORT=80
AICTL_PROXY_UPSTREAM=http://127.0.0.1:9090
AICTL_PROXY_ADMIN_PORT=2020
"""


def parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}

    if not path.exists():
        return values

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[7:].strip()

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        values[key] = value

    return values


def env_value(values: dict[str, str], key: str, default: str) -> str:
    return os.environ.get(key, values.get(key, default))


def command_from_string(value: str, **replacements: str) -> list[str]:
    return shlex.split(value.format(**replacements))


@dataclass(frozen=True)
class Settings:
    remote_ollama_url: str
    remote_tunnel_name: str
    local_ollama_url: str
    local_ollama_session: str
    local_ollama_start_command: list[str]
    webui_host: str
    webui_port: int
    webui_session: str
    webui_data_dir: Path
    webui_python: str
    remote_ssh_host: str = ""
    remote_ssh_user: str = ""
    remote_ssh_port: int = 22
    remote_ssh_identity_file: Path | None = None
    remote_ollama_host: str = "127.0.0.1"
    remote_ollama_port: int = 11434
    proxy_hostname: str = "localai"
    proxy_bind: str = "127.0.0.2"
    proxy_port: int = 80
    proxy_upstream: str = "http://127.0.0.1:9090"
    proxy_admin_port: int = 2020


def load_settings() -> Settings:
    values = parse_dotenv(ENV_FILE)

    tunnel = env_value(values, "AICTL_REMOTE_TUNNEL_NAME", "remote-llm")
    identity = env_value(values, "AICTL_REMOTE_SSH_IDENTITY_FILE", "")

    return Settings(
        remote_ollama_url=env_value(
            values, "AICTL_REMOTE_OLLAMA_URL", "http://127.0.0.1:11435"
        ).rstrip("/"),
        remote_tunnel_name=tunnel,
        remote_ssh_host=env_value(values, "AICTL_REMOTE_SSH_HOST", ""),
        remote_ssh_user=env_value(values, "AICTL_REMOTE_SSH_USER", ""),
        remote_ssh_port=int(env_value(values, "AICTL_REMOTE_SSH_PORT", "22")),
        remote_ssh_identity_file=(
            Path(identity).expanduser() if identity else None
        ),
        remote_ollama_host=env_value(values, "AICTL_REMOTE_OLLAMA_HOST", "127.0.0.1"),
        remote_ollama_port=int(env_value(values, "AICTL_REMOTE_OLLAMA_PORT", "11434")),
        local_ollama_url=env_value(
            values, "AICTL_LOCAL_OLLAMA_URL", "http://127.0.0.1:11434"
        ).rstrip("/"),
        local_ollama_session=env_value(
            values, "AICTL_LOCAL_OLLAMA_SESSION", "local-ollama"
        ),
        local_ollama_start_command=command_from_string(
            env_value(
                values,
                "AICTL_LOCAL_OLLAMA_START_COMMAND",
                "ollama serve",
            )
        ),
        webui_host=env_value(values, "AICTL_WEBUI_HOST", "127.0.0.1"),
        webui_port=int(env_value(values, "AICTL_WEBUI_PORT", "8080")),
        webui_session=env_value(
            values, "AICTL_WEBUI_SESSION", "open-webui"
        ),
        webui_data_dir=Path(
            env_value(
                values,
                "AICTL_WEBUI_DATA_DIR",
                "~/.local-ai/open-webui",
            )
        ).expanduser(),
        webui_python=env_value(values, "AICTL_WEBUI_PYTHON", "3.11"),
        proxy_hostname=env_value(values, "AICTL_PROXY_HOSTNAME", "localai"),
        proxy_bind=env_value(values, "AICTL_PROXY_BIND", "127.0.0.2"),
        proxy_port=int(env_value(values, "AICTL_PROXY_PORT", "80")),
        proxy_upstream=env_value(
            values, "AICTL_PROXY_UPSTREAM", "http://127.0.0.1:9090"
        ).rstrip("/"),
        proxy_admin_port=int(env_value(values, "AICTL_PROXY_ADMIN_PORT", "2020")),
    )


def init_user_config(force: bool = False) -> Path:
    if ENV_FILE.exists() and not force:
        return ENV_FILE

    try:
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        ENV_FILE.write_text(DEFAULT_ENV)
    except OSError as exc:
        raise RuntimeError(f"Could not create config at {ENV_FILE}: {exc}") from exc
    return ENV_FILE
