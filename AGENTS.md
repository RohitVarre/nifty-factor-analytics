# AGENTS.md

Research project plus Dash dashboard comparing 41 Indian NSE indices on Total Return Index (TRI) data from 2005 to today. User-facing overview and commands: [README.md](README.md). This file covers how things work and what has gone wrong before.

## Goal
Judge whether factor indices (Momentum, Quality, Value, Low-Vol, Alpha, Multifactor) beat cap-weighted benchmarks on return, risk and consistency, for both lumpsum and SIP investors. Results must be honest: TRI data only, no look-ahead, and state caveats (overlapping windows, in-sample weights) instead of hiding them.

## Status (2026-10-17)
- Data runs from 2005-04-01 to 2026-10-16 for all 41 indices (5,344 rows each; High Dividend Yield 15 has one missing day, filled by the merge). The 22 added on 2026-10-17 are every NSE strategy/weighting index with TRI history from 1 Apr 2005 (`reference/nse_equity_indices.csv`).
- Dashboard tabs: Cumulative Growth, Rolling Period Returns, SIP Cumulative, SIP Rolling Period (these four are **table-only** since 2026-10-17, at the user's request: no charts, no Linear/Log toggle), **Deep Dive Compare** (replaced "Best Times to Invest" on 2026-09-28), Correlation Analysis.
- 93 tests pass. The notebook was re-executed on the new data.
- Roadmap, not started: rebalancing friction (0.25–0.50%), walk-forward re-optimisation (e.g. 36-month look-back), macro-regime factor rotator.

## Public repo
The GitHub repo is public. `data/` and `cache/` are gitignored (NSE data is not ours to redistribute), so a fresh clone must run `download_new_indices.py` before the app or tests work. Keep personal paths, emails and credentials out of tracked files, and commit with the GitHub noreply address (set in this repo's local git config).

## Structure
- `analytics.py`: every calculation, pure functions, no Dash. **Put new maths here and test it.**
- `app.py`: layout and callbacks only. It loads `data/` at import time via `analytics.load_data()`.
- `download_new_indices.py`: fetches from niftyindices.com, caches in `cache/{API_Name}_{year}.csv`, writes `data/{Name}_TRI.csv` (`Date`, `<Index Name>`).
- `Indian_Indices_Analysis.ipynb`: standalone. It has its own copy of `run_metrics_analysis` and the optimiser, and writes `results/*.png`.
- `tests/test_analytics.py` (known-answer and reference-implementation checks) and `tests/test_app_e2e.py` (fires every registered callback through `/_dash-update-component`).
- `reference/nse_equity_indices.csv`: NSE's equity index catalogue (154 indices from the historical-data page's Broad / Sectoral / Strategy / Thematic lists, 2026-10-17), with `in_dashboard` and `tri_history_start` (checked for the 19 in the dashboard and 30 factor/weighting candidates; others say "not checked"). The catalogue comes from `/BackPage/gethistoricaltypeSubindexdata` and `/BackPage/gethistoricaltypeindexdata` with `indexgroup = "Historical Index Data"`.
- `handover.md`: historical handover from June 2026. Superseded by this file and the README.
- `cache/` also holds files for 7 indices from an earlier version of the project (Nifty 100/200, Alpha 50, 100 LowVol 30, 50 Value 20, Alpha LowVol 30, Low Vol 50). Nothing reads them.

## Methodology (single source of truth)
- **Volatility**: std of returns × √periods. Lumpsum tables use weekly returns (`resample('W')`, i.e. Friday close) × √52. Rolling and SIP use daily returns × √252.
- **Downside volatility**: `sqrt(mean(min(r,0)²))` × √periods. Target is 0, and the denominator is *all* periods, matching the Sortino convention.
- **Risk-adjusted measures** (`analytics.risk_adjusted` / `window_risk_adjusted`; the four tables show Sharpe, Sortino and M² and no longer show the rf = 0 ratios or min/max volatility, since 2026-10-23): with rf from the **Risk-Free Rate picker** at the top (`rf-rate`, % p.a., default `RF_RATE` = 6%, blank/invalid → default, clamped 0–30) converted per period as (1 + rf)^(1/P) − 1:
  - Sharpe = mean(r − rf_p) / std(r − rf_p) × √P.
  - Sortino = mean(r − rf_p) / √mean(min(r − rf_p, 0)²) × √P (downside measured below rf; the separate "Downside Volatility" column still uses target 0).
  - Risk-Adjusted Return = M² = rf + Sharpe × σ(Nifty 50) over the same returns: the index's return scaled to Nifty 50's risk. Arithmetic-mean based, so it sits above CAGR (Nifty 50: M² ≈ 14.5% vs CAGR 13.3%); compare it across indices, not with CAGR. Nifty 50's own M² barely moves with rf.
  - Per table: Cumulative = weekly returns over the range (P = 52); Rolling = daily returns inside each lumpsum window, averaged across windows (P = 252); SIP Cumulative = the SIP's flow-neutral daily returns from the first instalment (equal to the index's); SIP Rolling = daily returns from each window's first instalment to its valuation date, averaged. SIP Sharpe is therefore close to the lumpsum Sharpe for the same span; SIP changes the money-weighted return (XIRR), not the per-period returns.
  - Deep Dive's metric table uses the same picker and formulas; its Return / Volatility rows stay at rf = 0. The notebook keeps its own old (CAGR − rf) / vol shortcut.
