# Daily Markets Dashboard

A static dashboard you bookmark and open every day, showing:
- Brent & WTI crude oil, gold, S&P 500, Nasdaq, CAC 40, Bitcoin, Ethereum (via Yahoo Finance)
- USD/MAD and EUR/MAD (via open.er-api.com, free, no API key)
- MASI and MASI 20 (Casablanca Stock Exchange) — best-effort scrape; marked "unavailable" if the site layout changes

All prices are shown in USD with their MAD equivalent alongside. Gains are green, losses are red.

A GitHub Actions workflow refreshes the data once a day (or on demand) and commits
`docs/digest.json`; the static page at `docs/index.html` fetches that file and renders it.
GitHub Pages serves `docs/` as your dashboard URL.

## Setup (5 minutes)

1. **Create a new GitHub repo** (public or private — Pages on a private repo needs
   GitHub Pro/Team/Enterprise, so public is simplest) and push these files to it,
   keeping the `.github/workflows/` and `docs/` folders as-is.

2. **Enable GitHub Pages**: repo → Settings → Pages → Source: "Deploy from a branch"
   → Branch: `main`, folder: `/docs` → Save. GitHub gives you a URL like
   `https://<your-username>.github.io/<repo-name>/` — bookmark it.

3. **Run the workflow once** to generate the first `docs/digest.json`: Actions tab →
   "Daily Markets Digest" → "Run workflow". Wait ~30 seconds, then refresh your
   dashboard URL.

4. **It now updates automatically** every day at 07:00 UTC (edit the `cron` line in
   `.github/workflows/daily-digest.yml` to change the time — cron times are always
   UTC, so subtract/add for Morocco time depending on DST).

No secrets or API keys are needed — every data source used is free and keyless.

## Customizing

- **Add/remove assets**: edit `YFINANCE_TICKERS` in `digest.py`. Any Yahoo
  Finance ticker works — e.g. `"BTC-USD"` for Bitcoin, `"^FTSE"` for the FTSE 100.
- **Change the look**: edit `docs/index.html` — it's a single static file with
  inline CSS/JS, no build step.
- **Fix MASI scraping**: if it stops working, open
  https://www.casablanca-bourse.com/ in a browser, inspect the `.data-block`
  elements near the MASI/MASI 20 tickers, and adjust `fetch_masi_indexes()` in
  `digest.py` to match. The site's WAF also rejects bare `User-Agent: Mozilla/5.0`
  requests — keep the fuller browser-like header set in that function.
- **Cost**: entirely free — GitHub Actions gives 2,000 free minutes/month (this
  job takes well under a minute/day), GitHub Pages is free for public repos, and
  both data sources used are free with no API key.

## Local testing

```
pip install -r requirements.txt
python digest.py          # writes docs/digest.json and prints a text summary
open docs/index.html      # or use a local server if your browser blocks file:// fetch
```

Some browsers block `fetch()` on `file://` URLs — if `docs/index.html` shows a
load error locally, serve the `docs/` folder instead: `python -m http.server -d docs`.
