from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch

from a365_agent import cli
from a365_agent.config import DEFAULT_SIT_FILE


class CliTests(unittest.TestCase):
    def test_sit_without_path_uses_bundled_file(self) -> None:
        args = cli.parse_args(["--sit"])
        self.assertEqual(args.sit, DEFAULT_SIT_FILE)
        self.assertFalse(args.ai)

    def test_ai_requires_sit(self) -> None:
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit) as raised:
                cli.parse_args(["--ai"])
        self.assertEqual(raised.exception.code, 2)

    def test_main_dispatches_custom_sit_path_and_ai_mode(self) -> None:
        with patch.object(cli, "run_sit_batch", return_value=1) as run_batch:
            exit_code = cli.main(["--sit", "custom.yaml", "--ai"])

        self.assertEqual(exit_code, 1)
        path = run_batch.call_args.args[0]
        self.assertTrue(path.is_absolute())
        self.assertEqual(path.name, "custom.yaml")
        self.assertTrue(run_batch.call_args.kwargs["use_ai"])

    def test_main_maps_runtime_errors_to_exit_code_two(self) -> None:
        with (
            patch.object(cli, "run_chat", side_effect=RuntimeError("bad config")),
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            self.assertEqual(cli.main([]), 2)
        self.assertEqual(stderr.getvalue().strip(), "Operational error: bad config")

    def test_main_maps_other_errors_to_exit_code_one(self) -> None:
        with (
            patch.object(cli, "run_chat", side_effect=ValueError("bad request")),
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            self.assertEqual(cli.main([]), 1)
        self.assertEqual(
            stderr.getvalue().strip(),
            "Request or processing error (ValueError): bad request",
        )


if __name__ == "__main__":
    unittest.main()