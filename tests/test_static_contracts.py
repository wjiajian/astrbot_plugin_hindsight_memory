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

    def test_plugin_modules_do_not_use_absolute_import_fallbacks(self):
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")
        commands_source = (ROOT / "commands.py").read_text(encoding="utf-8")

        self.assertIn("from .commands import", main_source)
        self.assertIn("from .memory_formatter import", commands_source)
        self.assertNotIn("from commands import", main_source)
        self.assertNotIn("from memory_formatter import", commands_source)
        self.assertNotIn("except ImportError", main_source)
        self.assertNotIn("except ImportError", commands_source)


if __name__ == "__main__":
    unittest.main()
