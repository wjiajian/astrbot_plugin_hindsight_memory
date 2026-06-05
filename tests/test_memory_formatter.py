import unittest

from memory_formatter import format_recall_results


class MemoryFormatterTests(unittest.TestCase):
    def test_empty_results_return_empty_string(self):
        self.assertEqual(format_recall_results({"results": []}, 5), "")

    def test_formats_multiple_result_shapes(self):
        raw = {
            "results": [
                {"text": " Alice likes concise replies. "},
                {"content": "Bob prefers morning meetings."},
                {"memory": {"text": "Nested memory works."}},
            ]
        }

        formatted = format_recall_results(raw, 2)

        self.assertIn("<hindsight_memory>", formatted)
        self.assertIn("- Alice likes concise replies.", formatted)
        self.assertIn("- Bob prefers morning meetings.", formatted)
        self.assertNotIn("Nested memory works.", formatted)

    def test_truncates_long_memory(self):
        formatted = format_recall_results({"results": [{"text": "x" * 20}]}, 1, item_max_chars=10)

        self.assertIn("- xxxxxxx...", formatted)

    def test_truncated_text_never_exceeds_max_chars(self):
        formatted = format_recall_results({"results": [{"text": "x" * 20}]}, 1, item_max_chars=10)
        text = formatted.splitlines()[1].removeprefix("- ")

        self.assertLessEqual(len(text), 10)

    def test_tiny_truncate_limits_are_defensive(self):
        formatted = format_recall_results({"results": [{"text": "abcdef"}]}, 1, item_max_chars=2)

        self.assertIn("- ..", formatted)

    def test_ignores_raw_json_without_text_fields(self):
        formatted = format_recall_results({"results": [{"score": 0.9}]}, 5)

        self.assertEqual(formatted, "")

    def test_cyclic_nested_memory_does_not_recurse_forever(self):
        memory = {}
        memory["memory"] = memory

        formatted = format_recall_results({"results": [memory]}, 5)

        self.assertEqual(formatted, "")

    def test_too_deep_nested_memory_is_ignored(self):
        raw = {"results": [{"memory": {"memory": {"memory": {"memory": {"memory": {"text": "too deep"}}}}}}]}

        formatted = format_recall_results(raw, 5)

        self.assertEqual(formatted, "")

    def test_max_extract_depth_can_be_configured(self):
        raw = {"results": [{"memory": {"memory": {"memory": {"memory": {"memory": {"text": "now visible"}}}}}}]}

        formatted = format_recall_results(raw, 5, max_extract_depth=5)

        self.assertIn("now visible", formatted)

    def test_empty_memory_branch_falls_back_to_observation_branch(self):
        raw = {
            "results": [
                {
                    "memory": {"score": 0.9},
                    "observation": {"text": "Observation text should survive."},
                }
            ]
        }

        formatted = format_recall_results(raw, 5)

        self.assertIn("Observation text should survive.", formatted)


if __name__ == "__main__":
    unittest.main()
