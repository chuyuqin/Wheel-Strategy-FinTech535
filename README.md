# FINTECH 535 · Final Cycle

Assignment page: https://chuyuqin.github.io/Wheel-Strategy-FinTech535/final-cycle.html

Research correction: https://chuyuqin.github.io/Wheel-Strategy-FinTech535/research-revision.html

Submit the direct assignment-page URL, not this README. These paths require the new commit and GitHub Pages deployment to be live.

The nightly planner runs at 10 p.m. America/New_York, writes root `open_orders.json`, an identical `mkt/` compatibility copy, run status, and an append-only commitment ledger. A separate workflow deploys `docs/` after each nightly run, including its new bot commit. No LSEG secrets or desktop session are required: prices arrive through the professor's existing server connection.

## Reproduce the planner

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-nightly.txt
.venv/bin/python -m unittest discover -s tests -p 'test_nightly*.py' -v
.venv/bin/python src/nightly_orders.py
```

Generation writes actual output and can reserve an initial educational paper commitment. Tests use temporary synthetic files. The current conid is Microsoft 272093, copied from the existing server-delivered price file. The initial paper budget is $50,000; it is not a server-reported balance. No positions are fabricated or modified. Prices may lag by at most one completed NYSE session; the true signal date and lag are reported. Older inputs prevent new commitments. Existing dated tickets stay in the file as audit history and are never retargeted; without earlier tickets the output is `[]`. After the first ticket, a later target session waits for an authoritative book; the local adapter schema must match the future server format before cycling automatically.

## Publish and verify

1. Push this project to `main` in `chuyuqin/Wheel-Strategy-FinTech535`.
2. Repository Settings → Pages → Build and deployment → Source: **GitHub Actions**.
3. Actions → **Nightly wheel orders** → **Run workflow**. Confirm its Python/test/commit stages succeed. A waiting decision is a valid completed run and reports its reason.
4. Confirm **Deploy coursework pages** succeeds after the nightly workflow. Check the direct page URL and root JSON.
5. The default branch schedule then runs nightly without this laptop. GitHub may delay a scheduled start. Do not disable the repository's Actions; GitHub can disable schedules in inactive public repos after 60 days.

## Research correction

`docs/research-revision.html` presents every stock together, a newly stated forward testable prediction, historical Treasury-excess Sharpe, cash interest on free cash excluding collateral, assignment/stock-exposure explanations and sensitivities. It preserves the old reports with visible archive notices. Run `python src/revise_research.py` with the original private LSEG cache and bundled public Treasury CSV to regenerate the corrected study. `tests/test_rates_revision.py` tests rate conventions; `docs/results/revision/verification.json` records independent audits of 48 account paths. Never add the ignored `data/raw/` cache to Git.

---

## Archived original assignment notes

# PG Wheel Strategy

FINTECH 535 · Chuyu Qin · November 1, 2026

The submission website is `docs/index.html`. The full PG study covers January 3, 2023–September 30, 2024. Starting capital is $50,000 per account. The wheel returned 22.51% versus 19.27% for PG buy-and-hold with dividend reinvestment. Maximum drawdowns were -7.51% and -10.66%.

The website includes the thesis, three trading rules, one completed cycle, exact daily holdings, searchable blotter, ledger, dividend accounting, execution evidence and research-selection disclosures. PG was selected after a four-stock comparison; the result is exploratory. The January–September 2024 restart favors buy-and-hold. The common window was limited by cached option coverage after the daily LSEG download cap; no longer cross-stock result is claimed.

## View and publish

Open `docs/index.html` directly, or run `python3 -m http.server 8000 --directory docs`. Publish the `main` branch, `/docs` directory with GitHub Pages. All charts and data are bundled; viewing requires no LSEG access. Publication is left to the repository owner.

## Reproduce from the original private cache

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python src/normalize_comparison_cache.py
.venv/bin/python src/compare_stocks.py
.venv/bin/python src/verify_comparison.py
.venv/bin/python src/build_site.py
```

Raw responses in `data/raw/` are ignored by Git and excluded from the ZIP. Fetching history requires an entitled LSEG Workspace session. `src/fetch_comparison.py` checks the remaining allowance and can resume completed caches after the provider resets its quota. Fresh historical observations may differ after vendor revisions.

## Records

`docs/results/comparison/PG/historical/` contains the main daily ledger, blotter, benchmark records, metrics, skipped decisions and dividend-assignment scenario. `PG/test/` contains the separate January–September 2024 restart diagnostic; the internal folder name is not a claim of an unseen holdout. The original frozen AMZN settings were transferred to PG without name-specific retuning.

`comparison.html` preserves all four comparison stocks. `amzn-study.html` preserves the longer original AMZN report. The comparison plan versions, input audits, source manifest and verification results are under `docs/results/`. The main accounting identities, fill proxies and remaining biases are explained in the website. Synthetic fixtures test accounting only and never enter performance.
