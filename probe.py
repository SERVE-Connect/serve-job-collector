#!/usr/bin/env python3
"""Probe candidate job sources and report which ones can be read automatically.

For each target in probe_targets.json it makes a handful of polite requests (robots.txt is
respected, 1.5 s between requests, one page plus a few feed guesses) and reports:
  - which applicant tracking system (ATS) the careers page uses, with a ready companies.json entry
  - whether the page carries JobPosting markup (schema.org JSON-LD)
  - whether an RSS / Atom / JSON feed exists, how many jobs it lists, and where its links point
Targets can set "guess_feeds": false. Nothing is written to the job data. Run:  python probe.py [--targets probe_targets.json]
Standard library only.
"""
import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib import error, parse, request, robotparser

UA = "SERVE-job-probe/1.0 (+https://github.com/SERVE-Connect/serve-job-collector)"
PAUSE = 1.5
MAX_BYTES = 1_500_000
FEED_GUESSES = ["/feed", "/feed/", "/rss", "/jobs.rss", "/feed.xml"]

ATS_PATTERNS = {
    "workday": r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com",
    "successfactors": r"(?:successfactors\.(?:com|eu)|jobs2web\.com)",
    "phenom": r"phenompeople\.com|phenom\.com",
    "taleo": r"taleo\.net",
    "icims": r"icims\.com",
    "oracle": r"oraclecloud\.com/hcmUI|candidateexperience",
    "greenhouse": r"greenhouse\.io",
    "lever": r"jobs\.lever\.co",
    "ashby": r"ashbyhq\.com",
    "smartrecruiters": r"smartrecruiters\.com",
    "avature": r"avature\.net",
    "eightfold": r"eightfold\.ai",
    "radancy": r"radancy\.net|tmpwebeng\.com|talentbrew",
    "jobvite": r"jobvite\.com",
    "workable": r"workable\.com",
}


def get(url, timeout=20):
    req = request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with request.urlopen(req, timeout=timeout) as r:
            return {"status": r.status, "url": r.geturl(), "ctype": r.headers.get("Content-Type", ""),
                    "body": r.read(MAX_BYTES)}
    except error.HTTPError as e:
        return {"status": e.code, "url": url, "ctype": "", "body": b""}
    except Exception as e:  # DNS, TLS, timeout
        return {"status": 0, "url": url, "ctype": "", "body": b"", "error": str(e)[:120]}


def allowed(url):
    """True unless the site's robots.txt disallows this URL for us. Unknown counts as allowed."""
    p = parse.urlsplit(url)
    r = get("%s://%s/robots.txt" % (p.scheme, p.netloc), timeout=10)
    time.sleep(PAUSE)
    if r["status"] != 200:
        return True
    rp = robotparser.RobotFileParser()
    rp.parse(r["body"].decode("utf-8", "replace").splitlines())
    return rp.can_fetch(UA, url)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.feeds, self.ld = [], []
        self._ld = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and "alternate" in (a.get("rel") or "") and \
                re.search(r"rss|atom|json", a.get("type") or "", re.I) and a.get("href"):
            self.feeds.append(a["href"])
        if tag == "script" and "ld+json" in (a.get("type") or ""):
            self._ld, self._buf = True, []

    def handle_data(self, data):
        if self._ld:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._ld:
            self._ld = False
            self.ld.append("".join(self._buf))


def _types(node):
    if isinstance(node, dict):
        t = node.get("@type")
        yield from (t if isinstance(t, list) else [t])
        for v in node.values():
            yield from _types(v)
    elif isinstance(node, list):
        for v in node:
            yield from _types(v)


