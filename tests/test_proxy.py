import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aictl import cli, proxy
from test_backends import make_settings


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.settings = make_settings()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        patcher = patch("aictl.proxy.STATE_DIR", Path(self.directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.output = io.StringIO()
        redirect = contextlib.redirect_stdout(self.output)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def test_generates_localai_config_and_dedicated_admin_listener(self):
        config = proxy.caddyfile(self.settings)
        self.assertIn("http://localai {", config)
        self.assertIn("bind 127.0.0.2", config)
        self.assertIn("reverse_proxy http://127.0.0.1:9090", config)
        self.assertIn("admin 127.0.0.1:2020", config)
        self.assertNotIn("https://", config)

    def test_custom_settings(self):
        settings = replace(self.settings, proxy_hostname="ai.test", proxy_port=8081)
        self.assertEqual(proxy.url(settings), "http://ai.test:8081")
        self.assertIn("http://ai.test:8081 {", proxy.caddyfile(settings))

    def test_rejects_bad_configuration_and_injection(self):
        for changes in (
            {"proxy_hostname": "localai {"},
            {"proxy_hostname": ""},
            {"proxy_hostname": "http://localai"},
            {"proxy_bind": "0.0.0.0"},
            {"proxy_port": 0}, {"proxy_admin_port": 65536},
            {"proxy_upstream": "http://example.com:9090"},
            {"proxy_upstream": "http://127.0.0.1:9090/path"},
            {"proxy_upstream": "http://127.0.0.1:9090\n}"},
            {"proxy_upstream": "http://127.0.0.2:80"},
            {"proxy_bind": "127.0.0.1", "proxy_port": 2020},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                proxy.caddyfile(replace(self.settings, **changes))

    @patch("aictl.proxy.platform.system", return_value="Darwin")
    @patch("aictl.proxy.bind_available", return_value=False)
    @patch("aictl.proxy.resolved_addresses", return_value=set())
    @patch("aictl.proxy.shutil.which", return_value=None)
    def test_setup_prints_install_hosts_and_alias_instructions(self, which, resolve, bind, platform):
        self.assertFalse(proxy.setup(self.settings))
        output = self.output.getvalue()
        self.assertIn("brew install caddy", output)
        self.assertIn("sudo nano /etc/hosts", output)
        self.assertIn("127.0.0.2 localai", output)
        self.assertIn("sudo ifconfig lo0 inet 127.0.0.2", output)
        self.assertIn("After a reboot", output)

    @patch("aictl.proxy.bind_available", return_value=True)
    @patch("aictl.proxy.resolved_addresses", return_value={"127.0.0.2"})
    @patch("aictl.proxy.shutil.which", return_value="/bin/caddy")
    def test_setup_preserves_completed_system_configuration(self, which, resolve, bind):
        self.assertTrue(proxy.setup(self.settings))
        output = self.output.getvalue()
        self.assertIn("Setup: ready", output)
        self.assertNotIn("sudo nano", output)
        self.assertNotIn("ifconfig", output)
        self.assertNotIn("brew install", output)

    @patch("aictl.proxy.bind_available", return_value=True)
    @patch("aictl.proxy.resolved_addresses", return_value={"127.0.0.1", "127.0.0.2"})
    @patch("aictl.proxy.shutil.which", return_value="/bin/caddy")
    def test_setup_detects_conflicting_hosts_entries(self, which, resolve, bind):
        self.assertFalse(proxy.setup(self.settings))
        self.assertIn("correct this entry", self.output.getvalue())

    @patch("aictl.proxy.run")
    @patch("aictl.proxy.shutil.which", return_value=None)
    def test_start_checks_caddy_before_running_commands(self, which, run):
        with patch("aictl.proxy.resolved_addresses", return_value=set()), patch(
            "aictl.proxy.bind_available", return_value=False,
        ):
            self.assertFalse(proxy.start(self.settings))
        run.assert_not_called()
        self.assertIn("/etc/hosts", self.output.getvalue())

    @patch("aictl.proxy.run")
    @patch("aictl.proxy.setup", return_value=False)
    @patch("aictl.proxy.require_caddy", return_value="/bin/caddy")
    def test_start_requires_completed_setup(self, require, setup, run):
        self.assertFalse(proxy.start(self.settings))
        run.assert_not_called()

    @patch("aictl.proxy.run")
    @patch("aictl.proxy.http_status", return_value=200)
    @patch("aictl.proxy.admin_config", return_value=None)
    @patch("aictl.proxy.setup", return_value=True)
    @patch("aictl.proxy.require_caddy", return_value="/bin/caddy")
    def test_start_reuses_existing_http_proxy(self, require, setup, admin, http, run):
        self.assertTrue(proxy.start(self.settings))
        run.assert_not_called()
        self.assertIn("leaving it running", self.output.getvalue())

    @patch("aictl.proxy.run")
    @patch("aictl.proxy.admin_config", return_value={"admin": {"listen": "127.0.0.1:2020"}})
    @patch("aictl.proxy.setup", return_value=True)
    @patch("aictl.proxy.require_caddy", return_value="/bin/caddy")
    def test_start_does_not_replace_unrelated_caddy(self, require, setup, admin, run):
        with self.assertRaisesRegex(RuntimeError, "Another Caddy instance"):
            proxy.start(self.settings)
        run.assert_not_called()

    @patch("aictl.proxy.os.geteuid", return_value=501)
    @patch("aictl.proxy.shutil.which", return_value="/usr/bin/sudo")
    @patch("aictl.proxy.run")
    @patch("aictl.proxy.http_status", side_effect=[None, 200])
    @patch("aictl.proxy.admin_config", return_value=None)
    @patch("aictl.proxy.setup", return_value=True)
    @patch("aictl.proxy.require_caddy", return_value="/opt/homebrew/bin/caddy")
    def test_background_start_validates_config_and_uses_sudo_for_port80(self, require, setup, admin, http, run, which, uid):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, '{"apps": {}}', ""),
            subprocess.CompletedProcess([], 0),
        ]
        self.assertTrue(proxy.start(self.settings))
        calls = run.call_args_list
        self.assertEqual(calls[0].args[0][1], "adapt")
        self.assertIn("--validate", calls[0].args[0])
        self.assertEqual(calls[1].args[0][:3], ["sudo", "/opt/homebrew/bin/caddy", "start"])
        self.assertNotIn("capture", calls[1].kwargs)
        config, snapshot = proxy.paths()
        self.assertIn("http://localai", config.read_text())
        self.assertTrue(proxy.managed({"apps": {}}))
        self.assertIn("Caddy started in the background", self.output.getvalue())

    @patch("aictl.proxy.run")
    @patch("aictl.proxy.http_status", return_value=None)
    @patch("aictl.proxy.admin_config", return_value=None)
    @patch("aictl.proxy.setup", return_value=True)
    @patch("aictl.proxy.require_caddy", return_value="/bin/caddy")
    def test_foreground_run_on_high_port_does_not_use_sudo(self, require, setup, admin, http, run):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, '{}', ""),
            subprocess.CompletedProcess([], 0),
        ]
        self.assertTrue(proxy.start(replace(self.settings, proxy_port=8081), foreground=True))
        self.assertEqual(run.call_args.args[0][:2], ["/bin/caddy", "run"])
        self.assertIn("Ctrl-C to stop", self.output.getvalue())

    @patch("aictl.proxy.run", return_value=subprocess.CompletedProcess([], 1, "", "bad config"))
    @patch("aictl.proxy.http_status", return_value=None)
    @patch("aictl.proxy.admin_config", return_value=None)
    @patch("aictl.proxy.setup", return_value=True)
    @patch("aictl.proxy.require_caddy", return_value="/bin/caddy")
    def test_config_validation_failure_prevents_start(self, require, setup, admin, http, run):
        with self.assertRaisesRegex(RuntimeError, "bad config"):
            proxy.start(self.settings)
        self.assertEqual(run.call_count, 1)

    @patch("aictl.proxy.run")
    @patch("aictl.proxy.admin_config", return_value={"unrelated": True})
    @patch("aictl.proxy.require_caddy", return_value="/bin/caddy")
    def test_stop_does_not_stop_unrelated_caddy(self, require, admin, run):
        with self.assertRaisesRegex(RuntimeError, "not started by aictl"):
            proxy.stop(self.settings)
        run.assert_not_called()

    @patch("aictl.proxy.run", return_value=subprocess.CompletedProcess([], 0, "", ""))
    @patch("aictl.proxy.admin_config", return_value={"apps": {}})
    @patch("aictl.proxy.require_caddy", return_value="/bin/caddy")
    def test_stop_uses_dedicated_admin_endpoint(self, require, admin, run):
        _, snapshot = proxy.paths()
        snapshot.parent.mkdir()
        snapshot.write_text('{"apps": {}}')
        proxy.stop(self.settings)
        run.assert_called_once_with(["/bin/caddy", "stop", "--address", "127.0.0.1:2020"], capture=True)

    @patch("aictl.proxy.run")
    @patch("aictl.proxy.admin_config", return_value=None)
    @patch("aictl.proxy.require_caddy", return_value="/bin/caddy")
    def test_stop_when_stopped(self, require, admin, run):
        proxy.stop(self.settings)
        run.assert_not_called()

    @patch("aictl.proxy.http_status", side_effect=[502, None])
    @patch("aictl.proxy.admin_config", return_value=None)
    @patch("aictl.proxy.resolved_addresses", return_value={"127.0.0.2"})
    def test_status_distinguishes_proxy_from_upstream_failure(self, resolve, admin, http):
        proxy.status(self.settings)
        self.assertIn("Proxy HTTP: HTTP 502", self.output.getvalue())
        self.assertIn("Upstream HTTP: unreachable", self.output.getvalue())

    def test_cli_proxy_commands(self):
        for command in ("setup", "start", "run", "status", "stop"):
            self.assertEqual(cli.build_parser().parse_args(["proxy", command]).proxy_command, command)

    @patch("aictl.cli.load_settings")
    @patch("aictl.proxy.setup", return_value=False)
    def test_cli_setup_failure_exit_code(self, setup, settings):
        with patch("sys.argv", ["aictl", "proxy", "setup"]):
            self.assertEqual(cli.main(), 1)

    @patch("aictl.cli.load_settings")
    @patch("aictl.proxy.start", return_value=True)
    def test_cli_run_dispatches_foreground(self, start, settings):
        with patch("sys.argv", ["aictl", "proxy", "run"]):
            self.assertEqual(cli.main(), 0)
        start.assert_called_once_with(settings.return_value, foreground=True)

    @patch("aictl.proxy.opener")
    def test_http_error_response_is_reported_as_status(self, opener):
        import urllib.error
        opener.return_value.open.side_effect = urllib.error.HTTPError("http://localai", 502, "Bad Gateway", {}, None)
        self.assertEqual(proxy.http_status("http://localai"), 502)

    def test_local_requests_ignore_environment_proxy_settings(self):
        import urllib.request
        local = proxy.opener()
        self.assertFalse(any(isinstance(h, urllib.request.ProxyHandler) for h in local.handlers))
        self.assertTrue(any(isinstance(h, proxy.NoRedirect) for h in local.handlers))

    @patch("aictl.proxy.run")
    @patch("aictl.proxy.admin_config", return_value={"apps": {}})
    @patch("aictl.proxy.setup", return_value=True)
    @patch("aictl.proxy.require_caddy", return_value="/bin/caddy")
    def test_start_reuses_its_managed_proxy(self, require, setup, admin, run):
        config, snapshot = proxy.paths()
        config.parent.mkdir()
        config.write_text(proxy.caddyfile(self.settings))
        snapshot.write_text('{"apps": {}}')
        self.assertTrue(proxy.start(self.settings))
        run.assert_not_called()

    @patch("aictl.proxy.run")
    @patch("aictl.proxy.admin_config", return_value={"apps": {}})
    @patch("aictl.proxy.setup", return_value=True)
    @patch("aictl.proxy.require_caddy", return_value="/bin/caddy")
    def test_changed_settings_require_restarting_managed_proxy(self, require, setup, admin, run):
        config, snapshot = proxy.paths()
        config.parent.mkdir()
        config.write_text(proxy.caddyfile(self.settings))
        snapshot.write_text('{"apps": {}}')
        with self.assertRaisesRegex(RuntimeError, "Proxy settings changed"):
            proxy.start(replace(self.settings, proxy_upstream="http://127.0.0.1:8080"))
        run.assert_not_called()

    @patch("aictl.proxy.run")
    @patch("aictl.proxy.bind_available", return_value=True)
    def test_existing_alias_never_runs_sudo_or_ifconfig(self, bind, run):
        proxy.ensure_loopback(self.settings)
        run.assert_not_called()

    @patch("aictl.proxy.os.geteuid", return_value=501)
    @patch("aictl.proxy.shutil.which", side_effect=lambda name: {"ifconfig": "/sbin/ifconfig", "sudo": "/usr/bin/sudo"}.get(name))
    @patch("aictl.proxy.platform.system", return_value="Darwin")
    @patch("aictl.proxy.bind_available", side_effect=[False, True])
    @patch("aictl.proxy.run", return_value=subprocess.CompletedProcess([], 0))
    def test_creates_configured_alias_with_sudo_and_verifies(self, run, bind, platform, which, uid):
        settings = replace(self.settings, proxy_bind="127.0.0.3")
        proxy.ensure_loopback(settings)
        run.assert_called_once_with([
            "sudo", "/sbin/ifconfig", "lo0", "inet", "127.0.0.3",
            "netmask", "255.255.255.255", "alias",
        ])
        self.assertEqual(bind.call_count, 2)
        self.assertIn("(created)", self.output.getvalue())

    @patch("aictl.proxy.os.geteuid", return_value=0)
    @patch("aictl.proxy.shutil.which", return_value="/sbin/ifconfig")
    @patch("aictl.proxy.platform.system", return_value="Darwin")
    @patch("aictl.proxy.bind_available", side_effect=[False, True])
    @patch("aictl.proxy.run", return_value=subprocess.CompletedProcess([], 0))
    def test_root_does_not_invoke_sudo_for_alias(self, run, bind, platform, which, uid):
        proxy.ensure_loopback(self.settings)
        self.assertEqual(run.call_args.args[0][0], "/sbin/ifconfig")

    @patch("aictl.proxy.os.geteuid", return_value=0)
    @patch("aictl.proxy.shutil.which", return_value="/sbin/ifconfig")
    @patch("aictl.proxy.platform.system", return_value="Darwin")
    @patch("aictl.proxy.bind_available", return_value=False)
    @patch("aictl.proxy.run", return_value=subprocess.CompletedProcess([], 1))
    def test_alias_creation_failure_is_reported(self, run, bind, platform, which, uid):
        with self.assertRaisesRegex(RuntimeError, "Could not create"):
            proxy.ensure_loopback(self.settings)
        self.assertNotIn("(created)", self.output.getvalue())

    @patch("aictl.proxy.os.geteuid", return_value=0)
    @patch("aictl.proxy.shutil.which", return_value="/sbin/ifconfig")
    @patch("aictl.proxy.platform.system", return_value="Darwin")
    @patch("aictl.proxy.bind_available", return_value=False)
    @patch("aictl.proxy.run", return_value=subprocess.CompletedProcess([], 0))
    def test_alias_must_be_available_after_ifconfig(self, run, bind, platform, which, uid):
        with self.assertRaisesRegex(RuntimeError, "still unavailable"):
            proxy.ensure_loopback(self.settings)

    @patch("aictl.proxy.ensure_loopback")
    @patch("aictl.proxy.platform.system", return_value="Darwin")
    @patch("aictl.proxy.bind_available", return_value=False)
    @patch("aictl.proxy.resolved_addresses", return_value={"127.0.0.2"})
    @patch("aictl.proxy.shutil.which", return_value="/bin/caddy")
    def test_apply_setup_creates_missing_alias(self, which, resolve, bind, platform, ensure):
        self.assertTrue(proxy.setup(self.settings, apply=True))
        ensure.assert_called_once_with(self.settings)

    @patch("aictl.proxy.ensure_loopback")
    @patch("aictl.proxy.platform.system", return_value="Darwin")
    @patch("aictl.proxy.bind_available", return_value=False)
    @patch("aictl.proxy.resolved_addresses", return_value=set())
    @patch("aictl.proxy.shutil.which", return_value=None)
    def test_apply_requires_caddy_and_hosts_mapping_first(self, which, resolve, bind, platform, ensure):
        self.assertFalse(proxy.setup(self.settings, apply=True))
        ensure.assert_not_called()

    @patch("aictl.proxy.ensure_loopback")
    @patch("aictl.proxy.bind_available", return_value=False)
    @patch("aictl.proxy.resolved_addresses", return_value={"127.0.0.2"})
    @patch("aictl.proxy.shutil.which", return_value="/bin/caddy")
    def test_plain_setup_does_not_change_network(self, which, resolve, bind, ensure):
        self.assertFalse(proxy.setup(self.settings))
        ensure.assert_not_called()

    @patch("aictl.cli.load_settings")
    @patch("aictl.proxy.setup", return_value=True)
    def test_cli_dispatches_setup_apply(self, setup, settings):
        with patch("sys.argv", ["aictl", "proxy", "setup", "--apply"]):
            self.assertEqual(cli.main(), 0)
        setup.assert_called_once_with(settings.return_value, apply=True)

    @patch("aictl.proxy.setup", return_value=False)
    def test_start_requests_automatic_loopback_setup(self, setup):
        self.assertFalse(proxy.start(self.settings))
        setup.assert_called_once_with(self.settings, apply=True)


if __name__ == "__main__":
    unittest.main()
