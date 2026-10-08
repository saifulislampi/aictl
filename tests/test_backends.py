\
import unittest
from pathlib import Path

from aictl.backends import get_backend
from aictl.settings import Settings


def make_settings():
    return Settings(
        remote_ollama_url="http://127.0.0.1:11435",
        remote_tunnel_name="remote-llm",
        local_ollama_url="http://127.0.0.1:11434",
        local_ollama_session="local-ollama",
        local_ollama_start_command=["ollama", "serve"],
        webui_host="127.0.0.1",
        webui_port=8080,
        webui_session="open-webui",
        webui_data_dir=Path("~/.local-ai/open-webui").expanduser(),
        webui_python="3.11",
    )


class BackendTests(unittest.TestCase):
    def test_local_alias(self):
        backend = get_backend(make_settings(), "local-ollama")
        self.assertEqual(backend.name, "local")

    def test_remote_alias(self):
        backend = get_backend(make_settings(), "remote-ollama")
        self.assertEqual(backend.name, "remote")


if __name__ == "__main__":
    unittest.main()