def analyse_page(html, base):
    p = _Links()
    try:
        p.feed(html)
    except Exception:
        pass
    postings = 0
    for blob in p.ld:
        try:
            postings += sum(1 for t in _types(json.loads(blob)) if t == "JobPosting")
        except ValueError:
            pass
    ats = {}
    for name, pat in ATS_PATTERNS.items():
        if re.search(pat, html, re.I):
            ats[name] = True
    return {"ats": sorted(ats), "jobposting": postings,
            "feeds": [parse.urljoin(base, f) for f in p.feeds],
            "js_only": len(html) < 4000 or "__NEXT_DATA__" in html or 'id="root"></div>' in html,
            "suggest": suggest(html)}


def suggest(html):
    """Ready-to-paste companies.json entries for the ATS tokens found in the page."""
    out = {}
    m = re.search(r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", html)
    if m:
        out["workday"] = {"host": "%s.%s.myworkdayjobs.com" % (m.group(1), m.group(2)),
                          "tenant": m.group(1), "site": m.group(3), "search": "India"}
    for key, pat in (("greenhouse", r"greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)"),
                     ("lever", r"jobs\.lever\.co/([a-z0-9_-]+)"),
                     ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9._-]+)"),
                     ("smartrecruiters", r"smartrecruiters\.com/(?:company/)?([A-Za-z0-9_-]+)")):
        m = re.search(pat, html)
        if m and m.group(1) not in ("embed", "v1", "boards", "api"):
            out[key] = {"token" if key != "smartrecruiters" else "company": m.group(1)}
    return out


TITLE_KEYS = ("title", "job_title", "name", "position", "text")
DATE_KEYS = ("publication_date", "published", "pubDate", "date", "created_at", "createdAt", "posted_at", "updated")
LINK_KEYS = ("url", "link", "apply_url", "applyUrl", "absolute_url", "applicationLink", "hostedUrl", "refs")


def _first(d, keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, dict):
            v = next((x for x in v.values() if isinstance(x, str)), None)
        if v:
            return str(v)
    return ""


def parse_feed(body, ctype=""):
    """Returns {kind, count, sample{title,date,link}} or None if the body is not a job feed."""
    text = body.decode("utf-8", "replace").lstrip("\ufeff").strip()
    if not text:
        return None
    if text[0] in "[{":
        try:
            data = json.loads(text)
        except ValueError:
            return None
        items = data if isinstance(data, list) else next(
            (v for k in ("jobs", "results", "data", "items", "postings") for v in [data.get(k)] if isinstance(v, list)), None)
        if not items or not isinstance(items[0], dict):
            return None
        it = items[0]
        return {"kind": "json", "count": len(items),
                "sample": {"title": _first(it, TITLE_KEYS), "date": _first(it, DATE_KEYS), "link": _first(it, LINK_KEYS)}}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    ns = lambda e: e.tag.split("}")[-1]
    items = [e for e in root.iter() if ns(e) in ("item", "entry")]
    if not items:
        return None

    def field(e, name):
        for c in e:
            if ns(c) == name:
                return (c.text or c.attrib.get("href") or "").strip()
        return ""
    it = items[0]
    return {"kind": "xml", "count": len(items),
            "sample": {"title": field(it, "title"), "date": field(it, "pubDate") or field(it, "published") or field(it, "updated"),
                       "link": field(it, "link")}}