- **Rolling windows are calendar-based**: for each end date, start = the last trading day ≤ end − N years. CAGR uses actual elapsed days / 365.25. Window vol comes from cumulative sums (`window_moments`) and matches pandas std exactly.
- **SIP**: instalment on the first trading day of each month. Rolling SIP = N×12 instalments, valued on the next month's first trading day. IRR uses a vectorised bisection (`xirr_matrix`). SIP volatility uses flow-neutral (TWR) returns, which for a single-index SIP equal the index's daily returns.
- **SIP drawdown is flow-adjusted**: `V_t / (C_t + cummax(V − C)_t) − 1`, so new instalments cannot mask a fall.
- **Deep Dive**: lumpsum only (one-time investment, point-to-point TRI CAGR; no SIP), window length from a 1–10 year `dcc.Slider` like the other rolling tabs. One observation per trading-day window end (heavily overlapping, so frequencies are descriptive only). KDE via `scipy.stats.gaussian_kde`. Distribution and excess charts mark the median (dashed) and the mean (dotted) in each fund's colour. These lines are traces on a hidden 0–1 overlay axis (`add_stat_line`), so their values appear as legend entries below the chart (`legend_below`) and never as labels over the bars; clicking an entry hides that line. Capture ratios use monthly geometric means in B's up/down months.
- **Excess-return correlation** (Correlation tab): weekly index return minus weekly benchmark return, then Pearson (`excess_return_correlation`). The benchmark is dropped from the matrix. Default benchmark is Nifty 50. A benchmark that is most of another index (Nifty 50 inside Nifty 500) makes that index's excess the mirror of the size tilt, so Nifty 500 as benchmark puts Nifty 50 at the top of the "most diversifying" list (−0.86 vs Midcap 150) for size reasons, not factor ones.
- **Deep Dive fixed axes**: the x-axes of the distribution and excess histograms are fixed to the min/max rolling return of the chosen pair across *all* 1–10Y windows that fit the date range (`analytics.rolling_return_bounds`, ±3% padding), with a fixed bin width of range/100, so moving the window slider never rescales them; only the density/count axis autoscales. Short windows dominate the range (1Y spans about −55% to +133% for MQVLv vs Nifty 50), so long windows look narrow by design. The rolling-over-time chart's return axis is *not* fixed.
- **One fund vs all others** (`fund_correlations`, beside the excess heatmap): for the chosen fund, weekly Excess Correlation (benchmark subtracted) and Raw Correlation against every other *selected* index. The fund and the benchmark are never rows; if the fund is the benchmark the table explains why it is empty. Initial sort is Excess ascending (best diversifiers first); header clicks sort numerically.
- **Heatmap layout** (`corr_heatmap` in `app.py`): rows/columns ordered by `analytics.cluster_order` (average-linkage clustering on 1 − correlation, optimal leaf ordering), 1px cell gaps, height ≈ 22px per index, full names + value in the hover, numbers printed in cells only up to `HEATMAP_TEXT_MAX` = 22 indices. Forcing square cells (`scaleanchor`) shrank the 41-index matrix to about 220px wide, so it is not used.
- **Heatmap palette**: both correlation heatmaps use `CORR_COLORSCALE` in `app.py` (blue = low/negative, grey = middle, red = high/positive). Change it there only. The raw heatmap's range is fixed at 0.4 to 1.0, the excess one at −1 to 1.
- **95% confidence intervals** (all four tables; `analytics.ci_*`, cached by `cached_ci` in `app.py`): each table's interval is for *its own* statistic, recomputed on resampled histories: lumpsum CAGR (`ci_cagr`), mean rolling lumpsum CAGR for the slider window (`ci_rolling_cagr_mean`), monthly-SIP XIRR (`ci_sip_irr`), mean rolling SIP IRR for the slider window (`ci_rolling_sip_mean`). Resampling is a circular block bootstrap of daily log returns in 126-day blocks (keeps volatility clustering), the same blocks for every index, fixed seed (identical inputs give identical intervals), percentile interval 2.5%–97.5%; B = 600 / 300 / 400 / 200. Bootstrap SIP IRRs use the closed-form monthly annuity (`monthly_sip_irr`, within about 0.1 pp of exact XIRR per window); the tables' point estimates still use exact XIRR. Intervals are for the long-run value of the statistic, **not** the range of single-year or single-window returns, and they assume the future resembles the resampled past (backtested history included). Cold timing with all 41 indices: about 0.6–1.9 s per table.
- **Merging**: outer merge on Date, then `ffill().bfill()`. This is safe because every index starts 2005-04-01. A later-starting index would get a fake flat history from `bfill`.

