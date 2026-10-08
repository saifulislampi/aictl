import contextlib
import io
import shlex
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aictl import backends, cli, tunnels
from test_backends import make_settings


class TunnelTests(unittest.TestCase):
    def setUp(self):
        self.settings = replace(
            make_settings(), remote_ssh_host="server.example.com",
            remote_ssh_user="alice", remote_ssh_port=2222,
            remote_ssh_identity_file=Path("/keys/my private key"),
        )
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_explicit_ssh_connection_and_forward(self):
        command = tunnels.ssh_command(self.settings)
        self.assertEqual(command[:5], ["ssh", "-F", "/dev/null", "-N", "-T"])
        self.assertEqual(command[command.index("-L") + 1], "127.0.0.1:11435:127.0.0.1:11434")
        self.assertEqual(command[command.index("-l") + 1], "alice")
        self.assertEqual(command[command.index("-p") + 1], "2222")
        self.assertEqual(command[command.index("-i") + 1], "/keys/my private key")
        self.assertIn("ExitOnForwardFailure=yes", command)
        self.assertEqual(command[-1], "server.example.com")

    def test_optional_user_and_key(self):
        command = tunnels.ssh_command(replace(self.settings, remote_ssh_user="", remote_ssh_identity_file=None))
        self.assertNotIn("-l", command)
        self.assertNotIn("-i", command)

    def test_invalid_configuration(self):
        for changes in (
            {"remote_ssh_host": ""}, {"remote_ssh_host": "-bad"},
            {"remote_ssh_port": 0}, {"remote_ollama_port": 65536},
            {"remote_tunnel_name": "bad.name"},
            {"remote_ollama_url": "http://0.0.0.0:11435"},
            {"remote_ollama_url": "https://127.0.0.1:11435"},
            {"remote_ollama_url": "http://127.0.0.1:11435/api"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                tunnels.ssh_command(replace(self.settings, **changes))

    def test_ipv6_forward(self):
        command = tunnels.ssh_command(replace(
            self.settings, remote_ollama_url="http://[::1]:11436", remote_ollama_host="::1",
        ))
        self.assertEqual(command[command.index("-L") + 1], "[::1]:11436:[::1]:11434")

    @patch("aictl.tunnels.running")
    @patch("aictl.tunnels.reachable", return_value=True)
    def test_reuses_reachable_endpoint(self, reachable, running):
        self.assertTrue(tunnels.start(self.settings))
        running.assert_not_called()

    @patch("aictl.tunnels.time.sleep")
    @patch("aictl.tunnels.run")
    @patch("aictl.tunnels.running", return_value=True)
    @patch("aictl.tunnels.reachable", side_effect=[False, True])
    def test_reuses_existing_session(self, reachable, running, run, sleep):
        self.assertTrue(tunnels.start(self.settings))
        run.assert_not_called()

    @patch("aictl.tunnels.time.sleep")
    @patch("aictl.tunnels.command_exists", return_value=True)
    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 0, "", ""))
    @patch("aictl.tunnels.running", return_value=False)
    @patch("aictl.tunnels.reachable", side_effect=[False, True])
    def test_creates_detached_retry_session(self, reachable, running, run, exists, sleep):
        self.assertTrue(tunnels.start(self.settings))
        args = run.call_args.args[0]
        self.assertEqual(args[:5], ["tmux", "new-session", "-d", "-s", "remote-llm"])
        shell_args = shlex.split(args[-1])
        self.assertEqual(shell_args[:2], ["sh", "-c"])
        self.assertIn(shlex.join(tunnels.ssh_command(self.settings)), shell_args[2])
        self.assertIn("sleep 5", shell_args[2])
        # Parse the nested shell command without executing SSH.
        self.assertEqual(subprocess.run(
            ["sh", "-n", "-c", shell_args[2]], capture_output=True,
        ).returncode, 0)

    @patch("aictl.tunnels.command_exists", return_value=True)
    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 1, "", "tmux failed"))
    @patch("aictl.tunnels.running", return_value=False)
    @patch("aictl.tunnels.reachable", return_value=False)
    def test_session_creation_failure(self, reachable, running, run, exists):
        with self.assertRaisesRegex(RuntimeError, "tmux failed"):
            tunnels.start(self.settings)

    @patch("aictl.tunnels.time.sleep")
    @patch("aictl.tunnels.running", return_value=True)
    @patch("aictl.tunnels.reachable", return_value=False)
    def test_readiness_timeout(self, reachable, running, sleep):
        self.assertFalse(tunnels.start(self.settings))
        self.assertIn("aictl tunnel attach", self.output._new_target.getvalue())

    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 0, "", ""))
    @patch("aictl.tunnels.running", return_value=True)
    def test_disconnect_targets_exact_session(self, running, run):
        tunnels.stop(self.settings)
        self.assertEqual(run.call_args.args[0], ["tmux", "kill-session", "-t", "=remote-llm"])

    @patch("aictl.tunnels.run")
    @patch("aictl.tunnels.running", return_value=False)
    def test_disconnect_when_stopped(self, running, run):
        tunnels.stop(self.settings)
        run.assert_not_called()

    @patch("aictl.backends.set_active_backend")
    @patch("aictl.backends.reachable", return_value=False)
    @patch("aictl.tunnels.start", return_value=True)
    def test_switch_creates_tunnel_and_selects_remote(self, start, reachable, select):
        self.assertTrue(backends.switch(self.settings, "remote"))
        start.assert_called_once_with(self.settings)
        select.assert_called_once_with("remote")

    @patch("aictl.backends.set_active_backend")
    @patch("aictl.backends.reachable", return_value=False)
    @patch("aictl.tunnels.start", return_value=False)
    def test_failed_switch_preserves_selection(self, start, reachable, select):
        self.assertFalse(backends.switch(self.settings, "remote"))
        select.assert_not_called()

    def test_cli_tunnel_commands(self):
        parser = cli.build_parser()
        for action in ("connect", "disconnect", "status", "attach"):
            self.assertEqual(parser.parse_args(["tunnel", action]).tunnel_command, action)

    @patch("aictl.cli.load_settings")
    @patch("aictl.tunnels.start", return_value=False)
    def test_cli_connect_failure_exit_code(self, start, settings):
        with patch("sys.argv", ["aictl", "tunnel", "connect"]):
            self.assertEqual(cli.main(), 1)

    @patch("aictl.tunnels.command_exists", return_value=False)
    @patch("aictl.tunnels.running", return_value=False)
    @patch("aictl.tunnels.reachable", return_value=False)
    def test_missing_ssh_has_actionable_error(self, reachable, running, exists):
        with self.assertRaisesRegex(RuntimeError, "ssh is required"):
            tunnels.start(self.settings)

    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 1, "", "cannot stop"))
    @patch("aictl.tunnels.running", return_value=True)
    def test_disconnect_reports_failure(self, running, run):
        with self.assertRaisesRegex(RuntimeError, "cannot stop"):
            tunnels.stop(self.settings)

    @patch("aictl.tunnels.running", return_value=True)
    @patch("aictl.tunnels.reachable", return_value=False)
    def test_status_distinguishes_session_from_endpoint(self, reachable, running):
        tunnels.status(self.settings)
        output = self.output._new_target.getvalue()
        self.assertIn("Tunnel tmux: running", output)
        self.assertIn("Ollama HTTP: unreachable", output)

    @patch("aictl.tunnels.os.execvp")
    @patch("aictl.tunnels.running", return_value=True)
    def test_attach_targets_exact_session(self, running, execvp):
        tunnels.attach(self.settings)
        execvp.assert_called_once_with("tmux", ["tmux", "attach", "-t", "=remote-llm"])

    @patch("aictl.tunnels.command_exists", return_value=True)
    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 0, "", ""))
    def test_running_targets_exact_session(self, run, exists):
        self.assertTrue(tunnels.running(self.settings))
        self.assertEqual(run.call_args.args[0], ["tmux", "has-session", "-t", "=remote-llm"])


if __name__ == "__main__":
    unittest.main()
