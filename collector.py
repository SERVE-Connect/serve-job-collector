#!/usr/bin/env python3
"""SERVE daily job collector (v3).

Reads public ATS job boards listed in companies.json, keeps India jobs posted within
the last N days, checks each one is still open, estimates the experience asked for,
sorts them into sections (IT / Data / Security / ... / Non-IT) and cities, and writes:

  data/jobs_latest.md          every job, by section then city
  data/it_jobs_shortlist.md    IT sections only, for 0-5 years (fit yes / unknown)
  data/jobs_latest.json        same data for scripts
  data/run_report.json         which boards worked
  data/seen.json               job IDs seen before

Standard library only. Run:  python collector.py [--days 7]
"""
import argparse
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib import error, parse, request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
UA = "SERVE-Job-Collector/1.0 (nonprofit job awareness)"
NOW = datetime.now(timezone.utc)
PAUSE = 0.25  # seconds between calls, be polite
WINDOW = 7


# ---------------------------------------------------------------- http
def http(url, body=None, tries=3, timeout=30):
    """Return (status, json). 404/410 -> (code, None). Other failures raise."""
    headers = {"User-Agent": UA, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    last = "failed"
    for i in range(tries):
        try:
            req = request.Request(url, data=data, headers=headers)
            with request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace"))
        except error.HTTPError as e:
            if e.code in (404, 410):
                return e.code, None
            last = "HTTP %s" % e.code
            if e.code < 500 and e.code != 429:
                break
        except Exception as e:  # network, timeout, bad json
            last = str(e)[:120]
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(last)


# ---------------------------------------------------------------- places
INDIA_WORDS = [
    "pune", "pimpri", "hinjewadi", "hinjawadi", "mumbai", "navi mumbai", "thane",
    "powai", "airoli", "sambhajinagar", "aurangabad", "nashik", "nagpur", "kolhapur",
    "delhi", "noida", "gurgaon", "gurugram", "faridabad", "ghaziabad", "haryana",
    "hyderabad", "chennai", "kolkata", "ahmedabad", "gandhinagar", "bangalore",
    "bengaluru", "kochi", "coimbatore", "jaipur", "indore", "chandigarh", "mohali",
    "thiruvananthapuram", "trivandrum", "lucknow", "bhubaneswar", "vadodara", "surat",
    "mysuru", "mysore", "visakhapatnam", "bhopal", "patna",
]

# Order = the order jobs are listed in. Remote sits after the three priority cities.
CITY_GROUPS = [
    ("Pune", ("pune", "pimpri", "hinjewadi", "hinjawadi")),
    ("Mumbai", ("mumbai", "thane", "powai", "airoli")),
    ("Chhatrapati Sambhajinagar", ("sambhajinagar", "aurangabad")),
    ("Delhi NCR / Haryana", ("delhi", "noida", "gurgaon", "gurugram", "faridabad", "ghaziabad", "haryana")),
    ("Bangalore", ("bangalore", "bengaluru")),
    ("Chennai", ("chennai",)),
    ("Kolkata", ("kolkata",)),
    ("Hyderabad", ("hyderabad",)),
    ("Ahmedabad", ("ahmedabad", "gandhinagar")),
]
GROUP_ORDER = ["Pune", "Mumbai", "Chhatrapati Sambhajinagar", "Remote (India)",
               "Delhi NCR / Haryana", "Bangalore", "Chennai", "Kolkata", "Hyderabad",
               "Ahmedabad", "Other India"]


def is_india(loc):
    s = (loc or "").lower()
    if re.search(r"\bindia\b|\bind\b", s):
        return True
    return any(w in s for w in INDIA_WORDS)


def mode_of(loc, declared=""):
    """remote / hybrid / onsite / unspecified. Uses the employer's own field first."""
    d = (declared or "").strip().lower().replace("-", "")
    if d in ("remote", "hybrid", "onsite"):
        return d
    if d in ("flexible", "flex"):
        return "hybrid"
    s = (loc or "").lower()
    if "remote" in s or "virtual" in s:
        return "remote"
    return "unspecified"


def city_group(loc, mode):
    if mode == "remote":
        return "Remote (India)"
    s = (loc or "").lower()
    for name, words in CITY_GROUPS:
        if any(w in s for w in words):
            return name
    return "Other India"


def is_multi_city(loc):
    s = (loc or "").lower()
    return sum(w in s for w in INDIA_WORDS) >= 3


# ---------------------------------------------------------------- classify
DROP = re.compile(r"pooling|talent community|evergreen", re.I)
CLINICAL = re.compile(
    r"clinical|pharmacovigilance|drug safety|biostat|regulatory affairs|medical|\blab\b|"
    r"research associate", re.I)
NON_IT = re.compile(
    r"account executive|\bsales\b|marketing|recruit|talent acqui|human resources|\bhr\b|"
    r"accountant|accounting|legal|counsel|customer success|business development|"
    r"supply chain|procurement|content writer|mechanical|civil engineer|chemical|"
    r"manufacturing|field engineer|program manager|operations manager|product manager|"
    r"facility|data cent(er|re)|\bdceo\b|\bict design|hardware compute|semiconductor|"
    r"\btax\b|finance|investigat|offboarding|training and quality|coordinator", re.I)
IT_YES = re.compile(
    r"software|developer|engineer|devops|\bsre\b|site reliability|data scien|data analy|"
    r"data engineer|analytics|machine learning|\bml\b|\bai\b|genai|cloud|security|cyber|"
    r"\bsoc\b|\bqa\b|quality assurance|\btest|sdet|automation|platform|backend|back-end|"
    r"frontend|front-end|full[- ]?stack|\bjava|python|\.net|golang|react|angular|node\.?js|"
    r"android|\bios\b|mobile|database|\bdba\b|network|sysadmin|system admin|infrastructure|"
    r"it support|technical support|application support|solutions? architect|programmer|"
    r"salesforce|\bsap\b|mainframe|\betl\b|business intelligence|penetration|vulnerab|"
    r"firmware|embedded|\bsdk\b|\bapi\b|systems? (development|engineer|admin)|"
    r"support engineer|programmer analyst|business analyst", re.I)
SEC = re.compile(r"security|cyber|\bsoc\b|penetration|vulnerab|threat|\biam\b|identity (and|&) access|appsec|infosec", re.I)
DATA_RE = re.compile(r"\bdata\b|analytic|machine learning|\bml\b|\bai\b|genai|business intelligence|\bbi\b|scientist|\betl\b", re.I)
CLOUD = re.compile(r"devops|\bsre\b|site reliability|cloud|infrastructure|network|systems? (admin|engineer|development)|sysadmin|kubernetes|platform engineer", re.I)
QA_RE = re.compile(r"\bqa\b|quality assurance|\btest|sdet|automation", re.I)
SUPPORT = re.compile(r"support|helpdesk|help desk|service desk", re.I)

SECTIONS = ["IT / Software", "Data / Analytics / AI", "Cybersecurity",
            "Cloud / DevOps / Infrastructure", "QA / Testing", "IT Support / Operations",
            "Clinical / Research", "Non-IT / Other"]
IT_SECTIONS = set(SECTIONS[:6])

SENIOR = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|vp|vice president|head|"
    r"architect|distinguished|avp)\b", re.I)


