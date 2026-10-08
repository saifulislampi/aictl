import contextlib
import io
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aictl import backends, cli, tunnels
from test_backends import make_settings


class TunnelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_dir = Path(self.directory.name)
        state_patch = patch("aictl.tunnels.STATE_DIR", self.state_dir)
        state_patch.start()
        self.addCleanup(state_patch.stop)
        self.settings = replace(
            make_settings(), remote_ssh_host="server.example.com",
            remote_ssh_user="alice", remote_ssh_port=2222,
            remote_ssh_identity_file=Path("/keys/my private key"),
        )
        self.output = io.StringIO()
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)
        for name in ("legacy_running", "running"):
            mock = patch(f"aictl.tunnels.{name}", return_value=False)
            setattr(self, name, mock.start())
            self.addCleanup(mock.stop)
        mock = patch("aictl.tunnels.command_exists", return_value=True)
        self.exists = mock.start()
        self.addCleanup(mock.stop)
        mock = patch("aictl.tunnels.time.sleep")
        mock.start()
        self.addCleanup(mock.stop)

    def test_explicit_ssh_connection_and_forward(self):
        command = tunnels.ssh_command(self.settings)
        self.assertEqual(command[:5], ["ssh", "-F", "/dev/null", "-N", "-T"])
        self.assertIn("-f", command)
        self.assertIn("-M", command)
        self.assertEqual(command[command.index("-S") + 1], str(tunnels.control_path(self.settings)))
        self.assertEqual(command[command.index("-L") + 1], "127.0.0.1:11435:127.0.0.1:11434")
        self.assertEqual(command[command.index("-l") + 1], "alice")
        self.assertEqual(command[command.index("-p") + 1], "2222")
        self.assertEqual(command[command.index("-i") + 1], "/keys/my private key")
        self.assertIn("ExitOnForwardFailure=yes", command)
        self.assertEqual(command[-1], "server.example.com")

    def test_optional_user_and_key(self):
        command = tunnels.ssh_command(replace(
            self.settings, remote_ssh_user="", remote_ssh_identity_file=None,
        ))
        self.assertNotIn("-l", command)
        self.assertNotIn("-i", command)
        self.assertNotIn("BatchMode=yes", command)

    def test_noninteractive_authentication_uses_batch_mode(self):
        command = tunnels.ssh_command(self.settings, interactive=False)
        self.assertIn("BatchMode=yes", command)

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

    def test_control_path_is_stable_when_connection_settings_change(self):
        path = tunnels.control_path(self.settings)
        self.assertEqual(path, tunnels.control_path(replace(self.settings, remote_ssh_host="new-server")))
        self.assertNotEqual(path, tunnels.control_path(replace(self.settings, remote_tunnel_name="other")))
        self.assertTrue(path.is_relative_to(self.state_dir))

    def test_long_control_path_has_actionable_error(self):
        with patch("aictl.tunnels.STATE_DIR", Path("/" + "x" * 100)):
            with self.assertRaisesRegex(ValueError, "AICTL_STATE_DIR"):
                tunnels.control_path(self.settings)

    @patch("aictl.tunnels.run")
    @patch("aictl.tunnels.reachable", return_value=True)
    def test_reuses_reachable_endpoint_without_any_ssh_or_tmux(self, reachable, run):
        self.assertTrue(tunnels.start(self.settings))
        self.running.assert_not_called()
        self.legacy_running.assert_not_called()
        run.assert_not_called()
        self.assertIn("using the existing connection", self.output.getvalue())

    @patch("aictl.tunnels.run")
    @patch("aictl.tunnels.reachable", side_effect=[False, False, True])
    def test_reuses_existing_ssh_connection_without_starting_another(self, reachable, run):
        self.running.return_value = True
        self.assertTrue(tunnels.start(self.settings))
        run.assert_not_called()
        self.assertIn("SSH tunnel already running", self.output.getvalue())

    @patch("aictl.tunnels.run")
    @patch("aictl.tunnels.reachable", side_effect=[False, True])
    def test_rechecks_endpoint_after_taking_lock(self, reachable, run):
        self.assertTrue(tunnels.start(self.settings))
        run.assert_not_called()
        self.running.assert_not_called()

    @patch("aictl.tunnels.sys.stdin.isatty", return_value=True)
    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 0))
    @patch("aictl.tunnels.reachable", side_effect=[False, False, True])
    def test_authentication_inherits_terminal_and_reports_success(self, reachable, run, isatty):
        settings = replace(self.settings, remote_ssh_identity_file=None)
        self.assertTrue(tunnels.start(settings))
        command = run.call_args.args[0]
        self.assertEqual(command[0], "ssh")
        self.assertNotIn("-i", command)
        self.assertNotIn("BatchMode=yes", command)
        self.assertNotIn("capture", run.call_args.kwargs)
        self.assertEqual(run.call_count, 1)
        output = self.output.getvalue()
        self.assertIn("Answer SSH prompts here", output)
        self.assertIn("SSH connected; tunnel running in the background", output)
        self.assertIn("Ollama is ready", output)
        self.assertNotIn("Ctrl-b", output)

    @patch("aictl.tunnels.sys.stdin.isatty", return_value=False)
    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 0))
    @patch("aictl.tunnels.reachable", side_effect=[False, False, True])
    def test_noninteractive_start_never_prompts_for_password(self, reachable, run, isatty):
        self.assertTrue(tunnels.start(self.settings))
        self.assertIn("BatchMode=yes", run.call_args.args[0])
        self.assertNotIn("Answer SSH prompts here", self.output.getvalue())

    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 255))
    @patch("aictl.tunnels.reachable", return_value=False)
    def test_authentication_failure_does_not_report_success(self, reachable, run):
        self.assertFalse(tunnels.start(self.settings))
        self.assertIn("SSH connection failed", self.output.getvalue())
        self.assertNotIn("SSH connected", self.output.getvalue())

    @patch("aictl.tunnels.run")
    @patch("aictl.tunnels.reachable", return_value=False)
    def test_missing_ssh_has_actionable_error(self, reachable, run):
        self.exists.return_value = False
        with self.assertRaisesRegex(RuntimeError, "ssh is required"):
            tunnels.start(self.settings)
        run.assert_not_called()

    @patch("aictl.tunnels.run")
    @patch("aictl.tunnels.reachable", return_value=False)
    def test_readiness_timeout_distinguishes_ssh_from_ollama(self, reachable, run):
        self.running.return_value = True
        self.assertFalse(tunnels.start(self.settings))
        self.assertIn("SSH tunnel is running, but Ollama is not responding", self.output.getvalue())
        run.assert_not_called()

    @patch("aictl.tunnels.run")
    @patch("aictl.tunnels.reachable", return_value=False)
    def test_timeout_detects_disconnected_ssh(self, reachable, run):
        self.running.side_effect = [True, False]
        self.assertFalse(tunnels.start(self.settings))
        self.assertIn("SSH tunnel disconnected", self.output.getvalue())

    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 0))
    @patch("aictl.tunnels.reachable", side_effect=[False, False, True])
    def test_stale_socket_removed_before_reconnection(self, reachable, run):
        path = tunnels.control_path(self.settings)
        path.parent.mkdir()
        path.touch()
        self.assertTrue(tunnels.start(self.settings))
        self.assertFalse(path.exists())

    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 0, "", ""))
    @patch("aictl.tunnels.reachable", side_effect=[False, False, True])
    def test_unresponsive_legacy_tmux_tunnel_migrates_to_direct_ssh(self, reachable, run):
        self.legacy_running.return_value = True
        self.assertTrue(tunnels.start(self.settings))
        self.assertEqual(run.call_args_list[0].args[0], ["tmux", "kill-session", "-t", "=remote-llm"])
        self.assertEqual(run.call_args_list[1].args[0][0], "ssh")
        self.assertNotIn("tmux", run.call_args_list[1].args[0])

    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 0, "", ""))
    def test_disconnect_uses_control_socket(self, run):
        self.running.return_value = True
        tunnels.stop(self.settings)
        run.assert_called_once_with(tunnels.control_command(self.settings, "exit"), capture=True)

    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 1, "", "cannot stop"))
    def test_disconnect_reports_failure(self, run):
        self.running.return_value = True
        with self.assertRaisesRegex(RuntimeError, "cannot stop"):
            tunnels.stop(self.settings)

    @patch("aictl.tunnels.run")
    def test_disconnect_when_stopped(self, run):
        tunnels.stop(self.settings)
        run.assert_not_called()

    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 0, "", ""))
    def test_disconnect_also_stops_legacy_tunnel(self, run):
        self.legacy_running.return_value = True
        tunnels.stop(self.settings)
        run.assert_called_once_with(["tmux", "kill-session", "-t", "=remote-llm"], capture=True)

    @patch("aictl.tunnels.reachable", return_value=False)
    def test_status_distinguishes_connection_from_endpoint(self, reachable):
        self.running.return_value = True
        tunnels.status(self.settings)
        self.assertIn("SSH tunnel: running", self.output.getvalue())
        self.assertIn("Ollama HTTP: unreachable", self.output.getvalue())

    @patch("aictl.tunnels.run")
    @patch("aictl.tunnels.reachable", return_value=True)
    def test_old_attach_command_does_not_open_tmux(self, reachable, run):
        tunnels.attach(self.settings)
        run.assert_not_called()
        self.assertIn("authentication happens in your terminal", self.output.getvalue())

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

    @patch("aictl.backends.set_active_backend")
    @patch("aictl.backends.start")
    @patch("aictl.tunnels.run")
    @patch("aictl.backends.reachable", return_value=True)
    def test_switch_reuses_working_remote_without_new_process(self, reachable, run, start, select):
        self.assertTrue(backends.switch(self.settings, "remote"))
        start.assert_not_called()
        run.assert_not_called()
        select.assert_called_once_with("remote")
        self.assertIn("already reachable; using the existing connection", self.output.getvalue())

    def test_cli_tunnel_commands(self):
        parser = cli.build_parser()
        for action in ("connect", "disconnect", "status", "attach"):
            self.assertEqual(parser.parse_args(["tunnel", action]).tunnel_command, action)

    @patch("aictl.cli.load_settings")
    @patch("aictl.tunnels.start", return_value=False)
    def test_cli_connect_failure_exit_code(self, start, settings):
        with patch("sys.argv", ["aictl", "tunnel", "connect"]):
            self.assertEqual(cli.main(), 1)


