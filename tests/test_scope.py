import unittest

from scope import build_scope_from_event


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

    def test_group_scope_hashes_group_and_omits_sender_tag(self):
        scope = build_scope_from_event(
            FakeEvent(group="group-1", umo="telegram:group:group-1"), "salt"
        )

        self.assertEqual(scope.scope_type, "group")
        self.assertIn("scope:group", scope.tags)
        self.assertTrue(any(tag.startswith("group:") for tag in scope.tags))
        self.assertFalse(any(tag.startswith("sender:") for tag in scope.tags))
        self.assertNotIn("group-1", " ".join(scope.tags))

    def test_missing_group_id_falls_back_to_private(self):
        scope = build_scope_from_event(FakeEvent(group=""), "salt")

        self.assertEqual(scope.scope_type, "private")

    def test_platform_isolation_changes_scope_key(self):
        one = build_scope_from_event(FakeEvent(platform="telegram"), "salt")
        two = build_scope_from_event(FakeEvent(platform="discord"), "salt")

        self.assertNotEqual(one.scope_key, two.scope_key)


if __name__ == "__main__":
    unittest.main()
