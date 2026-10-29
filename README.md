# SERVE daily job collector

Runs every morning on GitHub Actions (01:47 IST, retries at 03:17 and 04:47 IST if the first run was not good; GitHub often starts scheduled runs 2 to 5 hours late). Reads company ATS job boards, keeps India jobs
posted in the last 7 days, checks each is still open, and writes:

Files the chat reads are written to `daily/today/`. On the first run of a new IST day the previous `today/` becomes `daily/yesterday/` (the fallback); later runs the same day just overwrite `today/`. The folder names never change, so the chat skills carry fixed links, and each file's "collected" header tells the chat whether it is really from today:
- `bulletin_pick.md`      today's best 8-10 IT jobs for 0-5 years
- `top_10.md`, `internship.md`, `city_<city>.md`, `domain_<domain>.md`  ready top-10 lists built in code (overall, internships and apprenticeships, per city, per domain); `ranked_index.md` lists them all with their job counts
- `it_jobs_shortlist.md`  every IT job for 0-5 years, by section then city
- `jobs_latest.md`        everything, including "Senior IT roles (5+ yrs)", Clinical and Non-IT. The workflow reads its first lines to see whether today's run was already good
- `jobs_latest.csv`       the same table for Google Sheets or Excel: sort and filter by score_rank, posted, section, city_group, company, fit_0_5

Working files stay in `data/`:
- `sent_ids.txt`          you fill this in (see below)
- `run_report.json`       which boards worked and which failed
- `seen.json`             IDs already seen (marks `New today`), kept 8 days

## How the bulletin picks are chosen
1. Jobs posted today or yesterday, asking under 5 years (or no years stated). One best job per company, by score.
2. If fewer than 8: a second job from a company, for at most 2 companies.
3. If still fewer than 8: the same steps on days 2-7 (marked `fallback`).

Score (100): fit for 0-5 years 30 (senior title or 5+ years: 6), city 25 (Pune highest), freshness 15,
role relevance 15, verified open on the company's own page 10, completeness 5. The score is fixed for each job
when the collector runs; asking for a city or domain does not change it.

## Ranked lists (top_10, city_*, domain_*)
The same pick rules as above, applied to any pool, with already-sent jobs left out:
- `top_10.md`: all cities and domains, 0-5 years.
- `city_*.md`: one per city group, all domains, senior roles included. Multi-city jobs count for each city they list.
- `domain_*.md`: one per section (Senior IT roles includes 5+ years), plus keyword domains
  (pharma, logistics, hospitality, healthcare, banking and finance, customer support, HR, sales and marketing),
  which are matched by words in the title and requirements within Non-IT / Other and Clinical / Research.
The chat commands read one of these files and only format it, so they cannot break the company or sent rules.

## Telling the collector what you posted
After a bulletin, open `data/sent_ids.txt` on GitHub, add the line the chat gives you at the end of each bulletin (date, then the job IDs) and commit. Those jobs are skipped on later days.
Lines older than 7 days are removed by the daily run.

The run page on GitHub (Actions -> the run -> Summary) shows a table of boards and counts.

## Add a company
Edit `companies.json`.

- Greenhouse: apply link has `greenhouse.io/TOKEN/` -> add `{"name": "X", "token": "TOKEN"}`
- Lever: apply link has `jobs.lever.co/TOKEN/` -> add to `lever`
- Workday: career page like `https://TENANT.wdN.myworkdayjobs.com/SITE` -> add
  `{"name": "X", "host": "TENANT.wdN.myworkdayjobs.com", "tenant": "TENANT", "site": "SITE", "search": "India"}`
- SmartRecruiters: `{"name": "X", "company": "COMPANYID"}` in `smartrecruiters`
- Ashby: `{"name": "X", "token": "TOKEN"}` in `ashby`

Check `data/run_report.json` after the next run. A board that shows `"ok": false` has a wrong token or blocks bots.

## Not covered
Companies that use their own career portal with no public API (TCS, Infosys, Wipro, HCL, Citi and similar).
The experience figure is a guess from the job text (`fit_0_5`), so read `exp_hint` before publishing.

Qualification, salary and requirements are filled only when the job text states them (salary also from the Greenhouse and Lever pay fields). Nothing is guessed. `requirements` is raw text of up to 300 characters, which the chat condenses into a summary of about 150 characters for the bulletin.
