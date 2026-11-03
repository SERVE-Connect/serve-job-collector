import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import collector


class Requirements(unittest.TestCase):
    def test_heading_at_sentence_start_is_used(self):
        t = "<p>We build things.</p><p>Requirements: 3+ years of Java and SQL. Bachelor degree.</p>"
        self.assertTrue(collector.parse_requirements(t).startswith("3+ years of Java"))

    def test_heading_word_inside_a_sentence_is_ignored(self):
        t = "They need strong leadership skills and coordinating team resources. If the role has reports, they lead them."
        self.assertEqual(collector.parse_requirements(t), "")

    def test_prose_skills_then_real_heading_uses_the_real_one(self):
        t = "Great leadership skills and a team of friends. Key Skills: Python, Spark, Airflow."
        self.assertTrue(collector.parse_requirements(t).startswith("Python, Spark"))

    def test_text_starting_with_heading(self):
        self.assertTrue(collector.parse_requirements("Qualifications: B.Tech in CS").startswith("B.Tech"))

    def test_never_starts_mid_sentence_after_a_bullet_heading(self):
        t = "Responsibilities · Build pipelines · Qualifications · Bachelor degree in Engineering"
        self.assertTrue(collector.parse_requirements(t).startswith("Bachelor degree"))


if __name__ == "__main__":
    unittest.main()
