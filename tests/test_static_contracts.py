import ast
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
        tree = _main_tree()
        client_method = _class_method(tree, "HindsightMemoryPlugin", "_client")

        self.assertIsNotNone(client_method)
        self.assertTrue(_has_attribute(client_method, "hindsight_client_signature"))
        self.assertTrue(_calls_method(client_method, "_client_signature"))
        self.assertTrue(_awaits_aclose(client_method, "hindsight_client"))
        self.assertTrue(_instantiates(client_method, "HindsightClient"))

    def test_config_contract_includes_retention_policy(self):
        config = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))

        for key in (
            "retain_decision_mode",
            "recall_item_max_chars",
            "memory_extract_max_depth",
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
        self.assertEqual(config["recall_item_max_chars"]["default"], 360)
        self.assertEqual(config["memory_extract_max_depth"]["default"], 4)
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


def _main_tree():
    return ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))


def _class_method(tree, class_name, method_name):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.AsyncFunctionDef, ast.FunctionDef)) and item.name == method_name:
                    return item
    return None


def _has_attribute(node, attr_name):
    return any(isinstance(item, ast.Attribute) and item.attr == attr_name for item in ast.walk(node))


def _calls_method(node, method_name):
    return any(
        isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and item.func.attr == method_name
        for item in ast.walk(node)
    )


def _awaits_aclose(node, client_attr):
    for item in ast.walk(node):
        if not isinstance(item, ast.Await) or not isinstance(item.value, ast.Call):
            continue
        func = item.value.func
        if not isinstance(func, ast.Attribute) or func.attr != "aclose":
            continue
        value = func.value
        if isinstance(value, ast.Attribute) and value.attr == client_attr:
            return True
    return False


def _instantiates(node, class_name):
    return any(isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == class_name for item in ast.walk(node))


if __name__ == "__main__":
    unittest.main()
