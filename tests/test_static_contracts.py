import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StaticContractTests(unittest.TestCase):
    def test_main_does_not_mock_astrbot_runtime_imports(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertNotIn("AstrBotConfig = dict", source)
        self.assertNotIn("_NoopFilter", source)
        self.assertNotIn("_NoopCommandGroup", source)
        self.assertNotIn("TextPart = None", source)

    def test_main_uses_startools_data_dir(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("StarTools", source)
        self.assertIn("StarTools.get_data_dir()", source)
        self.assertNotIn("get_astrbot_data_path", source)
        self.assertNotIn("\".data\"", source)

    def test_main_keeps_framework_listener_signature_and_textpart_check_clean(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("def hindsight(self, event: AstrMessageEvent):", source)
        self.assertNotIn("TextPart is None", source)

    def test_main_uses_config_aware_async_client_factory(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("async def _client(self) -> HindsightClient:", source)
        self.assertIn("self.hindsight_client_signature", source)
        self.assertIn("await self.hindsight_client.aclose()", source)
        self.assertNotIn("self.hindsight_client = HindsightClient(\n            api_base=str(self.config.get", source)

    def test_config_contract_includes_retention_policy(self):
        config = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))

        for key in (
            "retain_decision_mode",
            "retain_min_chars",
            "retain_sensitive_requires_explicit",
            "retain_ai_enabled",
            "retain_ai_provider_id",
            "retain_ai_fallback_to_current_provider",
            "retain_ai_min_confidence",
            "retain_dedupe_enabled",
            "retain_dedupe_threshold",
            "retain_dedupe_limit",
            "retain_write_raw_conversation",
        ):
            self.assertIn(key, config)
        self.assertEqual(config["retain_decision_mode"]["default"], "balanced")
        self.assertEqual(config["retain_min_chars"]["default"], 8)
        self.assertIs(config["retain_sensitive_requires_explicit"]["default"], True)
        self.assertIs(config["retain_ai_enabled"]["default"], False)
        self.assertEqual(config["retain_ai_provider_id"]["default"], "")
        self.assertEqual(config["retain_ai_provider_id"]["_special"], "select_provider")
        self.assertIs(config["retain_ai_fallback_to_current_provider"]["default"], False)
        self.assertEqual(config["retain_ai_min_confidence"]["default"], 0.7)
        self.assertIs(config["retain_dedupe_enabled"]["default"], True)
        self.assertEqual(config["retain_dedupe_threshold"]["default"], 0.85)
        self.assertEqual(config["retain_dedupe_limit"]["default"], 5)
        self.assertIs(config["retain_write_raw_conversation"]["default"], False)

    def test_ai_retention_uses_selectable_llm_provider(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("retain_ai_provider_id", source)
        self.assertIn("get_current_chat_provider_id", source)
        self.assertIn("llm_generate", source)
        self.assertIn("chat_provider_id", source)
        self.assertNotIn("text_chat", source)
        self.assertNotIn("get_using_provider", source)

    def test_plugin_modules_do_not_use_absolute_import_fallbacks(self):
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")
        commands_source = (ROOT / "commands.py").read_text(encoding="utf-8")

        self.assertIn("from .commands import", main_source)
        self.assertIn("from .retention_policy import", main_source)
        self.assertIn("from .memory_formatter import", commands_source)
        self.assertNotIn("from commands import", main_source)
        self.assertNotIn("from retention_policy import", main_source)
        self.assertNotIn("from memory_formatter import", commands_source)
        self.assertNotIn("except ImportError", main_source)
        self.assertNotIn("except ImportError", commands_source)


if __name__ == "__main__":
    unittest.main()
