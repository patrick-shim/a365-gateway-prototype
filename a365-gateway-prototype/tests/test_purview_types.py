from __future__ import annotations

import unittest

from obs_gateway.purview.types import DlpEvaluation
from obs_gateway.shared.errors import ValidationError


class DlpEvaluationTests(unittest.TestCase):
    def test_rejects_non_string_client_ip(self) -> None:
        payload = {
            "user_id": "user-1",
            "content": "synthetic content",
            "activity": "uploadText",
            "conversation_id": "conversation-1",
            "sequence_number": 0,
            "client_ip": {"address": "127.0.0.1"},
        }
        with self.assertRaisesRegex(ValidationError, "client_ip"):
            DlpEvaluation.from_payload(payload)


if __name__ == "__main__":
    unittest.main()