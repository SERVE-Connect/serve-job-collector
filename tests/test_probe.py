import json, os, sys, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import probe

probe.PAUSE = 0

WORKDAY_PAGE = '<html><a href="https://acme.wd3.myworkdayjobs.com/en-US/AcmeCareers">Jobs</a>' + "x" * 5000 + "</html>"
LD_PAGE = ('<html><head><script type="application/ld+json">{"@graph":[{"@type":"JobPosting","title":"A"},'
           '{"@type":"JobPosting","title":"B"}]}</script></head>' + "x" * 5000 + "</html>")
RSS = ('<rss><channel><item><title>Laravel Dev</title><pubDate>Mon, 02 Nov 2026 08:00:00 GMT</pubDate>'
       '<link>https://employer.example/apply/1</link></item><item><title>B</title></item></channel></rss>')
ATOM = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title><updated>2026-11-01</updated><link href="https://x.example/j"/></entry></feed>'
JSON_FEED = json.dumps({"jobs": [{"title": "Dev", "publication_date": "2026-11-01", "url": "https://remotive.com/j/1"}]})


class Probe(unittest.TestCase):
    def test_ats_and_suggestion(self):
        a = probe.analyse_page(WORKDAY_PAGE, "https://x.example")
        self.assertIn("workday", a["ats"])
        self.assertEqual(a["suggest"]["workday"], {"host": "acme.wd3.myworkdayjobs.com", "tenant": "acme",
                                                   "site": "AcmeCareers", "search": "India"})

    def test_jobposting_and_feed_links(self):
        html = LD_PAGE.replace("<head>", '<head><link rel="alternate" type="application/rss+xml" href="/jobs.rss">')
        a = probe.analyse_page(html, "https://x.example/jobs")
        self.assertEqual(a["jobposting"], 2)
        self.assertEqual(a["feeds"], ["https://x.example/jobs.rss"])

    def test_feed_formats(self):
        r = probe.parse_feed(RSS.encode())
        self.assertEqual((r["kind"], r["count"], r["sample"]["link"]), ("xml", 2, "https://employer.example/apply/1"))
        self.assertEqual(probe.parse_feed(ATOM.encode())["sample"]["link"], "https://x.example/j")
        self.assertEqual(probe.parse_feed(JSON_FEED.encode())["count"], 1)
        self.assertIsNone(probe.parse_feed(b"<html><body>hello</body></html>"))
        self.assertIsNone(probe.parse_feed(b"not a feed"))

    def test_script_rendered_page_has_no_source(self):
        a = probe.analyse_page("<html><div id=\"root\"></div></html>", "https://x.example")
        self.assertTrue(a["js_only"] and not a["ats"] and not a["jobposting"])


class Handler(BaseHTTPRequestHandler):
    routes = {
        "/robots.txt": (200, "User-agent: *\nDisallow: /private\n"),
        "/wd": (200, WORKDAY_PAGE), "/ld": (200, LD_PAGE), "/spa": (200, "<html><div id=\"root\"></div></html>"),
        "/feed": (200, RSS), "/blogfeed": (200, RSS.replace("employer.example/apply/1", "me.example/blog/post")), "/private/jobs": (200, WORKDAY_PAGE),
    }

    def do_GET(self):
        code, body = self.routes.get(self.path, (404, ""))
        self.send_response(code); self.end_headers(); self.wfile.write(body.encode())

    def log_message(self, *a):
        pass


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def run_t(self, path, **kw):
        kw.setdefault("guess_feeds", False)
        return probe.probe_target(dict(name="t", urls=[self.base + path], **kw), "company")

    def test_verdicts(self):
        self.assertTrue(self.run_t("/wd")["verdict"].startswith("ATS FOUND: workday"))
        self.assertTrue(self.run_t("/ld")["verdict"].startswith("JobPosting"))
        self.assertTrue(self.run_t("/spa")["verdict"].startswith("NO MACHINE-READABLE"))
        self.assertTrue(self.run_t("/nope")["verdict"].startswith("UNREACHABLE"))

    def test_feed_guess_found_and_link_host_reported(self):
        r = self.run_t("/spa", guess_feeds=True)  # /feed is guessed from the site root
        self.assertTrue(r["verdict"].startswith("FEED OK: 2 jobs"), r["verdict"])
        self.assertIn("employer.example", r["verdict"])

    def test_blog_feed_and_foreign_feed_are_not_job_feeds(self):
        r = self.run_t("/spa", feeds=[self.base + "/blogfeed"])
        self.assertTrue(r["verdict"].startswith("NO JOB FEED") and "blog" in r["verdict"], r["verdict"])
        other = probe.probe_target(dict(name="t", urls=["http://localhost:%d/spa" % self.srv.server_port],
                                        feeds=[self.base + "/feed"], guess_feeds=False), "remote")
        self.assertIn("another site", other["verdict"])

    def test_board_pages_give_no_ats_suggestion(self):
        r = probe.probe_target(dict(name="t", urls=[self.base + "/wd"], guess_feeds=False), "remote")
        self.assertEqual(r["suggest"], {})

    def test_robots_disallow_is_respected(self):
        r = self.run_t("/private/jobs")
        self.assertEqual(r["pages"][0]["status"], "blocked by robots.txt")
        self.assertTrue(r["verdict"].startswith("BLOCKED"))

    def test_report_renders(self):
        md = probe.markdown([self.run_t("/wd")])
        self.assertIn("suggested companies.json entry", md)


if __name__ == "__main__":
    unittest.main()