def section_of(title):
    t = title or ""
    if CLINICAL.search(t):
        return "Clinical / Research"
    if NON_IT.search(t):
        return "Non-IT / Other"
    if SEC.search(t):
        return "Cybersecurity"
    if DATA_RE.search(t):
        return "Data / Analytics / AI"
    if CLOUD.search(t):
        return "Cloud / DevOps / Infrastructure"
    if QA_RE.search(t):
        return "QA / Testing"
    if SUPPORT.search(t) and IT_YES.search(t):
        return "IT Support / Operations"
    if IT_YES.search(t):
        return "IT / Software"
    return "Non-IT / Other"


# ---------------------------------------------------------------- dates, experience
def to_dt(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, timezone.utc)
    s = str(v).strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def age_days(dt):
    if dt is None:
        return None
    return max(0, (NOW - dt).days)


def wd_posted_age(text):
    """Workday 'Posted 3 Days Ago' -> 3. Unknown -> None."""
    t = (text or "").lower()
    if "today" in t:
        return 0
    if "yesterday" in t:
        return 1
    m = re.search(r"(\d+)\+?\s*day", t)
    return int(m.group(1)) if m else None


def clean(text):
    t = html.unescape(text or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_exp(text):
    """Return (largest 'N years' figure or None, short hint). Lower bound of ranges."""
    t = clean(text)
    best, hint = None, ""
    for m in re.finditer(
        r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*\+?\s*)?(?:years?|yrs?)\b",
        t, re.I,
    ):
        lo = int(m.group(1))
        if lo > 15:
            continue
        if best is None or lo > best:
            best = lo
            start = max(0, m.start() - 25)
            if start:  # begin at a word boundary, not mid-word
                start = t.find(" ", start) + 1 or start
            hint = t[start: m.end() + 45].strip()
    return best, hint


