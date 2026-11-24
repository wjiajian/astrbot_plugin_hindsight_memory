"""Owner scope / shared-bank routing tests.

Reuses the astrbot stubs installed by test_main_memory_ai so the plugin module
can be imported without the real framework.
"""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_main_memory_ai as base  # noqa: E402  (installs astrbot stubs)

main = base.main


OWNER = "2519208636"


class FakeEvent:
    def __init__(self, sender=OWNER, group=None, admin=False, platform="onebot"):
        self.unified_msg_origin = f"{platform}:{'group' if group else 'private'}:{sender}"
        self.message_str = "hello"
        self._platform = platform
        self._sender = sender
        self._group = group
        self._admin = admin

    def get_platform_name(self):
        return self._platform

    def get_sender_id(self):
        return self._sender

    def get_group_id(self):
        return self._group

    def is_admin(self):
        return self._admin


def make_plugin(config, data_dir=None):
    plugin = main.HindsightMemoryPlugin.__new__(main.HindsightMemoryPlugin)
    plugin._context = base.SimpleNamespace(conversation_manager=None)
    plugin.config = config
    plugin.store = main.PluginStateStore(Path(data_dir or tempfile.mkdtemp()))
    plugin.salt = "test-salt"
    plugin.hindsight_client = None
    plugin.hindsight_client_signature = None
    return plugin


BASE_CFG = {"bank_id": "local-bank", "shared_bank_id": "shared-bank", "owner_user_ids": OWNER}


class OwnerScopeTests(unittest.TestCase):
    def test_owner_private_chat_gets_owner_scope(self):
        plugin = make_plugin(dict(BASE_CFG))
        scopes = plugin._scopes(FakeEvent())
        self.assertIsNotNone(scopes)
        self.assertTrue(plugin._is_owner_scope(scopes.primary))
        self.assertTrue(scopes.primary.scope_key.startswith("owner-private:"))
        self.assertEqual(scopes.primary.tags, [])

    def test_owner_is_detected_without_platform_admin_role(self):
        """OneBot private events have no role, so is_admin() is False there."""
        plugin = make_plugin(dict(BASE_CFG))
        event = FakeEvent(admin=False)
        self.assertFalse(event.is_admin())
        self.assertTrue(plugin._is_admin_event(event))

    def test_stranger_private_chat_keeps_hashed_scope(self):
        plugin = make_plugin(dict(BASE_CFG))
        scopes = plugin._scopes(FakeEvent(sender="10000"))
        self.assertFalse(plugin._is_owner_scope(scopes.primary))
        self.assertNotIn(OWNER, scopes.primary.scope_key)

    def test_group_chat_never_gets_owner_scope(self):
        plugin = make_plugin(dict(BASE_CFG))
        scopes = plugin._scopes(FakeEvent(group="275091129", admin=True))
        self.assertFalse(plugin._is_owner_scope(scopes.primary))

    def test_no_owner_configured_means_no_owner_scope(self):
        cfg = {"bank_id": "local-bank", "shared_bank_id": "shared-bank", "owner_user_ids": ""}
        plugin = make_plugin(cfg)
        # the AstrBot admin fallback is unavailable in tests, so nobody is owner
        scopes = plugin._scopes(FakeEvent())
        self.assertFalse(plugin._is_owner_scope(scopes.primary))


class BankRoutingTests(unittest.TestCase):
    def test_owner_writes_to_shared_bank(self):
        plugin = make_plugin(dict(BASE_CFG))
        self.assertEqual(plugin._bank_id(FakeEvent()), "shared-bank")

    def test_stranger_writes_to_local_bank(self):
        plugin = make_plugin(dict(BASE_CFG))
        self.assertEqual(plugin._bank_id(FakeEvent(sender="10000")), "local-bank")

    def test_owner_private_mode_writes_to_local_bank(self):
        plugin = make_plugin(dict(BASE_CFG))
        event = FakeEvent()
        key = plugin._scopes(event).primary.scope_key
        plugin.store.set_private_scope(key, True)
        self.assertEqual(plugin._bank_id(event), "local-bank")

    def test_owner_private_mode_reads_both_banks(self):
        plugin = make_plugin(dict(BASE_CFG))
        event = FakeEvent()
        self.assertEqual(plugin._recall_banks(event), ["shared-bank"])
        key = plugin._scopes(event).primary.scope_key
        plugin.store.set_private_scope(key, True)
        self.assertEqual(plugin._recall_banks(event), ["local-bank", "shared-bank"])

    def test_without_shared_bank_everything_stays_local(self):
        plugin = make_plugin({"bank_id": "local-bank", "owner_user_ids": OWNER})
        event = FakeEvent()
        self.assertEqual(plugin._bank_id(event), "local-bank")
        self.assertEqual(plugin._recall_banks(event), ["local-bank"])

    def test_shared_bank_ignored_when_event_missing(self):
        plugin = make_plugin(dict(BASE_CFG))
        self.assertEqual(plugin._bank_id(), "local-bank")
        self.assertEqual(plugin._recall_banks(), ["local-bank"])


class PrivateModeStateTests(unittest.TestCase):
    def test_private_scope_state_survives_reload(self):
        data_dir = tempfile.mkdtemp()
        store = main.PluginStateStore(Path(data_dir))
        store.set_private_scope("owner-private:onebot:abc", True)
        self.assertTrue(main.PluginStateStore(Path(data_dir)).is_private_scope("owner-private:onebot:abc"))

    def test_private_scope_can_be_turned_off(self):
        data_dir = tempfile.mkdtemp()
        store = main.PluginStateStore(Path(data_dir))
        store.set_private_scope("owner-private:onebot:abc", True)
        store.set_private_scope("owner-private:onebot:abc", False)
        self.assertFalse(store.is_private_scope("owner-private:onebot:abc"))

    def test_legacy_state_file_without_private_scopes_still_loads(self):
        data_dir = Path(tempfile.mkdtemp())
        state_file = data_dir / main.STATE_FILE if hasattr(main, "STATE_FILE") else data_dir / "scope_state.json"
        state_file.write_text('{"disabled_scopes": ["private:x"]}', encoding="utf-8")
        store = main.PluginStateStore(data_dir)
        self.assertFalse(store.is_scope_enabled("private:x"))
        self.assertFalse(store.is_private_scope("private:x"))


if __name__ == "__main__":
    unittest.main()