class ControlSocketTests(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patcher = patch("aictl.tunnels.STATE_DIR", Path(self.directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("aictl.tunnels.command_exists", return_value=True)
    @patch("aictl.tunnels.run", return_value=subprocess.CompletedProcess([], 0))
    def test_running_checks_local_control_socket(self, run, exists):
        path = tunnels.control_path(self.settings)
        path.parent.mkdir()
        path.touch()
        self.assertTrue(tunnels.running(self.settings))
        run.assert_called_once_with(tunnels.control_command(self.settings, "check"), capture=True)

    @patch("aictl.tunnels.command_exists", return_value=True)
    @patch("aictl.tunnels.run")
    def test_missing_socket_does_not_start_ssh(self, run, exists):
        self.assertFalse(tunnels.running(self.settings))
        run.assert_not_called()

    def test_tunnel_lock_creates_private_directory(self):
        with tunnels.tunnel_lock(self.settings):
            path = tunnels.control_path(self.settings)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertTrue(path.with_suffix(".lock").exists())

    def test_tunnel_lock_serializes_concurrent_commands(self):
        import threading

        started = threading.Event()
        acquired = threading.Event()
        errors = []

        def second_command():
            started.set()
            try:
                with tunnels.tunnel_lock(self.settings):
                    acquired.set()
            except Exception as exc:
                errors.append(exc)

        # The second command cannot acquire the lock until the first returns.
        with tunnels.tunnel_lock(self.settings):
            worker = threading.Thread(target=second_command, daemon=True)
            worker.start()
            self.assertTrue(started.wait(timeout=1))
            self.assertFalse(acquired.wait(timeout=0.05))
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertTrue(acquired.is_set())
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