## Dev commands
Use the `main` conda env (`conda activate main`). Package versions are in `requirements.txt`.
- Run the app: `python app.py` (port 4400, `debug=True`, auto-reloads on save).
- Refresh data: `python download_new_indices.py` (exits 1 and keeps old files if any index-year fails).
- Test: `python -m unittest discover -s tests -t .`
- Re-run the notebook: `jupyter nbconvert --to notebook --execute --inplace Indian_Indices_Analysis.ipynb`

## Testing requirements
All tests must pass before committing (there is no CI or git hook yet; run them by hand). Any new calculation needs a known-answer test in `tests/test_analytics.py`. Any new callback or output is covered automatically by `TestEveryCallbackWithDefaults`; add interaction or edge-case tests in `tests/test_app_e2e.py`.
- The e2e harness must JSON-encode payloads with `plotly.utils.PlotlyJSONEncoder`. Flask's encoder turns `datetime.date` values into `"Wed, 01 Apr 2005 00:00:00 GMT"` strings, which pandas rejects.
- Plotly 6 sends numeric arrays as `{"dtype","bdata"}` typed arrays. Decode them with `arr()` in the e2e tests.

## Known Issues / Mistakes Log
Newest at the bottom. Append only.

### NSE endpoint moved; the old URL still answers 200 with HTML (2026-09-28)
- **What happened:** the July 2026 refresh silently lost all 2026 data. `data/` ended on 2025-12-31 while the docs claimed 2026-06-17.
- **Root cause:** `/Backpage.aspx/getTotalReturnIndexString` now returns the site's home page (HTTP 200). The new endpoint is `/BackPage/getTotalReturnIndexString`, and it returns a bare JSON list (content-type text/html) instead of `{"d": "<json string>"}`. The script also deleted `data/*.csv` *before* downloading.
- **Fix / avoid by:** `parse_response()` accepts both shapes and rejects anything else. The script no longer deletes `data/`, only writes an index when every year is present, and exits 1 on failure. If NSE changes the endpoint again, find the current URL in `https://liveindexsa.niftyindices.com/assets/js/IISLComponet.js` (search for `TotalReturnIndexString`). The site limits each request to at most 1 year.

### Current-year cache went stale forever (2026-09-28)
- **What happened:** a `cache/*_{current year}.csv` written mid-year would be reused on every later run.
- **Fix / avoid by:** years < the current year come from cache; the current year is always re-fetched, with the stale cache used only as a fallback.

### Linear/Log toggle did nothing (2026-09-28) (obsolete 2026-10-17: the growth chart and toggle were removed)
- **What happened:** the growth chart was always on a log scale.
- **Root cause:** `dbc.Button.active` does not change on click, and no callback updated it.
- **Fix / avoid by:** the `toggle_scale` callback flips `active` and `outline` from `n_clicks`.

