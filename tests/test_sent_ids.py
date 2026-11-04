import os, sys, unittest
from datetime import date
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import collector

TODAY = date(2026, 11, 4)


class SentIds(unittest.TestCase):
    def test_normal_lines_inside_seven_days_are_kept(self):
        ids, keep = collector.parse_sent(["# note", "", "2026-10-31 JR1 R-2", "2026-11-03 744000158 JR3"], TODAY)
        self.assertEqual(ids, {"JR1", "R-2", "744000158", "JR3"})
        self.assertEqual(keep, ["# note", "", "2026-10-31 JR1 R-2", "2026-11-03 744000158 JR3"])

    def test_lines_older_than_seven_days_are_dropped(self):
        ids, keep = collector.parse_sent(["2026-10-27 OLD1", "2026-10-28 EDGE"], TODAY)
        self.assertEqual(ids, {"EDGE"})            # exactly 7 days old still counts
        self.assertEqual(keep, ["2026-10-28 EDGE"])

    def test_two_digit_year_is_read_as_20yy_and_the_line_is_rewritten(self):
        ids, keep = collector.parse_sent(["26-10-29 JR2028457 26996280"], TODAY)
        self.assertEqual(ids, {"JR2028457", "26996280"})
        self.assertEqual(keep, ["2026-10-29 JR2028457 26996280"])

    def test_a_line_without_a_date_counts_as_sent_today_and_gets_a_date(self):
        ids, keep = collector.parse_sent(["8ef474ea-ea67-4cd4-bcd4-af702e493c52, 744000157048299, JR347355"], TODAY)
        self.assertEqual(ids, {"8ef474ea-ea67-4cd4-bcd4-af702e493c52", "744000157048299", "JR347355"})  # no trailing commas
        self.assertEqual(keep, ["2026-11-04 8ef474ea-ea67-4cd4-bcd4-af702e493c52 744000157048299 JR347355"])

    def test_commas_and_extra_spaces_between_ids_are_fine(self):
        ids, keep = collector.parse_sent(["2026-11-01  A,  B ,C"], TODAY)
        self.assertEqual(ids, {"A", "B", "C"})
        self.assertEqual(keep, ["2026-11-01 A B C"])

    def test_a_future_or_unreadable_date_is_not_silently_trusted(self):
        # "2026-13-45 X" is not a date: the whole line is treated as a dateless line of ids (today)
        ids, keep = collector.parse_sent(["2026-13-45 X"], TODAY)
        self.assertEqual(ids, {"2026-13-45", "X"})
        self.assertEqual(keep, ["2026-11-04 2026-13-45 X"])


if __name__ == "__main__":
    unittest.main()


class SiteRegister(unittest.TestCase):
    DOC = {"fields": {"data": {"stringValue": '{"R-1": "2026-11-04", "collector-amazon_ab12": "2026-11-04", "JR9": "2026-11-02"}'}}}

    def test_reads_the_firestore_rest_document(self):
        self.assertEqual(collector.parse_site_register(self.DOC),
                         {"R-1": "2026-11-04", "collector-amazon_ab12": "2026-11-04", "JR9": "2026-11-02"})

    def test_a_missing_or_broken_document_gives_nothing(self):
        for bad in ({}, {"fields": {}}, {"fields": {"data": {"stringValue": "not json"}}}, None):
            self.assertEqual(collector.parse_site_register(bad), {})

    def test_only_new_ids_become_dated_lines(self):
        lines = collector.site_sent_lines({"R-1": "2026-11-04", "JR9": "2026-11-02", "NEW": "2026-11-04"}, existing={"R-1"})
        self.assertEqual(lines, ["2026-11-02 JR9", "2026-11-04 NEW"])

    def test_nothing_new_nothing_added(self):
        self.assertEqual(collector.site_sent_lines({"R-1": "2026-11-04"}, existing={"R-1"}), [])

    def test_load_sent_merges_the_site_register_and_survives_a_failed_fetch(self):
        import tempfile
        d = tempfile.mkdtemp()
        old_sent, old_data, old_fetch = collector.SENT, collector.DATA, collector.fetch_site_register
        try:
            collector.DATA, collector.SENT = d, os.path.join(d, "sent_ids.txt")
            today = collector.NOW.date().isoformat()
            open(collector.SENT, "w").write(f"{today} A B\n")
            collector.fetch_site_register = lambda: {"B": today, "C": today}
            self.assertEqual(collector.load_sent(), {"A", "B", "C"})
            self.assertIn(f"{today} C", open(collector.SENT).read())
            def boom(): raise OSError("offline")
            collector.fetch_site_register = boom
            self.assertEqual(collector.load_sent(), {"A", "B", "C"})   # the file alone is still enough
        finally:
            collector.SENT, collector.DATA, collector.fetch_site_register = old_sent, old_data, old_fetch
