"""Owner routing and persistence regressions, without loading the AstrBot entrypoint."""
import ast
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from astrbot_plugin_hindsight_memory import commands, scope

SENDER = "sample-owner"
PLATFORM = "sample-qq"


def event(platform=PLATFORM, sender=SENDER, private=True, admin=False):
    return SimpleNamespace(
        get_platform_name=lambda: "onebot",
        get_platform_id=lambda: platform,
        get_sender_id=lambda: sender,
        get_group_id=lambda: "",  # Some group events really do lack a group ID.
        is_private_chat=lambda: private,
        is_admin=lambda: admin,
        unified_msg_origin=f"{platform}:example:{sender}",
    )


class RoutingTests(unittest.TestCase):
    def config(self, **overrides):
        return {"bank_id": "local", "shared_bank_id": "shared", "owner_platform_id": PLATFORM,
                "owner_user_ids": SENDER, **overrides}

    def plan(self, evt=None, mode: bool | None = False, config=None, admins=()):
        from astrbot_plugin_hindsight_memory.routing import owner_mode_key, plan_memory_route
        evt = event() if evt is None else evt
        config = self.config() if config is None else config
        scopes = scope.build_scopes_from_event(evt, "example-salt")
        key = owner_mode_key(evt, scopes, config, admins)
        return scopes, plan_memory_route(scopes, config, key, mode)

    def test_private_local_reads_and_writes_keep_scope_tags(self):
        scopes, plan = self.plan(mode=True)
        self.assertEqual(plan.read_targets, (("local", tuple(scopes.primary.tags)), ("shared", ())))
        self.assertEqual(plan.write_bank, "local")
        self.assertEqual(plan.write_scopes[0].tags, scopes.primary.tags)

    def test_normal_owner_uses_untagged_shared_bank_but_original_switch_key(self):
        scopes, plan = self.plan()
        self.assertEqual(plan.read_targets, (("shared", ()),))
        self.assertEqual(plan.write_bank, "shared")
        self.assertEqual(plan.write_scopes[0].tags, [])
        self.assertEqual(plan.primary.scope_key, scopes.primary.scope_key)

    def test_explicit_owner_list_overrides_admin_role(self):
        _, plan = self.plan(event(sender="not-listed", admin=True), admins=("not-listed",))
        self.assertEqual(plan.write_bank, "local")

    def test_self_asserted_webchat_identity_is_not_owner(self):
        evt = event()
        evt.get_platform_name = lambda: "webchat"
        _, plan = self.plan(evt)
        self.assertEqual(plan.write_bank, "local")
        self.assertIsNone(plan.mode_key)

    def test_same_id_on_another_adapter_is_not_owner(self):
        for ids in (SENDER, ""):
            with self.subTest(ids=ids):
                _, plan = self.plan(event(platform="other", admin=True), config=self.config(owner_user_ids=ids), admins=(SENDER,))
                self.assertEqual(plan.write_bank, "local")

    def test_fallback_global_admin_without_event_role(self):
        _, plan = self.plan(config=self.config(owner_user_ids=""), admins=(SENDER,))
        self.assertEqual(plan.write_bank, "shared")

    def test_group_without_group_id_never_enters_owner_route(self):
        _, plan = self.plan(event(private=False, admin=True))
        self.assertEqual(plan.write_bank, "local")
        self.assertIsNone(plan.mode_key)

    def test_unconfigured_or_identical_banks_leave_legacy_routing_untouched(self):
        for shared in ("", "local"):
            with self.subTest(shared=shared):
                original, plan = self.plan(config=self.config(shared_bank_id=shared))
                self.assertIsNone(plan.mode_key)
                self.assertEqual(plan.read_targets, (("local", tuple(original.primary.tags)),))
                self.assertEqual(plan.write_scopes, tuple(original.retain_scopes))

    def test_unknown_privacy_state_disables_shared_reads_and_writes(self):
        scopes, plan = self.plan(mode=None)
        self.assertEqual(plan.read_targets, (("local", tuple(scopes.primary.tags)),))
        self.assertEqual(plan.write_bank, "local")

    def test_turn_plan_does_not_follow_later_mode_change(self):
        _, pending = self.plan(mode=True)
        _, following = self.plan(mode=False)
        self.assertEqual((pending.write_bank, following.write_bank), ("local", "shared"))


