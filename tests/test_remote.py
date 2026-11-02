import os, sys, unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import collector

def rfc(days_ago):
    return format_datetime(datetime.now(timezone.utc) - timedelta(days=days_ago))

WWR = """<?xml version="1.0"?><rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item><title>Acme Corp: Senior Python Developer</title><region>Anywhere in the World</region><pubDate>%s</pubDate>
<link>https://weworkremotely.com/remote-jobs/acme-senior-python</link><guid>https://weworkremotely.com/remote-jobs/acme-senior-python</guid>
<description>&lt;p&gt;Requirements: 5 years of Python. Bachelor degree. Salary: $90,000 - $120,000 per year&lt;/p&gt;</description></item>
<item><title>Old: Role</title><pubDate>%s</pubDate><link>https://weworkremotely.com/remote-jobs/old</link></item>
<item><title>NoDate: Role</title><link>https://weworkremotely.com/remote-jobs/nodate</link></item>
<item><title>NoLink: Role</title><pubDate>%s</pubDate></item>
</channel></rss>""" % (rfc(1), rfc(30), rfc(1))

LARA = """<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item><title>Laravel Dev - US Only</title>
<dc:creator>jobs@bigco.example (BigCo)</dc:creator><pubDate>%s</pubDate><link>https://larajobs.com/job/1</link></item></channel></rss>""" % rfc(2)

WP = """<rss><channel><item><title>Fix my plugin</title><pubDate>%s</pubDate><link>https://jobs.wordpress.net/job/fix</link>
<description>Need help</description></item></channel></rss>""" % rfc(0)


class Remote(unittest.TestCase):
    def test_wwr_company_from_title_and_stated_fields(self):
        rows, undated = collector.parse_remote_items(WWR, {"name": "WWR", "key": "wwr", "title_has_company": True})
        self.assertEqual(undated, 1)
        self.assertEqual(len(rows), 2)  # the old one is parsed here and dropped later by the window
        r = rows[0]
        self.assertEqual((r["company"], r["title"], r["location"]), ("Acme Corp", "Senior Python Developer", "Anywhere in the World"))
        self.assertEqual(r["qualification"], "Bachelor")
        self.assertIn("$90,000", r["salary"])
        self.assertEqual(r["source"], "remote-board")

    def test_company_from_creator_without_email_and_never_guessed(self):
        r = collector.parse_remote_items(LARA, {"name": "Laravel Jobs", "key": "larajobs"})[0][0]
        self.assertEqual(r["company"], "BigCo")
        r = collector.parse_remote_items(WP, {"name": "WordPress Jobs", "key": "wpjobs"})[0][0]
        self.assertEqual((r["company"], r["location"], r["salary"], r["qualification"]), ("", "", "", ""))

    def test_collect_applies_window_and_reports(self):
        orig = collector.http_text
        collector.http_text = lambda url, **k: WWR
        try:
            jobs, report = collector.collect_remote({"remote_boards": [
                {"name": "We Work Remotely", "key": "wwr", "feed": "x", "title_has_company": True}]})
        finally:
            collector.http_text = orig
        self.assertEqual([j["company"] for j in jobs], ["Acme Corp"])
        self.assertEqual(report["remote:We Work Remotely"], {"ok": True, "listed": 3, "kept": 1, "undated_skipped": 1, "without_company": 0})

    def test_feed_failure_is_reported_not_raised(self):
        orig = collector.http_text
        def boom(url, **k): raise RuntimeError("HTTP 403")
        collector.http_text = boom
        try:
            jobs, report = collector.collect_remote({"remote_boards": [{"name": "X", "key": "x", "feed": "x"}]})
        finally:
            collector.http_text = orig
        self.assertEqual(jobs, [])
        self.assertFalse(report["remote:X"]["ok"])

if __name__ == "__main__":
    unittest.main()
