\
from __future__ import annotations

import argparse
import shutil
import sys

from . import __version__
from . import backends, tunnels, webui
from .backends import BackendError
from .settings import ENV_FILE, STATE_FILE, init_user_config, load_settings
from .state import active_backend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aictl",
        description="Personal control plane for local/remote AI backends and services.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Create ~/.config/aictl/.env")
    init_p.add_argument("--force", action="store_true")

    sub.add_parser("status", help="Show overall status")
    sub.add_parser("doctor", help="Check dependencies")
    sub.add_parser("config", help="Show config/state paths")

    backend_p = sub.add_parser("backend", help="Manage inference backends")
    backend_sub = backend_p.add_subparsers(dest="backend_command", required=True)

    backend_sub.add_parser("list")
    backend_sub.add_parser("current")

    p = backend_sub.add_parser("status")
    p.add_argument("name", nargs="?")

    for action in ("use", "switch", "start", "stop", "attach"):
        p = backend_sub.add_parser(action)
        p.add_argument("name")

    tunnel_p = sub.add_parser("tunnel", help="Manage the built-in remote SSH tunnel")
    tunnel_sub = tunnel_p.add_subparsers(dest="tunnel_command", required=True)
    for action in ("connect", "disconnect", "status", "attach"):
        tunnel_sub.add_parser(action)

    models_p = sub.add_parser("models", help="List models on a backend")
    models_p.add_argument("--backend", choices=["local", "remote"])

    webui_p = sub.add_parser("webui", help="Manage Open WebUI")
    webui_sub = webui_p.add_subparsers(dest="webui_command", required=True)

    for action in ("start", "stop", "restart", "status", "attach"):
        webui_sub.add_parser(action)

    logs_p = webui_sub.add_parser("logs")
    logs_p.add_argument("-n", "--lines", type=int, default=100)

    return parser


def cmd_doctor(settings) -> None:
    print("Commands:")
    for command in ("python3", "tmux", "uvx", "ssh", "ollama"):
        path = shutil.which(command)
        print(f"  {command:<10} {path or 'NOT FOUND'}")

    print("\nBackends:")
    backends.list_backends(settings)

    print("\nRemote SSH:")
    print(f"  Host: {settings.remote_ssh_host or 'NOT CONFIGURED (AICTL_REMOTE_SSH_HOST)'}")
    print(f"  Port: {settings.remote_ssh_port}")

    print(f"\nConfig: {ENV_FILE}")
    print(f"State:  {STATE_FILE}")


def cmd_status(settings) -> None:
    print(f"Active backend: {active_backend()}")
    backends.status(settings)
    print()
    webui.status(settings)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "init":
            existed = ENV_FILE.exists()
            path = init_user_config(force=args.force)
            if existed and not args.force:
                print(f"Config already exists; kept unchanged: {path}")
            elif existed:
                print(f"Replaced config: {path}")
            else:
                print(f"Created config: {path}")
            print("Edit this file to set your tunnel name, ports, and local paths.")
            return 0

        settings = load_settings()

        if args.command == "status":
            cmd_status(settings)

        elif args.command == "doctor":
            cmd_doctor(settings)

        elif args.command == "config":
            print(f"Config: {ENV_FILE}")
            print(f"State:  {STATE_FILE}")

        elif args.command == "models":
            backends.list_models(settings, args.backend)

        elif args.command == "tunnel":
            action = args.tunnel_command
            if action == "connect":
                if not tunnels.start(settings):
                    return 1
            elif action == "disconnect":
                tunnels.stop(settings)
            elif action == "status":
                tunnels.status(settings)
            elif action == "attach":
                tunnels.attach(settings)

        elif args.command == "backend":
            action = args.backend_command

            if action == "list":
                backends.list_backends(settings)
            elif action == "current":
                print(active_backend())
            elif action == "status":
                backends.status(settings, args.name)
            elif action == "use":
                backends.use(settings, args.name)
            elif action == "switch":
                was_running = webui.running(settings)

                if not backends.switch(settings, args.name):
                    return 1

                if was_running:
                    print("Restarting Open WebUI to apply the backend change...")
                    webui.restart(load_settings())
            elif action == "start":
                if not backends.start(settings, args.name):
                    return 1
            elif action == "stop":
                backends.stop(settings, args.name)
            elif action == "attach":
                backends.attach(settings, args.name)

        elif args.command == "webui":
            action = args.webui_command

            if action == "start":
                webui.start(settings)
            elif action == "stop":
                webui.stop(settings)
            elif action == "restart":
                webui.restart(settings)
            elif action == "status":
                webui.status(settings)
            elif action == "attach":
                webui.attach(settings)
            elif action == "logs":
                webui.logs(settings, args.lines)

        return 0

    except (BackendError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
