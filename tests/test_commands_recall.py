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


class FakeHindsightClient:
    def __init__(self):
        self.calls = []

    async def recall(self, *, bank_id, query, tags):
        self.calls.append({"bank_id": bank_id, "query": query, "tags": tags})
        return {"results": [{"text": "用户喜欢冰美式。"}]}


if __name__ == "__main__":
    unittest.main()