class StateTests(unittest.TestCase):
    def test_legacy_off_stays_off_and_private_mode_is_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = commands.PluginStateStore(Path(tmp))
            store.state_path.write_text('{"disabled_scopes":["private:old"]}', encoding="utf-8")
            self.assertFalse(store.is_private_scope("owner-private:new"))
            store.set_private_scope("owner-private:new", True)
            reopened = commands.PluginStateStore(Path(tmp))
            self.assertFalse(reopened.is_scope_enabled("private:old"))
            self.assertTrue(reopened.is_private_scope("owner-private:new"))

    def test_private_conversation_marker_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = commands.PluginStateStore(Path(tmp))
            store.mark_private_conversation("conv-private", True)
            reopened = commands.PluginStateStore(Path(tmp))
            self.assertIs(reopened.is_private_conversation("conv-private"), True)
            self.assertIs(reopened.is_private_conversation("conv-shared"), False)
            reopened.mark_private_conversation("conv-private", False)
            self.assertIs(commands.PluginStateStore(Path(tmp)).is_private_conversation("conv-private"), False)

    def test_erased_or_reset_state_is_unknown_not_normal(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = commands.PluginStateStore(Path(tmp))
            store.set_private_scope("owner-private:test", True)
            store.state_path.unlink()
            self.assertIsNone(commands.PluginStateStore(Path(tmp)).is_private_scope("owner-private:test"))
            store.state_path.write_text("{}", encoding="utf-8")
            self.assertIsNone(commands.PluginStateStore(Path(tmp)).is_private_scope("owner-private:test"))

    def test_corrupt_file_never_reports_normal_mode_or_gets_overwritten(self):
        for content in ("{", "[]", '{"private_scopes":null}'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                store = commands.PluginStateStore(Path(tmp))
                store.state_path.write_text(content, encoding="utf-8")
                self.assertIsNone(store.is_private_scope("owner-private:test"))
                with self.assertRaises(OSError):
                    store.set_private_scope("owner-private:test", False)
                self.assertEqual(store.state_path.read_text(encoding="utf-8"), content)


class MultiBankRecallTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_failure_in_either_bank_preserves_other_result_with_guidance(self):
        from astrbot_plugin_hindsight_memory.hindsight_client import HindsightClientError
        from astrbot_plugin_hindsight_memory.memory_formatter import GUIDANCE_LINE
        for failing in ("local", "shared"):
            calls = []

            async def recall(*, bank_id, query, tags):
                calls.append((bank_id, tags))
                if bank_id == failing:
                    raise HindsightClientError("bank unavailable", status_code=404)
                return {"results": [{"text": "surviving memory"}]}

            result = await commands.run_recall_for_targets(
                SimpleNamespace(recall=recall), (("local", ("private-tag",)), ("shared", ())),
                "question", limit=1, guidance=True,
            )
            self.assertEqual(calls, [("local", ["private-tag"]), ("shared", [])])
            self.assertIn("surviving memory", result)
            self.assertEqual(result.count(GUIDANCE_LINE), 1)

    async def test_combines_duplicate_ranks_before_applying_one_global_limit(self):
        async def recall(*, bank_id, query, tags):
            return {"results": [{"text": bank_id}, {"text": "common result"}]}

        result = await commands.run_recall_for_targets(
            SimpleNamespace(recall=recall), (("local", ("private-tag",)), ("shared", ())),
            "question", limit=1,
        )
        self.assertEqual([line for line in result.splitlines() if line.startswith("- ")], ["- common result"])


class RuntimeWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "HindsightMemoryPlugin")
        cls.methods = {method.name: ast.unparse(method) for method in plugin.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def test_waiting_hook_snapshots_before_the_session_lock(self):
        waiting = self.methods["on_waiting_llm_request"]
        self.assertIn("_snapshot_plan", waiting)
        self.assertIn("TURN_ROUTE_EXTRA_KEY", waiting)

    def test_request_captures_and_response_uses_same_plan_for_dedupe_and_write(self):
        request = self.methods["on_llm_request"]
        response = self.methods["on_llm_response"]
        self.assertIn("_downgrade_to_local", request)
        self.assertIn("is_private_conversation", request)
        self.assertIn("TURN_ROUTE_EXTRA_KEY", request)
        self.assertIn("TURN_ROUTE_EXTRA_KEY", response)
        self.assertIn("bank_id=plan.write_bank", response)
        self.assertIn("decision, plan.write_bank)", response)

    def test_both_mode_commands_use_authorization_and_reset_before_persisting(self):
        self.assertIn("self._switch_private_mode(event, True)", self.methods["go_private"])
        self.assertIn("self._switch_private_mode(event, False)", self.methods["end_private"])
        switch = self.methods["_switch_private_mode"]
        self.assertIn("if not mode_key", switch)
        self.assertLess(switch.index("await self._reset_context"), switch.index("self.store.set_private_scope"))

    def test_manual_and_automatic_recall_share_bank_targets(self):
        for name in ("on_llm_request", "hindsight_recall"):
            self.assertIn("plan.read_targets", self.methods[name])