def fit(title, est):
    if SENIOR.search(title or ""):
        return "no"
    if est is None:
        return "unknown"
    return "yes" if est <= 5 else "no"


def cand(**kw):
    c = {"company": "", "title": "", "id": "", "req_id": "", "location": "",
         "posted_dt": None, "apply_url": "", "source": "", "text": "",
         "token": "", "status": "unchecked", "mode": ""}
    c.update(kw)
    return c


# ---------------------------------------------------------------- adapters
# Each source: list_<src>(board) -> [cand];  verify_<src>(cand) -> bool (open?)
def list_greenhouse(b):
    _, d = http("https://boards-api.greenhouse.io/v1/boards/%s/jobs" % b["token"])
    out = []
    for j in (d or {}).get("jobs", []):
        out.append(cand(
            company=b["name"], title=j.get("title", ""), id=str(j.get("id", "")),
            location=(j.get("location") or {}).get("name", ""),
            posted_dt=to_dt(j.get("first_published")),
            apply_url=j.get("absolute_url", ""), source="greenhouse", token=b["token"]))
    return out


def verify_greenhouse(c):
    st, d = http("https://boards-api.greenhouse.io/v1/boards/%s/jobs/%s" % (c["token"], c["id"]))
    if st != 200 or not d:
        return False
    c["req_id"] = str(d.get("requisition_id") or "")
    if DROP.search(c["req_id"] + " " + c["title"]):
        return False
    c["text"] = d.get("content", "")
    c["status"] = "open (ATS verified)"
    return True


def list_lever(b):
    _, d = http("https://api.lever.co/v0/postings/%s?mode=json" % b["token"])
    out = []
    for j in d or []:
        cat = j.get("categories") or {}
        locs = [cat.get("location", "")] + list(cat.get("allLocations") or [])
        loc = ", ".join(sorted({x for x in locs if x}))
        out.append(cand(
            company=b["name"], title=j.get("text", ""), id=j.get("id", ""),
            location=loc, posted_dt=to_dt(j.get("createdAt")), mode=j.get("workplaceType", ""),
            apply_url=j.get("hostedUrl", ""), source="lever", token=b["token"],
            text=j.get("descriptionPlain", "")))
    return out


def verify_lever(c):
    st, d = http("https://api.lever.co/v0/postings/%s/%s" % (c["token"], c["id"]))
    if st != 200 or not d:
        return False
    extra = " ".join(clean(x.get("content", "")) for x in d.get("lists", []))
    c["text"] = (d.get("descriptionPlain", "") + " " + extra).strip() or c["text"]
    c["status"] = "open (ATS verified)"
    return True


