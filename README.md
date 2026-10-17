# SERVE daily job collector

Runs every day at 08:00 IST on GitHub Actions. Reads company ATS job boards, keeps India jobs
posted in the last 7 days, checks each is still open, and writes:

- `data/bulletin_pick.md`      today's best 8-10 IT jobs for 0-5 years, give this link to the chat
- `data/it_jobs_shortlist.md`  every IT job for 0-5 years, by section then city
- `data/jobs_latest.md`        everything, including "Senior IT roles (5+ yrs)", Clinical and Non-IT
- `data/jobs_latest.csv`       the same table for Google Sheets or Excel: sort and filter by score_rank, posted, section, city_group, company, fit_0_5
- `data/jobs_latest.json`      same data for scripts (fields: section, city_group, work_mode, score, fit_0_5)
- `data/sent_ids.txt`          you fill this in (see below)
- `data/run_report.json`       which boards worked and which failed
- `data/seen.json`             IDs already seen (marks `New today`), kept 8 days

## How the bulletin picks are chosen
1. Jobs posted today or yesterday, asking under 5 years (or no years stated). One best job per company, by score.
2. If fewer than 8: a second job from a company, for at most 2 companies.
3. If still fewer than 8: the same steps on days 2-7 (marked `fallback`).

Score (100): fit for 0-5 years 30, city 25 (Pune highest), freshness 15, role relevance 15,
verified open on the company's own page 10, completeness 5.

## Telling the collector what you posted
After a bulletin, open `data/sent_ids.txt` on GitHub, add the line shown at the bottom of
`bulletin_pick.md` (date, then the job IDs) and commit. Those jobs are skipped on later days.
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
