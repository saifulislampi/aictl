\
import tempfile
import unittest
from pathlib import Path

from aictl.settings import command_from_string, parse_dotenv


class DotEnvTests(unittest.TestCase):
    def test_parse_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                """
# comment
FOO=bar
QUOTED="hello world"
export BAZ='qux'
"""
            )

            result = parse_dotenv(path)

            self.assertEqual(result["FOO"], "bar")
            self.assertEqual(result["QUOTED"], "hello world")
            self.assertEqual(result["BAZ"], "qux")

    def test_missing_dotenv(self):
        result = parse_dotenv(Path("/definitely/not/here"))
        self.assertEqual(result, {})

    def test_command_template(self):
        result = command_from_string(
            "tunnel connect {tunnel}",
            tunnel="remote-llm",
        )
        self.assertEqual(result, ["tunnel", "connect", "remote-llm"])


class RemoteSettingsTests(unittest.TestCase):
    def test_remote_config_and_environment_overrides(self):
        import os
        from unittest.mock import patch
        from aictl.settings import load_settings

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text(
                "AICTL_REMOTE_SSH_HOST=config-server\n"
                "AICTL_REMOTE_SSH_USER=alice\n"
                "AICTL_REMOTE_SSH_PORT=2222\n"
                "AICTL_REMOTE_SSH_IDENTITY_FILE=~/my key\n"
                "AICTL_REMOTE_OLLAMA_HOST=localhost\n"
                "AICTL_REMOTE_OLLAMA_PORT=11436\n"
                "AICTL_REMOTE_CONNECT_COMMAND=obsolete command\n"
            )
            with patch("aictl.settings.ENV_FILE", path), patch.dict(
                os.environ, {"AICTL_REMOTE_SSH_HOST": "env-server"}, clear=True,
            ):
                settings = load_settings()
            self.assertEqual(settings.remote_ssh_host, "env-server")
            self.assertEqual(settings.remote_ssh_user, "alice")
            self.assertEqual(settings.remote_ssh_port, 2222)
            self.assertEqual(settings.remote_ssh_identity_file, Path("~/my key").expanduser())
            self.assertEqual(settings.remote_ollama_host, "localhost")
            self.assertEqual(settings.remote_ollama_port, 11436)

    def test_unconfigured_remote_does_not_block_local_settings(self):
        import os
        from unittest.mock import patch
        from aictl.settings import load_settings

        with patch("aictl.settings.ENV_FILE", Path("/definitely/not/here")), patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
        self.assertEqual(settings.remote_ssh_host, "")
        self.assertEqual(settings.local_ollama_url, "http://127.0.0.1:11434")


if __name__ == "__main__":
    unittest.main()