def list_workday(b):
    base = "https://%s/wday/cxs/%s/%s" % (b["host"], b["tenant"], b["site"])
    apply_base = b.get("apply_base") or "https://%s/%s" % (b["host"], b["site"])
    searches = b.get("searches") or [b.get("search", "")]
    out, seen = [], set()
    for text in searches:  # Workday has no date filter and no date sort, so search several keywords
        offset = 0
        for _ in range(int(b.get("max_pages", 6))):
            _, d = http(base + "/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset,
                                         "searchText": text})
            posts = (d or {}).get("jobPostings", [])
            if not posts:
                break
            for p in posts:
                path = p.get("externalPath", "")
                if not path or path in seen:
                    continue
                seen.add(path)
                a = wd_posted_age(p.get("postedOn", ""))
                out.append(cand(
                    company=b["name"], title=p.get("title", ""), id=path.rsplit("_", 1)[-1],
                    location=p.get("locationsText", ""),
                    posted_dt=(NOW - timedelta(days=a)) if a is not None else None,
                    apply_url=apply_base + path, source="workday", token=base + path))
            offset += 20
            time.sleep(PAUSE)
    return out


def verify_workday(c):
    st, d = http(c["token"])
    info = (d or {}).get("jobPostingInfo") if d else None
    if st != 200 or not info or info.get("canApply") is False:
        return False
    sd = to_dt(info.get("startDate"))
    if sd:
        c["posted_dt"] = sd
    c["req_id"] = str(info.get("jobReqId") or "")
    c["mode"] = info.get("remoteType", "") or ""
    extra = " ".join([info.get("location", "")] + list(info.get("additionalLocations") or []) +
                     [(info.get("country") or {}).get("descriptor", "")])
    if not is_india(c["location"]) and is_india(extra):
        c["location"] = extra.strip()
    c["text"] = info.get("jobDescription", "")
    c["status"] = "open (ATS verified)"
    return True


def list_amazon(b):
    seen, out = set(), []
    for q in b["queries"]:
        offset = 0
        for _ in range(int(b.get("max_pages", 3))):
            url = "https://www.amazon.jobs/en/search.json?" + parse.urlencode({
                "base_query": q, "loc_query": "India", "country": "IND",
                "sort": "recent", "result_limit": 50, "offset": offset})
            _, d = http(url)
            jobs = (d or {}).get("jobs", [])
            if not jobs:
                break
            oldest = None
            for j in jobs:
                dt = to_dt(j.get("posted_date"))
                oldest = dt if (oldest is None or (dt and dt < oldest)) else oldest
                jid = str(j.get("id_icims", ""))
                if jid in seen:
                    continue
                seen.add(jid)
                out.append(cand(
                    company="Amazon", title=j.get("title", ""), id=jid,
                    location=(j.get("city") or j.get("normalized_location") or "") + ", India",
                    posted_dt=dt, apply_url="https://www.amazon.jobs" + j.get("job_path", ""),
                    source="amazon", text=j.get("basic_qualifications", "") or ""))
            if oldest and age_days(oldest) > WINDOW:
                break
            offset += 50
            time.sleep(PAUSE)
    return out


def verify_amazon(c):  # listed in Amazon's own live search = open
    c["status"] = "open (listed in employer's live search)"
    return True


def list_smartrecruiters(b):
    out, offset = [], 0
    for _ in range(int(b.get("max_pages", 5))):
        _, d = http("https://api.smartrecruiters.com/v1/companies/%s/postings?country=in&limit=100&offset=%d"
                    % (b["company"], offset))
        content = (d or {}).get("content", [])
        if not content:
            break
        for j in content:
            loc = j.get("location") or {}
            out.append(cand(
                company=b["name"], title=j.get("name", ""), id=str(j.get("id", "")),
                location=", ".join(x for x in (loc.get("city"), loc.get("region"), "India") if x),
                mode="remote" if loc.get("remote") else ("hybrid" if loc.get("hybrid") else ""),
                posted_dt=to_dt(j.get("releasedDate")),
                apply_url="https://jobs.smartrecruiters.com/%s/%s" % (b["company"], j.get("id", "")),
                source="smartrecruiters", token=b["company"]))
        offset += 100
        time.sleep(PAUSE)
    return out


