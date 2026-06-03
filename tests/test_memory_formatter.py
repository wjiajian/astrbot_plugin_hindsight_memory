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

        self.assertIn("- xxxxxxxxx...", formatted)

    def test_ignores_raw_json_without_text_fields(self):
        formatted = format_recall_results({"results": [{"score": 0.9}]}, 5)

        self.assertEqual(formatted, "")


if __name__ == "__main__":
    unittest.main()
