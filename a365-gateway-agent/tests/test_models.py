from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from azure.core.credentials import AccessToken
from jwt import encode as encode_jwt

from a365_agent.models import Caller, ConversationContext


class FakeCredential:
    def __init__(self, claims: dict[str, str]) -> None:
        self.token = encode_jwt(claims, key="", algorithm="none")
        self.requested_scopes: tuple[str, ...] = ()

    def get_token(self, *scopes: str, **kwargs: object) -> AccessToken:
        self.requested_scopes = scopes
        return AccessToken(self.token, 4_102_444_800)


class ModelTests(unittest.TestCase):
    def test_conversation_context_uses_distinct_uuid_values(self) -> None:
        context = ConversationContext.new()
        self.assertNotEqual(context.session_id, context.conversation_id)
        self.assertEqual(len(context.session_id), 36)
        self.assertEqual(len(context.conversation_id), 36)

    def test_caller_uses_identity_claims_without_forwarding_token(self) -> None:
        credential = FakeCredential(
            {
                "oid": "user-object-id",
                "preferred_username": "user@example.com",
                "name": "Example User",
            }
        )
        scope = "https://cognitiveservices.azure.com/.default"

        with patch.dict(os.environ, {}, clear=True):
            caller = Caller.from_azure_credential(credential, scope)

        self.assertEqual(credential.requested_scopes, (scope,))
        self.assertEqual(caller.user_id, "user-object-id")
        self.assertEqual(caller.email, "user@example.com")
        self.assertEqual(caller.name, "Example User")
        self.assertEqual(caller.client_ip, "127.0.0.1")
        self.assertNotIn(credential.token, repr(caller))

    def test_caller_environment_values_override_token_claims(self) -> None:
        credential = FakeCredential({"oid": "claim-id", "name": "Claim Name"})
        overrides = {
            "CALLER_USER_ID": "override-id",
            "CALLER_USER_EMAIL": "override@example.com",
            "CALLER_USER_NAME": "Override Name",
            "CALLER_CLIENT_IP": "192.0.2.10",
        }

        with patch.dict(os.environ, overrides, clear=True):
            caller = Caller.from_azure_credential(credential, "scope")

        self.assertEqual(caller.user_id, "override-id")
        self.assertEqual(caller.email, "override@example.com")
        self.assertEqual(caller.name, "Override Name")
        self.assertEqual(caller.client_ip, "192.0.2.10")

    def test_caller_requires_user_id_when_oid_is_absent(self) -> None:
        credential = FakeCredential({"name": "Application Identity"})
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "CALLER_USER_ID"):
                Caller.from_azure_credential(credential, "scope")


if __name__ == "__main__":
    unittest.main()