def verify_smartrecruiters(c):
    st, d = http("https://api.smartrecruiters.com/v1/companies/%s/postings/%s" % (c["token"], c["id"]))
    if st != 200 or not d:
        return False
    sections = ((d.get("jobAd") or {}).get("sections") or {})
    c["text"] = " ".join(clean((v or {}).get("text", "")) for v in sections.values())
    c["status"] = "open (ATS verified)"
    return True


def list_ashby(b):
    _, d = http("https://api.ashbyhq.com/posting-api/job-board/%s" % b["token"])
    out = []
    for j in (d or {}).get("jobs", []):
        if j.get("isListed") is False:
            continue
        out.append(cand(
            company=b["name"], title=j.get("title", ""), id=str(j.get("id", "")),
            location=j.get("location", ""),
            mode=j.get("workplaceType", "") or ("remote" if j.get("isRemote") else ""),
            posted_dt=to_dt(j.get("publishedAt")), apply_url=j.get("jobUrl", ""),
            source="ashby", token=b["token"], text=j.get("descriptionPlain", "")))
    return out


def verify_ashby(c):
    c["status"] = "open (listed on ATS board)"
    return True


ADAPTERS = {
    "greenhouse": (list_greenhouse, verify_greenhouse),
    "lever": (list_lever, verify_lever),
    "workday": (list_workday, verify_workday),
    "amazon": (list_amazon, verify_amazon),
    "smartrecruiters": (list_smartrecruiters, verify_smartrecruiters),
    "ashby": (list_ashby, verify_ashby),
}


# ---------------------------------------------------------------- main
def board_list(cfg):
    for src in ("greenhouse", "lever", "workday", "smartrecruiters", "ashby"):
        for b in cfg.get(src, []):
            yield src, b
    if cfg.get("amazon"):
        yield "amazon", dict(cfg["amazon"], name="Amazon")


def run(cfg):
    global WINDOW
    WINDOW = int(cfg.get("window_days", WINDOW))
    report, pool = {}, []
    for src, b in board_list(cfg):
        key = "%s:%s" % (src, b.get("name"))
        try:
            found = ADAPTERS[src][0](b)
            report[key] = {"ok": True, "listed": len(found)}
            pool.extend(found)
        except Exception as e:
            report[key] = {"ok": False, "error": str(e)[:150]}
        time.sleep(PAUSE)

    # cheap filters first, so we only verify what could be published
    short = []
    for c in pool:
        a = age_days(c["posted_dt"])
        if a is not None and a > WINDOW:
            continue
        if DROP.search(c["title"]):
            continue
        if not is_india(c["location"]) and not re.search(r"\d+\s+locations?", c["location"], re.I):
            continue
        short.append(c)

    jobs = []
    for c in short:
        try:
            if not ADAPTERS[c["source"]][1](c):
                continue
        except Exception as e:
            c["status"] = "unchecked (%s)" % str(e)[:60]
        if not is_india(c["location"]):
            continue
        a = age_days(c["posted_dt"])
        if a is not None and a > WINDOW:  # real date from detail can differ from list
            continue
        est, hint = parse_exp(c["text"])
        mode = mode_of(c["location"], c["mode"])
        group = city_group(c["location"], mode)
        jobs.append({
            "company": c["company"], "title": c["title"], "id": c["id"], "req_id": c["req_id"],
            "section": section_of(c["title"]),
            "location": c["location"], "work_mode": mode, "multi_city": is_multi_city(c["location"]),
            "city_group": group, "geo_rank": GROUP_ORDER.index(group) + 1,
            "posted": c["posted_dt"].date().isoformat() if c["posted_dt"] else "",
            "age_days": a, "exp_years_est": est, "exp_hint": hint,
            "fit_0_5": fit(c["title"], est), "status": c["status"],
            "apply_url": c["apply_url"], "source": c["source"],
        })
        time.sleep(PAUSE)
    return jobs, report