def probe_target(t, kind):
    res = {"name": t["name"], "kind": kind, "pages": [], "feeds": [], "ats": [], "suggest": {}, "jobposting": 0}
    seen_feeds = list(t.get("feeds", []))
    for url in t["urls"]:
        page = {"url": url}
        if not allowed(url):
            page["status"] = "blocked by robots.txt"
            res["pages"].append(page)
            continue
        r = get(url)
        time.sleep(PAUSE)
        page.update(status=r["status"], final=r["url"], error=r.get("error", ""))
        if r["status"] == 200:
            a = analyse_page(r["body"].decode("utf-8", "replace"), r["url"])
            page.update(ats=a["ats"], jobposting=a["jobposting"], js_only=a["js_only"])
            res["ats"] = sorted(set(res["ats"]) | set(a["ats"]))
            res["jobposting"] += a["jobposting"]
            res["suggest"].update(a["suggest"])
            seen_feeds += a["feeds"]
            p = parse.urlsplit(r["url"])
            if t.get("guess_feeds", True) and not t.get("feeds"):
                seen_feeds += ["%s://%s%s" % (p.scheme, p.netloc, g) for g in FEED_GUESSES]
        res["pages"].append(page)
    for f in dict.fromkeys(seen_feeds):
        if not allowed(f):
            res["feeds"].append({"url": f, "status": "blocked by robots.txt"})
            continue
        r = get(f)
        time.sleep(PAUSE)
        entry = {"url": f, "status": r["status"]}
        feed = parse_feed(r["body"], r["ctype"]) if r["status"] == 200 else None
        if feed:
            host = parse.urlsplit(feed["sample"]["link"]).netloc
            own = parse.urlsplit(f).netloc.replace("www.", "")
            feed["link_host"] = host
            feed["link_is_own_site"] = (own in host.replace("www.", "")) if host else None
            entry.update(feed)
        res["feeds"].append(entry)
    res["verdict"] = verdict(res)
    return res


def verdict(r):
    good = [f for f in r["feeds"] if f.get("count")]
    if good:
        f = good[0]
        where = "links stay on the board's own site (aggregator-style)" if f.get("link_is_own_site") else \
                "links point elsewhere (%s), check they are employer pages" % f.get("link_host", "?")
        return "FEED OK: %d jobs, %s; %s" % (f["count"], f["kind"], where)
    if r["suggest"]:
        return "ATS FOUND: %s. Paste the suggested entry into companies.json" % ", ".join(r["suggest"])
    if r["ats"]:
        return "ATS FOUND: %s. No public token in the page, needs a manual look" % ", ".join(r["ats"])
    if r["jobposting"]:
        return "JobPosting markup on the page (%d). Readable without an API" % r["jobposting"]
    if any(p.get("status") == "blocked by robots.txt" for p in r["pages"]):
        return "BLOCKED by robots.txt. Skip"
    if all(p.get("status") in (0, None) or p.get("status", 0) >= 400 for p in r["pages"] if isinstance(p.get("status"), int)) and r["pages"]:
        return "UNREACHABLE or refused. Skip, or check the URL"
    return "NO MACHINE-READABLE SOURCE found (page is script-rendered or has no feed). Skip"


def markdown(results):
    rows = ["# Source probe", "", "| Source | Type | Verdict |", "|---|---|---|"]
    rows += ["| %s | %s | %s |" % (r["name"], r["kind"], r["verdict"]) for r in results]
    for r in results:
        rows += ["", "## %s" % r["name"]]
        for p in r["pages"]:
            rows.append("- page %s: %s%s" % (p["url"], p.get("status"), " (%s)" % p["error"] if p.get("error") else ""))
        for f in r["feeds"]:
            s = f.get("sample", {})
            rows.append("- feed %s: %s%s" % (f["url"], f["status"], (", %s items, e.g. %r dated %r -> %s" % (
                f["count"], s.get("title"), s.get("date"), s.get("link"))) if f.get("count") else ""))
        if r["suggest"]:
            rows += ["- suggested companies.json entry:", "```json", json.dumps(r["suggest"], indent=1), "```"]
    return "\n".join(rows) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_targets.json"))
    ap.add_argument("--out", default="probe_report")
    a = ap.parse_args()
    cfg = json.load(open(a.targets, encoding="utf-8"))
    results = []
    for kind in ("company", "remote"):
        for t in cfg.get(kind, []):
            print("probing", t["name"], flush=True)
            results.append(probe_target(t, kind))
    md = markdown(results)
    open(a.out + ".md", "w", encoding="utf-8").write(md)
    json.dump(results, open(a.out + ".json", "w", encoding="utf-8"), indent=1)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        open(summary, "a", encoding="utf-8").write(md)
    print(md)


if __name__ == "__main__":
    sys.exit(main())
