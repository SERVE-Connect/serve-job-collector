# SERVE daily job collector

Runs every day at 08:00 IST on GitHub Actions. Reads company ATS job boards, keeps India IT jobs
posted in the last 7 days, checks each is still open, and writes:

- `data/it_jobs_latest.md`   easy to read, give this link to the chat
- `data/it_jobs_latest.json` same data for scripts
- `data/run_report.json`     which boards worked and which failed
- `data/seen.json`           job IDs already seen (marks `New today`)

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