def collapse(jobs):
    """Same company + same title (e.g. 17 identical openings) -> one row."""
    groups = {}
    for j in jobs:
        groups.setdefault((j["company"], j["title"].strip().lower()), []).append(j)
    out = []
    for g in groups.values():
        g.sort(key=lambda j: (j["geo_rank"], j["age_days"] if j["age_days"] is not None else 99))
        best = dict(g[0])
        best["copies"] = len(g)
        best["also_in"] = sorted({j["location"] for j in g[1:] if j["location"] != best["location"]})
        out.append(best)
    return out


def add_history(jobs):
    path = os.path.join(DATA, "seen.json")
    try:
        with open(path) as f:
            seen = json.load(f)
    except Exception:
        seen = {}
    today = NOW.date().isoformat()
    for j in jobs:
        k = "%s|%s" % (j["company"], j["id"])
        j["first_seen"] = seen.setdefault(k, today)
        j["new_today"] = j["first_seen"] == today
    cutoff = (NOW - timedelta(days=90)).date().isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    with open(path, "w") as f:
        json.dump(seen, f, indent=0, sort_keys=True)


FIT_ORDER = {"yes": 0, "unknown": 1, "no": 2}


def render(rows):
    """Markdown grouped by section, then city."""
    out = []
    for sec in SECTIONS:
        in_sec = [j for j in rows if j["section"] == sec]
        if not in_sec:
            continue
        out += ["## %s (%d)" % (sec, len(in_sec)), ""]
        for grp in GROUP_ORDER:
            in_grp = [j for j in in_sec if j["city_group"] == grp]
            if not in_grp:
                continue
            out += ["### %s (%d)" % (grp, len(in_grp)), ""]
            for j in in_grp:
                loc = j["location"] + (" [multi-city]" if j["multi_city"] else "")
                more = " | Also hiring in: %s" % "; ".join(j["also_in"][:6]) if j.get("also_in") else ""
                out += [
                    "**%s | %s**" % (j["title"], j["company"]),
                    "- Location: %s | Work mode: %s%s" % (loc, j["work_mode"], more),
                    "- Posted: %s (%s days ago) | New today: %s"
                    % (j["posted"] or "unknown", j["age_days"] if j["age_days"] is not None else "?",
                       "yes" if j["new_today"] else "no"),
                    "- Experience: fit %s%s" % (j["fit_0_5"], " | " + j["exp_hint"] if j["exp_hint"] else ""),
                    "- ID: %s%s | Status: %s" % (j["id"], " / " + j["req_id"] if j["req_id"] else "", j["status"]),
                    "- Apply: " + j["apply_url"], ""]
    return out


