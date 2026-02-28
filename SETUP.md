# Dashboard Auto-Update — Setup Guide

Two files do everything. Once set up you never touch them again.

---

## What happens automatically

On the **25th of every month at 08:00 UTC** GitHub runs a free Action that:
1. Calls the FRED API for all 13 live series
2. Updates the sparkline data and current-value numbers in the HTML
3. Commits and pushes the file back to your repo
4. GitHub Pages re-deploys within ~60 seconds

Your live site at `alex30free.github.io/stocklab` shows fresh data with zero manual work.

---

## One-time setup (5 minutes)

### Step 1 — Add the two files to your repo

Copy both files into your `stocklab` repo exactly at these paths:

```
stocklab/
├── update_dashboard.py          ← root of repo
└── .github/
    └── workflows/
        └── update-dashboard.yml ← must be this exact folder
```

**To upload via GitHub web UI:**

1. Go to `github.com/alex30free/stocklab`
2. Click **Add file → Upload files**
3. Upload `update_dashboard.py` to the root
4. For the workflow file: click **Add file → Create new file**,
   type `.github/workflows/update-dashboard.yml` as the filename
   (GitHub creates the folders automatically), paste the contents, commit

### Step 2 — Add your FRED API key as a secret

Your key must not sit in the public repo. GitHub secrets are encrypted.

1. Go to your repo → **Settings** (top menu)
2. Left sidebar → **Secrets and variables → Actions**
3. Click **New repository secret**
4. Name: `FRED_API_KEY`
5. Value: `68cb1c667bbe364dc0f7e64c8e1283ae`
6. Click **Add secret**

### Step 3 — Give Actions permission to write to your repo

1. Go to repo → **Settings → Actions → General**
2. Scroll to **Workflow permissions**
3. Select **Read and write permissions**
4. Click **Save**

### Step 4 — Test it right now (don't wait until the 25th)

1. Go to your repo → **Actions** tab
2. Left sidebar → **Auto-Update Dashboard**
3. Click **Run workflow → Run workflow**
4. Watch it run (takes ~30 seconds)
5. Check that the HTML file's last-modified date updated

---

## What gets updated automatically

| KPI | FRED Series | Typical release |
|-----|------------|-----------------|
| Yield Curve | T10Y2Y | Daily |
| HY Spreads | BAMLH0A0HYM2 | Daily |
| M2 Money Supply | M2SL | ~4th week |
| Fed Funds Rate | FEDFUNDS | Monthly |
| 5yr/5yr Inflation | T5YIFR | Daily |
| CPI (YoY %) | CPIAUCSL | ~2nd week |
| CAPE Ratio | CAPE | Monthly |
| PPI (YoY %) | PPIACO | ~2nd week |
| Initial Claims | ICSA | Weekly (Thu) |
| Sahm Rule | SAHMREALTIME | Monthly |
| JOLTS Quits | JTSQUR | ~4th week |
| Dollar Index | DTWEXBGS | Daily |
| Equity Risk Premium | DGS10 + CAPE | Computed |

**Not auto-updated** (no free FRED series exists):
- BofA FM Cash Level → update manually when you review the monthly BofA report
- AAII Sentiment → check aaii.com/sentimentsurvey weekly
- Put/Call Ratio → check CBOE daily if needed

---

## If something goes wrong

- **Action fails**: Go to Actions tab, click the failed run, read the log
- **FRED API error**: The script retries 3 times then skips that series; the old value stays in the HTML
- **No changes committed**: Means the data was identical to last month — that's fine, the action still ran successfully

---

## Cost

**Free.** GitHub Actions gives 2,000 free minutes/month for public repos
(unlimited) and 2,000 minutes for private repos. This job uses ~30 seconds
per month — well within any limit.
