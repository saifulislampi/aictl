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
- local hostname access through Caddy,
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
aictl backend attach local

aictl backend stop remote
aictl backend stop local

aictl tunnel connect
aictl tunnel status
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

aictl proxy setup
aictl proxy setup --apply
aictl proxy start
aictl proxy run
aictl proxy status
aictl proxy stop
```

## Requirements

The Python package itself has no third-party dependencies.

Required:

- Python 3.11+

For remote Ollama:

- OpenSSH (`ssh`)

For an aictl-managed local Ollama:

- Ollama
- `tmux`

For Open WebUI:

- `uv` / `uvx`
- `tmux`

On macOS:

```bash
brew install tmux
brew install uv
```

For the optional local hostname proxy:

- Caddy (`brew install caddy` on macOS)
- a hosts-file entry for the configured hostname
- the configured loopback address

For a remote backend, OpenSSH (`ssh`) is required. Tunnel management
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

SSH prompts for host confirmation, a password, or a key passphrase directly
in your terminal. After authentication, `aictl` reports that SSH connected and
checks whether Ollama is ready. The tunnel continues in the background while
the command returns to your shell. Open `http://127.0.0.1:8080` in your browser.

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
The command reports whether it created, preserved, or replaced the file.
The `.env` filename is hidden; it is created in `~/.config/aictl`, not in the
repository. To locate and list it:

```bash
aictl config
ls -la ~/.config/aictl
```

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

Python manages an OpenSSH background connection directly. SSH authentication
happens in your current terminal; there is no tmux window to open or detach
from. No separate `tunnel` script or `~/.ssh/config` entry is needed. All SSH
connection and forwarding options come from config or environment variables.

Set these values in `~/.config/aictl/.env` (or export them in your environment):

| Setting | Meaning | Default |
| --- | --- | --- |
| `AICTL_REMOTE_SSH_HOST` | Real SSH hostname or IP address; required to create a tunnel | empty |
| `AICTL_REMOTE_SSH_USER` | SSH login username | current local username |
| `AICTL_REMOTE_SSH_PORT` | SSH server port | `22` |
| `AICTL_REMOTE_SSH_IDENTITY_FILE` | Optional private key path | SSH default keys / agent |
| `AICTL_REMOTE_TUNNEL_NAME` | Name identifying the managed connection | `remote-llm` |
| `AICTL_REMOTE_OLLAMA_URL` | Local loopback HTTP endpoint; determines the forward's bind address and port | `http://127.0.0.1:11435` |
| `AICTL_REMOTE_OLLAMA_HOST` | Ollama host as reached from the SSH server | `127.0.0.1` |
| `AICTL_REMOTE_OLLAMA_PORT` | Ollama port on that host | `11434` |

For example, local port `11435` forwards to `127.0.0.1:11434` on the SSH server.
Use the actual address behind an old SSH alias for `AICTL_REMOTE_SSH_HOST`.
If your connection previously relied on SSH config for the username, port, or
identity file, put those values in the corresponding settings above.

```bash
aictl backend switch remote  # connects only when needed, then selects remote
aictl tunnel connect         # connects without changing the active backend
aictl tunnel status          # checks SSH connection and Ollama separately
aictl tunnel disconnect      # stops the managed background connection
```

### Authentication and connection feedback

When a new tunnel is needed, SSH prompts in your current terminal. Leave
`AICTL_REMOTE_SSH_IDENTITY_FILE` empty to use SSH's default keys, agent, or
password authentication. A password prompt appears only when SSH needs one.
If you configure a private key that requires a passphrase, its prompt appears
in the same terminal. SSH uses its normal known-hosts verification; passwords
are never stored in `.env` or handled by Python.

After successful authentication, output looks like this:

```text
remote: SSH connected; tunnel running in the background
remote: Ollama is ready
Endpoint: http://127.0.0.1:11435
Active backend: remote
Endpoint: http://127.0.0.1:11435
```

