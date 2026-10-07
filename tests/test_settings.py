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


if __name__ == "__main__":
    unittest.main()
