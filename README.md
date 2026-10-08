# aictl

`aictl` is my small personal CLI for controlling local and remote AI backends
from one place.

I use it to keep the plumbing out of the way while experimenting with local
LLMs, chat UIs, coding agents, MCP tools, and different inference backends.

The current version focuses on:

- local Ollama,
- remote Ollama reached through an SSH tunnel,
- built-in SSH tunnel management configured through `.env` or environment variables,
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
aictl init
aictl config
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

aictl backend use remote
aictl backend attach remote
aictl backend attach local

aictl backend stop remote
aictl backend stop local

aictl tunnel connect
aictl tunnel status
aictl tunnel attach
aictl tunnel disconnect

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

For a remote backend, OpenSSH (`ssh`) and tmux are required. Tunnel management
is built in; configure the connection in your `.env`.
The remote machine must already run Ollama and allow SSH access. `aictl` manages
the local tunnel; it does not install or start Ollama on the remote machine.

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

## Quick start with remote Ollama

After installation, create and edit your configuration:

```bash
aictl init
nano ~/.config/aictl/.env
```

Set `AICTL_REMOTE_SSH_HOST` to your server's actual hostname or IP and
`AICTL_REMOTE_SSH_USER` to your login username. Set
`AICTL_REMOTE_SSH_IDENTITY_FILE` if you use a specific private key, or leave it
empty to use SSH's default keys or agent. The default forwarding settings assume
Ollama is listening on `127.0.0.1:11434` on that server.

Then connect, select the backend, and start the UI:

```bash
aictl doctor
aictl backend switch remote
aictl models
aictl webui start
```

Open `http://127.0.0.1:8080` in your browser. If the switch reports that the
endpoint is not responding, use `aictl tunnel attach` to inspect SSH output or
complete authentication, detach with **Ctrl-b, then d**, and retry the switch.

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
AICTL_REMOTE_SSH_HOST=your-server.example.com
AICTL_REMOTE_SSH_USER=your-username
AICTL_REMOTE_SSH_PORT=22
AICTL_REMOTE_SSH_IDENTITY_FILE=~/.ssh/id_ed25519
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
```

The repo contains `.env.example`, but your real `.env` stays outside Git.
`aictl init` preserves an existing configuration. `aictl init --force` replaces
it with the default template, so edit an existing file to keep your settings.

### Environment overrides

Process environment variables override values from the `.env`.

For example:

```bash
AICTL_WEBUI_PORT=8081 aictl webui start
```

You can also supply SSH settings through the environment:

```bash
export AICTL_REMOTE_SSH_HOST=your-server.example.com
export AICTL_REMOTE_SSH_USER=your-username
aictl backend switch remote
```

To customize where configuration and state live, set `AICTL_CONFIG_DIR`,
`AICTL_ENV_FILE`, or `AICTL_STATE_DIR`. `aictl config` prints the resolved config
and state file paths.

## Remote backend

`aictl` creates and manages the SSH tunnel directly. No separate `tunnel`
script or `~/.ssh/config` entry is needed. It invokes `ssh -F /dev/null` with
explicit connection and forwarding options.

Set these values in `~/.config/aictl/.env` (or export them in your environment):

| Setting | Meaning | Default |
| --- | --- | --- |
| `AICTL_REMOTE_SSH_HOST` | Real SSH hostname or IP address; required to create a tunnel | empty |
| `AICTL_REMOTE_SSH_USER` | SSH login username | current local username |
| `AICTL_REMOTE_SSH_PORT` | SSH server port | `22` |
| `AICTL_REMOTE_SSH_IDENTITY_FILE` | Optional private key path | SSH default keys / agent |
| `AICTL_REMOTE_TUNNEL_NAME` | tmux session name | `remote-llm` |
| `AICTL_REMOTE_OLLAMA_URL` | Local loopback HTTP endpoint; determines the forward's bind address and port | `http://127.0.0.1:11435` |
| `AICTL_REMOTE_OLLAMA_HOST` | Ollama host as reached from the SSH server | `127.0.0.1` |
| `AICTL_REMOTE_OLLAMA_PORT` | Ollama port on that host | `11434` |

For example, local port `11435` forwards to `127.0.0.1:11434` on the SSH server.
Use the actual address behind an old SSH alias for `AICTL_REMOTE_SSH_HOST`.
If your connection previously relied on SSH config for the username, port, or
identity file, put those values in the corresponding settings above.

```bash
aictl backend switch remote  # creates the tunnel if the endpoint is unreachable
aictl tunnel connect         # starts the tunnel without changing active backend
aictl tunnel status          # shows tmux session and endpoint health separately
aictl tunnel attach          # inspect SSH output or answer authentication prompts
aictl tunnel disconnect      # stops the managed tmux session and its SSH tunnel
```

An existing reachable endpoint is reused. If the endpoint is down but the tmux
session exists, `aictl` waits for it rather than creating a duplicate session.
The session retries SSH every five seconds after disconnection; keepalive
options detect broken connections, and forwarding failures cause SSH to exit.
A failed readiness check leaves the session available for inspection and does
not change the selected backend.

For a first connection or interactive authentication, run `aictl tunnel attach`
to confirm the host or enter your password/key passphrase. Detach with **Ctrl-b,
then d**, and retry `aictl backend switch remote`. SSH uses its normal known-hosts
verification. Passwords are entered in the SSH terminal, not stored in `.env`.

### Updating tunnel settings

A running tunnel keeps the settings it was started with. After changing the
SSH host, user, key, or forwarding settings, recreate it:

```bash
aictl tunnel disconnect
aictl backend switch remote
```

Disconnect before changing `AICTL_REMOTE_TUNNEL_NAME`, so the old session can
still be found and stopped.

### Migrating from the external tunnel helper

Remove `AICTL_REMOTE_CONNECT_COMMAND` and `AICTL_REMOTE_DISCONNECT_COMMAND`
from your `.env`; they are no longer used. Add the SSH settings from the table
above. Copy the actual hostname, username, port, and identity path from any SSH
config entry you previously used. SSH config aliases and forwarding rules are
not read by the built-in tunnel.

Stop any tunnel started by the old helper before creating the replacement.
If it used the same session name configured in `AICTL_REMOTE_TUNNEL_NAME`,
`aictl tunnel disconnect` can stop it. Then run `aictl backend switch remote`.

### Troubleshooting

| Symptom | What to check |
| --- | --- |
| SSH host is not configured | Set `AICTL_REMOTE_SSH_HOST` in your config or environment. |
| SSH or tmux is missing | Run `aictl doctor` and install the missing command. |
| Tunnel session runs but Ollama is unreachable | Run `aictl tunnel attach`; complete authentication or inspect the SSH error. Check that remote Ollama is running and its host/port match your settings. |
| Local forwarding port is already in use | Stop the conflicting tunnel/service or choose a different port in `AICTL_REMOTE_OLLAMA_URL`. |
| Changed settings have no effect | Disconnect and recreate the tunnel. |

`aictl tunnel status` reports tmux session state and Ollama HTTP reachability
separately. A reachable endpoint alone does not mean it is managed by `aictl`.

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

`backend start` starts a backend without selecting it. `backend use` saves the
selection without starting it or restarting Open WebUI. Use `backend switch`
for the complete workflow. Switching to local does not stop the remote tunnel;
run `aictl tunnel disconnect` when you want to close it.

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
