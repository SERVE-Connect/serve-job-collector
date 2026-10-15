#!/usr/bin/env python3
"""SERVE daily job collector.

Reads public ATS job boards listed in companies.json, keeps India IT jobs posted
within the last N days, checks each one is still open, estimates the experience
asked for, and writes data/it_jobs_latest.json + data/it_jobs_latest.md.

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


# ---------------------------------------------------------------- helpers
INDIA_WORDS = [
    "pune", "pimpri", "hinjewadi", "hinjawadi", "mumbai", "navi mumbai", "thane",
    "powai", "airoli", "sambhajinagar", "aurangabad", "nashik", "nagpur", "kolhapur",
    "delhi", "noida", "gurgaon", "gurugram", "faridabad", "ghaziabad", "haryana",
    "hyderabad", "chennai", "kolkata", "ahmedabad", "gandhinagar", "bangalore",
    "bengaluru", "kochi", "coimbatore", "jaipur", "indore", "chandigarh", "mohali",
    "thiruvananthapuram", "trivandrum", "lucknow", "bhubaneswar", "vadodara", "surat",
    "mysuru", "mysore", "visakhapatnam", "bhopal", "patna",
]


def is_india(loc):
    s = (loc or "").lower()
    if re.search(r"\bindia\b|\bind\b", s):
        return True
    return any(w in s for w in INDIA_WORDS)


def geo_rank(loc):
    """1 Pune, 2 Mumbai, 3 Sambhajinagar, 4 Remote India, 5 other India."""
    s = (loc or "").lower()
    if any(w in s for w in ("pune", "pimpri", "hinjewadi", "hinjawadi")):
        return 1
    if any(w in s for w in ("mumbai", "thane", "powai", "airoli")):
        return 2
    if "sambhajinagar" in s or "aurangabad" in s:
        return 3
    if "remote" in s:
        return 4
    return 5


IT_YES = re.compile(
    r"software|developer|engineer|devops|\bsre\b|site reliability|data scien|data analy|"
    r"data engineer|analytics|machine learning|\bml\b|\bai\b|genai|cloud|security|cyber|"
    r"\bsoc\b|\bqa\b|quality assurance|\btest|sdet|automation|platform|backend|back-end|"
    r"frontend|front-end|full[- ]?stack|\bjava|python|\.net|golang|react|angular|node\.?js|"
    r"android|\bios\b|mobile|database|\bdba\b|network|sysadmin|system admin|infrastructure|"
    r"it support|technical support|application support|solutions? architect|programmer|"
    r"salesforce|\bsap\b|mainframe|\betl\b|business intelligence|penetration|vulnerab|"
    r"firmware|embedded|\bsdk\b|\bapi\b|data program|technology",
    re.I,
)
IT_NO = re.compile(
    r"account executive|\bsales\b|marketing|recruit|talent acqui|human resources|\bhr\b|"
    r"accountant|accounting|legal|counsel|customer success|business development|"
    r"supply chain|procurement|content writer|mechanical|civil engineer|chemical|"
    r"manufacturing|field engineer|pooling|talent community|evergreen",
    re.I,
)
SENIOR = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|vp|vice president|head|"
    r"architect|distinguished|avp)\b",
    re.I,
)


def is_it(title):
    return bool(IT_YES.search(title or "")) and not IT_NO.search(title or "")


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
    """Return (estimated_min_years or None, short hint). Uses the largest 'N years'."""
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
            hint = t[max(0, m.start() - 25): m.end() + 45].strip()
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
         "token": "", "status": "unchecked"}
    c.update(kw)
    return c


# ---------------------------------------------------------------- adapters
# Each adapter: list_<src>(board) -> [cand];  verify_<src>(cand) -> bool (open?)
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
    if re.search(r"pooling|evergreen|talent community", c["req_id"] + c["title"], re.I):
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
        if j.get("workplaceType") == "remote" and loc:
            loc += " (remote)"
        out.append(cand(
            company=b["name"], title=j.get("text", ""), id=j.get("id", ""),
            location=loc, posted_dt=to_dt(j.get("createdAt")),
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
    out, offset = [], 0
    for page in range(int(b.get("max_pages", 10))):
        _, d = http(base + "/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset,
                                     "searchText": b.get("search", "")})
        posts = (d or {}).get("jobPostings", [])
        if not posts:
            break
        recent = 0
        for p in posts:
            a = wd_posted_age(p.get("postedOn", ""))
            if a is not None and a <= WINDOW:
                recent += 1
            path = p.get("externalPath", "")
            c = cand(company=b["name"], title=p.get("title", ""), id=path.rsplit("_", 1)[-1],
                     location=p.get("locationsText", ""),
                     posted_dt=(NOW - timedelta(days=a)) if a is not None else None,
                     apply_url=apply_base + path, source="workday", token=base + path)
            out.append(c)
        if recent == 0 and page >= 1:  # list is newest-first; nothing recent left
            break
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
            location=j.get("location", "") + (" (remote)" if j.get("isRemote") else ""),
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

WINDOW = 7

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
        if not is_it(c["title"]):
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
        jobs.append({
            "company": c["company"], "title": c["title"], "id": c["id"], "req_id": c["req_id"],
            "location": c["location"], "geo_rank": geo_rank(c["location"]),
            "posted": c["posted_dt"].date().isoformat() if c["posted_dt"] else "",
            "age_days": a, "exp_years_est": est, "exp_hint": hint,
            "fit_0_5": fit(c["title"], est), "status": c["status"],
            "apply_url": c["apply_url"], "source": c["source"],
        })
        time.sleep(PAUSE)
    return jobs, report


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


def write_outputs(jobs, report):
    os.makedirs(DATA, exist_ok=True)
    add_history(jobs)
    jobs.sort(key=lambda j: (j["geo_rank"], FIT_ORDER[j["fit_0_5"]], j["age_days"] if j["age_days"] is not None else 99))
    ok = [k for k, v in report.items() if v["ok"]]
    bad = {k: v["error"] for k, v in report.items() if not v["ok"]}
    meta = {"generated_utc": NOW.strftime("%Y-%m-%d %H:%M"), "window_days": WINDOW,
            "boards_ok": len(ok), "boards_failed": bad, "job_count": len(jobs)}
    with open(os.path.join(DATA, "it_jobs_latest.json"), "w") as f:
        json.dump({"meta": meta, "jobs": jobs}, f, indent=1, ensure_ascii=False)
    with open(os.path.join(DATA, "run_report.json"), "w") as f:
        json.dump(report, f, indent=1)

    lines = ["# SERVE IT jobs, collected %s UTC" % meta["generated_utc"],
             "Window: last %d days. Boards read OK: %d. Boards failed: %d. Jobs: %d."
             % (WINDOW, len(ok), len(bad), len(jobs)),
             "Geography rank: 1 Pune, 2 Mumbai, 3 Sambhajinagar, 4 Remote India, 5 other India.",
             "fit_0_5: yes = asks 5 years or less, unknown = no years found, no = senior or over 5 years.", ""]
    if bad:
        lines.append("Failed boards: " + "; ".join("%s (%s)" % (k, v) for k, v in bad.items()))
        lines.append("")
    for i, j in enumerate(jobs, 1):
        lines += [
            "### %d. %s | %s" % (i, j["title"], j["company"]),
            "- Location: %s (rank %d) | Posted: %s (%s days ago) | New today: %s"
            % (j["location"], j["geo_rank"], j["posted"] or "unknown",
               j["age_days"] if j["age_days"] is not None else "?", "yes" if j["new_today"] else "no"),
            "- Experience: fit %s%s" % (j["fit_0_5"], " | " + j["exp_hint"] if j["exp_hint"] else ""),
            "- ID: %s%s | Status: %s" % (j["id"], " / " + j["req_id"] if j["req_id"] else "", j["status"]),
            "- Apply: " + j["apply_url"], ""]
    with open(os.path.join(DATA, "it_jobs_latest.md"), "w") as f:
        f.write("\n".join(lines))
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
    print(json.dumps(meta, indent=1))
    if meta["boards_ok"] == 0:  # nothing worked: fail the run so GitHub emails you
        sys.exit("No board could be read. Check run_report.json")


if __name__ == "__main__":
    main()