SSH backgrounding uses `-f`, which authenticates before leaving the foreground.
A control socket lets Python check and stop the connection later. See the
[OpenSSH manual](https://man.openbsd.org/ssh) for these options.

An already reachable endpoint is reused without opening a new connection.
`aictl backend switch remote` prints that it is using the existing connection.
If a managed SSH connection exists but Ollama is down, `aictl` checks the
endpoint without starting another SSH process for the tunnel. Concurrent
connect and disconnect commands are serialized by a local file lock.

Commands without an interactive terminal use SSH batch mode, so they require
keys or an agent and fail instead of waiting for a password prompt. SSH errors
remain visible. A failed connection or readiness check does not change the
selected backend.

Keepalive options detect broken connections. If the connection drops, run
`aictl tunnel connect` or `aictl backend switch remote` to reconnect. The new
background connection does not run the old tmux retry loop.

### Updating tunnel settings

A running tunnel keeps the settings it was started with. After changing the
SSH host, user, key, or forwarding settings, recreate it:

```bash
aictl tunnel disconnect
aictl backend switch remote
```

Disconnect before changing `AICTL_REMOTE_TUNNEL_NAME` or `AICTL_STATE_DIR`, so
the old connection can still be found and stopped. Control sockets live under
`AICTL_STATE_DIR/tunnels` (by default `~/.local/state/aictl/tunnels`).

### Migrating from tmux or an external tunnel helper

Remove `AICTL_REMOTE_CONNECT_COMMAND` and `AICTL_REMOTE_DISCONNECT_COMMAND`
from your `.env`; they are no longer used. Add the SSH settings from the table
above. Copy the actual hostname, username, port, and identity path from any SSH
config entry you previously used. SSH config aliases and forwarding rules are
not read by the built-in tunnel.

A working old tunnel is reused. If the endpoint is unreachable and a tmux
session with the configured `AICTL_REMOTE_TUNNEL_NAME` exists, `aictl` stops that
old session before creating the new background connection. `aictl tunnel
disconnect` can also stop an old tunnel with that session name. Tunnels with
other names must be stopped using the tool that created them.

The previous `aictl tunnel attach` and `aictl backend attach remote` commands
now show authentication guidance and status; they do not open tmux.

### Troubleshooting

| Symptom | What to check |
| --- | --- |
| SSH host is not configured | Set `AICTL_REMOTE_SSH_HOST` in your config or environment. |
| SSH is missing | Run `aictl doctor` and install OpenSSH. |
| Authentication fails | Read the SSH error in your terminal; check the username, key, and SSH port. |
| SSH connects but Ollama is unreachable | Check that remote Ollama is running and its host/port match `AICTL_REMOTE_OLLAMA_HOST` and `AICTL_REMOTE_OLLAMA_PORT`. |
| Local forwarding port is already in use | Stop the conflicting tunnel/service or choose a different port in `AICTL_REMOTE_OLLAMA_URL`. |
| Changed settings have no effect | Disconnect and recreate the tunnel. |
| Control socket path is too long | Set `AICTL_STATE_DIR` to a shorter directory path. |

`aictl tunnel status` reports the managed SSH connection and Ollama HTTP
reachability separately. A reachable endpoint alone does not mean it is
managed by `aictl`.

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

## Local hostname proxy

Use Caddy to access a local application at `http://localai` without typing its
port. The defaults match this setup:

```text
http://localai -> 127.0.0.2:80 -> http://127.0.0.1:9090
```

Configure the proxy through `~/.config/aictl/.env` or environment variables:

```dotenv
AICTL_PROXY_HOSTNAME=localai
AICTL_PROXY_BIND=127.0.0.2
AICTL_PROXY_PORT=80
AICTL_PROXY_UPSTREAM=http://127.0.0.1:9090
AICTL_PROXY_ADMIN_PORT=2020
```

`AICTL_PROXY_UPSTREAM` is independent of the Open WebUI settings. If your WebUI
runs on the default port `8080`, set it to `http://127.0.0.1:8080` instead.
The proxy hostname, bind address, and upstream are validated before generating
a configuration. The listener and upstream must use loopback addresses.

### Check installation and hostname setup

```bash
aictl proxy setup
```

This checks for Caddy first, verifies the hostname resolves to the configured
IPv4 address, and checks that the loopback address is available. If something
is missing, it prints the relevant setup instructions. On macOS these are:

```bash
brew install caddy
sudo nano /etc/hosts
```

Add this hosts-file entry, keeping existing entries and correcting any
conflicting mapping for the same hostname:

```text
127.0.0.2 localai
```

To let the tool create a missing loopback alias on macOS:

```bash
aictl proxy setup --apply
```

This runs the following command using the configured `AICTL_PROXY_BIND`, with
a visible sudo password prompt when needed:

```bash
sudo ifconfig lo0 inet 127.0.0.2 netmask 255.255.255.255 alias
```

The alias disappears after reboot, but `aictl proxy start` and `aictl proxy run`
automatically recreate it when missing on macOS. An existing alias is reused
without running sudo or ifconfig. Caddy and the hostname mapping must be ready
before the tool creates the alias. Using `127.0.0.1` for
`AICTL_PROXY_BIND` avoids needing an extra alias; update the hosts entry too.
Plain `setup` only checks readiness. `setup --apply`, `start`, and `run` can
create the loopback alias, but leave `/etc/hosts` and package installation to
the displayed instructions. An incomplete setup exits with
status 1. Other platforms receive a link to the official Caddy installation
instructions.

### Start and manage the proxy

```bash
aictl proxy start   # run Caddy in the background
aictl proxy status  # hostname, managed Caddy, proxy HTTP, and upstream HTTP
aictl proxy stop    # stop the Caddy instance managed by aictl
```

Then open `http://localai` in your browser. Start the upstream application
separately; an HTTP 502 from the proxy means it could not reach the upstream.

For the equivalent of your manual `sudo caddy run --config Caddyfile` command:

```bash
aictl proxy run
```

This runs Caddy in the foreground with logs visible; press **Ctrl-C** to stop.
Both `start` and `run` validate the generated Caddy configuration before
launching. For ports below 1024, `aictl` invokes `sudo` for Caddy when needed,
so its password prompt stays visible. Run `aictl` as your normal user to keep
its config and state paths consistent. Higher ports can run without sudo,
but must appear in the browser URL.

The generated Caddyfile lives at `~/.local/state/aictl/proxy/Caddyfile`, with
an adapted-config snapshot beside it. Your manually maintained Caddyfile is
not used or overwritten. A dedicated loopback admin API at
`127.0.0.1:2020` keeps this instance separate from Caddy's usual admin listener.
`proxy stop` verifies the running config matches the managed snapshot before
stopping it. An existing HTTP listener is reused without taking ownership;
stop a manually launched proxy using the command or terminal that started it.

After changing proxy settings, run `aictl proxy stop`, then `aictl proxy start`.
Stop before changing `AICTL_PROXY_ADMIN_PORT` or `AICTL_STATE_DIR`, so the
existing instance can still be located. If another Caddy instance uses the
configured admin port, choose a different `AICTL_PROXY_ADMIN_PORT`.

See the [Caddy installation guide](https://caddyserver.com/docs/install) and
[command-line documentation](https://caddyserver.com/docs/command-line).

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
