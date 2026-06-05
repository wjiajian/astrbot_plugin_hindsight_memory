import unittest

from scope import MissingScopeIdentityError, build_scope_from_event, build_scopes_from_event


class FakeEvent:
    def __init__(self, platform="telegram", sender="alice", group=None, umo="telegram:private:alice"):
        self.message_str = "hello"
        self.unified_msg_origin = umo
        self._platform = platform
        self._sender = sender
        self._group = group

    def get_platform_name(self):
        return self._platform

    def get_sender_id(self):
        return self._sender

    def get_group_id(self):
        return self._group


class ScopeTests(unittest.TestCase):
    def test_private_scope_hashes_sender_and_umo(self):
        scope = build_scope_from_event(FakeEvent(), "salt")

        self.assertEqual(scope.scope_type, "private")
        self.assertIn("scope:private", scope.tags)
        self.assertIn("platform:telegram", scope.tags)
        self.assertTrue(any(tag.startswith("sender:") for tag in scope.tags))
        self.assertTrue(any(tag.startswith("umo:") for tag in scope.tags))
        self.assertNotIn("alice", " ".join(scope.tags))

    def test_group_scope_uses_current_member_as_primary_scope(self):
        scope = build_scope_from_event(
            FakeEvent(group="group-1", umo="telegram:group:group-1"), "salt"
        )

        self.assertEqual(scope.scope_type, "group_member")
        self.assertIn("scope:group", scope.tags)
        self.assertIn("scope:group_member", scope.tags)
        self.assertTrue(any(tag.startswith("group:") for tag in scope.tags))
        self.assertTrue(any(tag.startswith("sender:") for tag in scope.tags))
        self.assertNotIn("group-1", " ".join(scope.tags))
        self.assertNotIn("alice", " ".join(scope.tags))

    def test_group_scopes_include_shared_and_member_layers(self):
        scopes = build_scopes_from_event(
            FakeEvent(group="group-1", umo="telegram:group:group-1"), "salt"
        )

        self.assertEqual(scopes.primary.scope_type, "group_member")
        self.assertEqual([scope.scope_type for scope in scopes.recall_scopes], ["group_shared", "group_member"])
        self.assertEqual([scope.scope_type for scope in scopes.retain_scopes], ["group_shared", "group_member"])
        self.assertFalse(any(tag.startswith("sender:") for tag in scopes.recall_scopes[0].tags))
        self.assertTrue(any(tag.startswith("sender:") for tag in scopes.recall_scopes[1].tags))

    def test_group_scope_requires_sender_id(self):
        event = FakeEvent(sender="", group="group-1", umo="telegram:group:group-1")

        with self.assertRaises(MissingScopeIdentityError):
            build_scopes_from_event(event, "salt")

    def test_private_scope_can_use_umo_when_sender_is_missing(self):
        scope = build_scope_from_event(FakeEvent(sender="", umo="telegram:private:alice"), "salt")

        self.assertEqual(scope.scope_type, "private")

    def test_private_scope_requires_sender_or_umo(self):
        event = FakeEvent(sender="", group=None, umo="")

        with self.assertRaises(MissingScopeIdentityError):
            build_scope_from_event(event, "salt")

    def test_missing_group_id_falls_back_to_private(self):
        scope = build_scope_from_event(FakeEvent(group=""), "salt")

        self.assertEqual(scope.scope_type, "private")

    def test_platform_isolation_changes_scope_key(self):
        one = build_scope_from_event(FakeEvent(platform="telegram"), "salt")
        two = build_scope_from_event(FakeEvent(platform="discord"), "salt")

        self.assertNotEqual(one.scope_key, two.scope_key)


if __name__ == "__main__":
    unittest.main()
