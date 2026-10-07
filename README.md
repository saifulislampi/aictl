# aictl

`aictl` is my small personal CLI for controlling local and remote AI backends
from one place.

I use it to keep the plumbing out of the way while experimenting with local
LLMs, chat UIs, coding agents, MCP tools, and different inference backends.

The current version focuses on:

- local Ollama,
- remote Ollama reached through an SSH tunnel,
- Open WebUI,
- tmux-managed services.

Machine-specific information is deliberately kept **outside the repository**.

## Why I built it

My development machine and my inference machine are not always the same host.

A typical setup looks like this:

```text
                          Mac
                           |
                    +------+------+
                    |    aictl    |
                    +------+------+
                           |
             +-------------+-------------+
             |                           |
        local backend               remote backend
             |                           |
      127.0.0.1:11434            127.0.0.1:11435
             |                           |
        local Ollama               SSH tunnel
                                         |
                                  remote Ollama

                           |
                     Open WebUI
                  127.0.0.1:8080
```

I want applications such as Open WebUI, coding harnesses, and future MCP/agent
tools to be able to use whichever backend I am currently testing without
repeating setup steps manually.


## Current commands

```bash
aictl status
aictl doctor

aictl backend list
aictl backend current
aictl backend status remote
aictl backend status local

aictl backend start remote
aictl backend start local

aictl backend switch remote
aictl backend switch local

aictl backend stop remote
aictl backend stop local

aictl models
aictl models --backend remote
aictl models --backend local

aictl webui start
aictl webui status
aictl webui logs
aictl webui attach
aictl webui restart
aictl webui stop
```

## Requirements

The Python package itself has no third-party dependencies.

Required:

- Python 3.11+
- `tmux`

For local Ollama:

- Ollama

For Open WebUI:

- `uv` / `uvx`

On macOS:

```bash
brew install tmux
brew install uv
```

For a remote backend, the default example assumes a separate `tunnel` helper
already exists. You can replace those commands in your local `.env`.

## Installation

Clone:

```bash
git clone <YOUR-REPOSITORY-URL>
cd aictl
```

Install as an editable `uv` tool:

```bash
uv tool install -e .
```

Verify:

```bash
aictl --version
aictl doctor
```

Uninstall:

```bash
uv tool uninstall aictl
```

## Personal configuration

Run:

```bash
aictl init
```

This creates:

```text
~/.config/aictl/.env
```

Edit it:

```bash
nano ~/.config/aictl/.env
```

Example:

```dotenv
AICTL_REMOTE_OLLAMA_URL=http://127.0.0.1:11435
AICTL_REMOTE_TUNNEL_NAME=remote-llm
AICTL_REMOTE_CONNECT_COMMAND=tunnel connect {tunnel}
AICTL_REMOTE_DISCONNECT_COMMAND=tunnel disconnect {tunnel}

AICTL_LOCAL_OLLAMA_URL=http://127.0.0.1:11434
AICTL_LOCAL_OLLAMA_SESSION=local-ollama
AICTL_LOCAL_OLLAMA_START_COMMAND=ollama serve

AICTL_WEBUI_HOST=127.0.0.1
AICTL_WEBUI_PORT=8080
AICTL_WEBUI_SESSION=open-webui
AICTL_WEBUI_DATA_DIR=~/.local-ai/open-webui
AICTL_WEBUI_PYTHON=3.11
```

The repo contains `.env.example`, but your real `.env` stays outside Git.

### Environment overrides

Process environment variables override values from the `.env`.

For example:

```bash
AICTL_WEBUI_PORT=8081 aictl webui start
```

## Remote backend

The remote backend is represented locally by a forwarded endpoint such as:

```text
http://127.0.0.1:11435
```

A separate SSH helper is responsible for creating that forward.

Example:

```bash
tunnel connect remote-llm
```

`aictl backend switch remote` will invoke the configured connect command if the
remote Ollama endpoint is not already reachable.

Interactive SSH authentication is intentionally left visible rather than
hidden by `aictl`.

## Local backend

The default local endpoint is:

```text
http://127.0.0.1:11434
```

If it is already reachable, `aictl` simply uses it.

If it is not reachable, `aictl` can start:

```bash
ollama serve
```

inside the configured tmux session.

## Switching

To use the remote backend:

```bash
aictl backend switch remote
```

To use local Ollama:

```bash
aictl backend switch local
```

If Open WebUI is already running, `aictl` restarts it so the new
`OLLAMA_BASE_URL` takes effect.

## Open WebUI

Start:

```bash
aictl webui start
```

By default:

```text
http://127.0.0.1:8080
```

Check:

```bash
aictl webui status
```

Logs:

```bash
aictl webui logs -n 200
```

Attach:

```bash
aictl webui attach
```

Stop:

```bash
aictl webui stop
```

Open WebUI data defaults to:

```text
~/.local-ai/open-webui
```

## State

The selected backend is stored at:

```text
~/.local/state/aictl/state.json
```

This is also outside the repository.

## Configuration priority

From highest to lowest:

1. process environment variables,
2. `~/.config/aictl/.env`,
3. built-in safe defaults.

## Development

Run directly from source:

```bash
PYTHONPATH=src python -m aictl --help
```

Run tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Security model

The intended default is to keep inference services bound to loopback.

```text
Mac localhost
    |
SSH tunnel
    |
remote localhost
    |
Ollama
```

This avoids exposing an unauthenticated Ollama API directly to a LAN or the
public internet.

## Roadmap

Potential future additions:

- LM Studio backend
- llama.cpp backend
- vLLM backend
- backend-specific health adapters
- model load/unload helpers
- benchmark commands
- context-length inspection
- GPU/RAM monitoring
- MCP service management
- coding-harness launch helpers
- structured experiment output

The goal is to grow the tool only when a real workflow needs the feature.

## Status

Early personal-tool / learning-project release. Expect the interface to evolve.
