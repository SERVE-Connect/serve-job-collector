import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import collector


class Description(unittest.TestCase):
    def test_keeps_paragraphs_and_bullets_as_lines_without_tags(self):
        t = "<p>Build <b>data</b> pipelines.</p><ul><li>Python &amp; SQL</li><li>3+ years</li></ul><br/>Pune office"
        self.assertEqual(collector.describe(t), "Build data pipelines.\n• Python & SQL\n• 3+ years\nPune office")

    def test_long_text_is_cut_at_a_word_with_an_ellipsis(self):
        out = collector.describe("word " * 1000, limit=100)
        self.assertLessEqual(len(out), 101)
        self.assertTrue(out.endswith("…"))
        self.assertFalse(out[:-1].endswith(" "))

    def test_empty_and_none(self):
        self.assertEqual(collector.describe(""), "")
        self.assertEqual(collector.describe(None), "")

    def test_json_rows_carry_the_description(self):
        self.assertIn("description", collector.JSON_EXTRA)


if __name__ == "__main__":
    unittest.main()
