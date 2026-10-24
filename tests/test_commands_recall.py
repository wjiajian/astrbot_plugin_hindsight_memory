from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

astrbot_module = sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
api_module = sys.modules.setdefault("astrbot.api", types.ModuleType("astrbot.api"))
api_module.logger = getattr(api_module, "logger", None)
setattr(astrbot_module, "api", api_module)

from astrbot_plugin_hindsight_memory.commands import run_manual_recall_for_tag_sets
from astrbot_plugin_hindsight_memory.hindsight_client import HindsightClientError


class CommandsRecallTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_recall_uses_expanded_queries_and_dedupes_results(self):
        client = FakeHindsightClient()

        formatted = await run_manual_recall_for_tag_sets(
            client,
            bank_id="bank-1",
            query="我喜欢什么饮料",
            tag_sets=[["scope:private"]],
            limit=5,
            queries=["我喜欢什么饮料", "饮料 偏好", "饮料 偏好"],
        )

        self.assertEqual([call["query"] for call in client.calls], ["我喜欢什么饮料", "饮料 偏好"])
        self.assertEqual([call["tags"] for call in client.calls], [["scope:private"], ["scope:private"]])
        self.assertEqual(formatted.count("用户喜欢冰美式。"), 1)
        self.assertIn("<hindsight_memory>", formatted)


    async def test_manual_recall_merges_scopes_and_queries_by_rank(self):
        client = FakeHindsightClient(
            {
                ("shared", "q"): [f"群事实{i}" for i in range(5)],
                ("member", "q"): ["用户叫小王", "用户喜欢猫"],
                ("shared", "expanded"): ["群事实0"],
                ("member", "expanded"): ["用户喜欢猫"],
            }
        )

        formatted = await run_manual_recall_for_tag_sets(
            client,
            bank_id="bank-1",
            query="q",
            tag_sets=[["shared"], ["member"]],
            limit=4,
            queries=["expanded"],
        )

        lines = formatted.splitlines()[1:-1]
        self.assertEqual(len(lines), 4)
        self.assertIn("- 用户叫小王", lines)
        self.assertIn("- 用户喜欢猫", lines)
        self.assertIn("- 群事实0", lines)

    async def test_manual_recall_passes_guidance_to_formatter(self):
        client = FakeHindsightClient()

        with_guidance = await run_manual_recall_for_tag_sets(
            client, bank_id="bank-1", query="q", tag_sets=[["scope:private"]], limit=5, guidance=True
        )
        without_guidance = await run_manual_recall_for_tag_sets(
            client, bank_id="bank-1", query="q", tag_sets=[["scope:private"]], limit=5
        )

        self.assertIn("长期记忆", with_guidance)
        self.assertNotIn("长期记忆", without_guidance)

    async def test_manual_recall_tolerates_partial_failures(self):
        client = FakeHindsightClient({("member", "q"): ["用户叫小王"]}, failing_tags={"shared"})

        formatted = await run_manual_recall_for_tag_sets(
            client, bank_id="bank-1", query="q", tag_sets=[["shared"], ["member"]], limit=5
        )

        self.assertIn("用户叫小王", formatted)

    async def test_manual_recall_raises_when_all_requests_fail(self):
        client = FakeHindsightClient({}, failing_tags={"shared"})

        with self.assertRaises(HindsightClientError):
            await run_manual_recall_for_tag_sets(client, bank_id="bank-1", query="q", tag_sets=[["shared"]], limit=5)


class FakeHindsightClient:
    def __init__(self, results=None, failing_tags=()):
        self.calls = []
        self.results = results
        self.failing_tags = set(failing_tags)

    async def recall(self, *, bank_id, query, tags):
        self.calls.append({"bank_id": bank_id, "query": query, "tags": tags})
        if self.failing_tags.intersection(tags):
            raise HindsightClientError("boom")
        if self.results is None:
            return {"results": [{"text": "用户喜欢冰美式。"}]}
        return {"results": [{"text": text} for text in self.results.get((tags[0], query), [])]}


if __name__ == "__main__":
    unittest.main()