### Tables sorted alphabetically (2026-09-28)
- **What happened:** "Click headers to sort" put "9.5%" above "17%".
- **Root cause:** values were preformatted strings.
- **Fix / avoid by:** `make_table()` keeps numbers numeric (`type: numeric` + `dash_table.Format`). Only unsortable, mixed-unit Deep Dive tables use strings.

### Rolling tabs ignored the date range; windows used a fixed 252 rows (2026-09-28)
- **Root cause:** `update_tab2` and `update_tab4` read the full `df_daily`, and the data has about 248 trading days a year, so "5 years" was about 5.08 years.
- **Fix / avoid by:** every callback slices via `filter_dates()`, and windows are calendar-based (`analytics.rolling_windows`).

### Volatility labels were swapped (2026-09-28)
- **What happened:** "Worst-Case Volatility" showed the *minimum* volatility.
- **Fix / avoid by:** the columns are now "Lowest Volatility" and "Highest Volatility".

### SIP maths (2026-09-28)
- **What happened:** the SIP drawdown compared value with a raw peak, so fresh instalments hid losses. The daily return formula `V_t/(V_{t−1}+CF_t) − 1` understated returns on SIP days.
- **Fix / avoid by:** flow-adjusted drawdown and TWR `(V_t − CF_t)/V_{t−1} − 1` in `simulate_sip`, both covered by tests. The rolling SIP loop was also vectorised (about 2 s → 0.15 s).

### Docs drifted from the code and data (2026-09-28)
- **What happened:** the README described a "Portfolio Builder" tab that doesn't exist, port 8050 (the real port is 4400), 11 of 19 indices in the table, and optimiser weights (61.8/30.7/7.5) the notebook never produced. The notebook's conclusions claimed the optimised blend had "the highest Sortino" when its own output showed it below Low-Vol alone.
- **Fix / avoid by:** after any data refresh, re-run the notebook and regenerate the README table from `analytics.run_metrics_analysis`. Never hand-type numbers.

### Correlation heatmaps used opposite colour directions (2026-10-01)
- **What happened:** the raw heatmap was red = high (`rdbu_r`) while the new excess heatmap was blue = high, so the same colour meant opposite things one card apart.
- **Fix / avoid by:** a single `CORR_COLORSCALE` constant feeds both, and `TestCorrelationPalette` asserts they are identical. Never pass a named colour scale to a correlation heatmap.

### Sharpe and Sortino used a (CAGR − rf) / volatility shortcut (2026-10-23)
- **What happened:** `run_metrics_analysis` computed Sharpe as (CAGR − 6%) / volatility and Sortino as (CAGR − 6%) / downside volatility (target 0), mixing a geometric return with arithmetic risk.
- **Fix / avoid by:** textbook versions on periodic excess returns (`risk_adjusted`), with Sortino's downside measured below rf; covered by known-answer tests in `TestRiskAdjusted`. Rankings at the top of the table shift slightly (Total Market MQ 50 now edges MQVLv 50 on Sortino).

### Notebook optimiser caveat (open)
- The optimiser scores weekly-rebalanced *arithmetic* mean returns, but the portfolio it then evaluates is buy-and-hold (`norm_prices.dot(weights)`), and the weights are fitted in-sample. Treat its "optimal" weights as illustrative only.

### Deprecation to plan for (open)
- Dash warns that `dash_table.DataTable` will leave core Dash in a future major version. When upgrading Dash, move to `dash-ag-grid` or pin Dash 3.x.

## Data availability (checked 2026-10-01)
- niftyindices.com serves PE/PB/dividend yield at `/BackPage/getpepbHistoricaldataDBtoString` (same `cinfo` payload as the TRI call, 1-year limit). History back to 2005 exists only for Nifty 50, Nifty Next 50 and Nifty 500. Midcap 150, Microcap 250, Total Market, Alpha 30, Value 50, Quality 30 have it only from some later year, and the other factor indices (Momentum, Low Vol, MQVLv, Momentum-Quality, Nifty200 Momentum 30) returned nothing for 2006, 2015 and 2024. Nothing here fetches it yet. ROE and earnings growth are not offered by this site at all.

## Where to look
| Question | File |
|---|---|
| How is metric X computed? | `analytics.py`, plus the Methodology section above |
| Which callback drives chart Y? | `app.py`: search for the component id |
| How is NSE data fetched? | `download_new_indices.py` + the first Mistakes Log entry |
| How was the notebook's optimiser built? | `Indian_Indices_Analysis.ipynb`, cells 11–14 |