def write_summary(meta, report, jobs):
    """Shown on the GitHub run page (Actions -> the run -> Summary)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    kept = {}
    for j in jobs:
        kept[j["company"]] = kept.get(j["company"], 0) + 1
    L = ["## SERVE job collector run", "",
         "- Time: %s UTC | Window: %d days" % (meta["generated_utc"], meta["window_days"]),
         "- Boards read: %d OK, %d failed" % (meta["boards_ok"], len(meta["boards_failed"])),
         "- Jobs published: **%d** (IT: %d)" % (meta["job_count"], meta["it_job_count"]), "",
         "| Section | Jobs | Pune | Mumbai | Sambhajinagar | Remote |", "|---|---|---|---|---|---|"]
    for sec in SECTIONS:
        r = [j for j in jobs if j["section"] == sec]
        cnt = lambda g: sum(1 for j in r if j["city_group"] == g)
        L.append("| %s | %d | %d | %d | %d | %d |" % (sec, len(r), cnt("Pune"), cnt("Mumbai"),
                 cnt("Chhatrapati Sambhajinagar"), cnt("Remote (India)")))
    L += ["", "| Board | Listed | Published | Status |", "|---|---|---|---|"]
    for k, v in report.items():
        name = k.split(":", 1)[1]
        L.append("| %s | %s | %d | %s |" % (k, v.get("listed", "-"), kept.get(name, 0),
                 "OK" if v["ok"] else "FAILED: " + v["error"]))
    text = "\n".join(L)
    print(text)
    if path:
        with open(path, "a") as f:
            f.write(text + "\n")


def write_outputs(jobs, report):
    os.makedirs(DATA, exist_ok=True)
    jobs = collapse(jobs)
    add_history(jobs)
    jobs.sort(key=lambda j: (SECTIONS.index(j["section"]), j["geo_rank"],
                             FIT_ORDER[j["fit_0_5"]], j["age_days"] if j["age_days"] is not None else 99))
    ok = [k for k, v in report.items() if v["ok"]]
    bad = {k: v["error"] for k, v in report.items() if not v["ok"]}
    it = [j for j in jobs if j["section"] in IT_SECTIONS]
    meta = {"generated_utc": NOW.strftime("%Y-%m-%d %H:%M"), "window_days": WINDOW,
            "boards_ok": len(ok), "boards_failed": bad, "job_count": len(jobs),
            "it_job_count": len(it)}
    with open(os.path.join(DATA, "jobs_latest.json"), "w") as f:
        json.dump({"meta": meta, "jobs": jobs}, f, indent=1, ensure_ascii=False)
    with open(os.path.join(DATA, "run_report.json"), "w") as f:
        json.dump(report, f, indent=1)

    legend = ["Cities are listed in this order: Pune, Mumbai, Chhatrapati Sambhajinagar, Remote (India), "
              "Delhi NCR / Haryana, Bangalore, Chennai, Kolkata, Hyderabad, Ahmedabad, Other India.",
              "Work mode comes from the employer's own listing (remote / hybrid / onsite / unspecified). "
              "[multi-city] means the job is open in 3 or more cities.",
              "fit_0_5: yes = asks 5 years or less, unknown = no years found, no = senior or over 5 years.", ""]
    head = ["# SERVE jobs, collected %s UTC" % meta["generated_utc"],
            "Window: last %d days. Boards read OK: %d. Boards failed: %d. Jobs: %d (IT: %d)."
            % (WINDOW, len(ok), len(bad), len(jobs), len(it))]
    if bad:
        head.append("Failed boards: " + "; ".join("%s (%s)" % (k, v) for k, v in bad.items()))
    head.append("")
    with open(os.path.join(DATA, "jobs_latest.md"), "w") as f:
        f.write("\n".join(head + legend + render(jobs)))

    # short file for chats: only IT jobs a 0-5 year candidate can apply to
    short = [j for j in it if j["fit_0_5"] in ("yes", "unknown")]
    shead = head[:1] + ["Shortlist: IT sections only, fit_0_5 = yes or unknown. "
                        "Jobs: %d. Full list: jobs_latest.md" % len(short), ""]
    with open(os.path.join(DATA, "it_jobs_shortlist.md"), "w") as f:
        f.write("\n".join(shead + legend + render(short)))
    write_summary(meta, report, jobs)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int)
    ap.add_argument("--config", default=os.path.join(ROOT, "companies.json"))
    a = ap.parse_args()
    with open(a.config) as f:
        cfg = json.load(f)
    if a.days:
        cfg["window_days"] = a.days
    jobs, report = run(cfg)
    meta = write_outputs(jobs, report)
    if meta["boards_ok"] == 0:  # nothing worked: fail the run so GitHub emails you
        sys.exit("No board could be read. Check run_report.json")


if __name__ == "__main__":
    main()
