"""Pure analytics used by app.py (and the tests). No Dash imports here.

Conventions (shared by every tab):
- Prices are daily TRI levels in a DataFrame indexed by Date, one column per index.
- Returns and ratios are fractions (0.12 = 12%); the UI multiplies by 100 for display.
- "Downside volatility" is the root-mean-square of negative returns (target 0), annualised,
  i.e. the denominator of the Sortino ratio. "Return / Volatility" and
  "Return / Downside Volatility" are the rf = 0 analogues of Sharpe and Sortino.
- Rolling windows are calendar-based (N years back from each date), not a fixed row count.
"""
import os
import glob
import numpy as np
import pandas as pd
from scipy import stats

DATA_DIR = "data"
RF_RATE = 0.06
TRADING_DAYS = 252
WEEKS = 52


# -------------------------------------------------------------
# Data loading
# -------------------------------------------------------------
def load_data(data_dir=DATA_DIR):
    files = glob.glob(os.path.join(data_dir, "*_TRI.csv"))
    if not files:
        raise ValueError("No index files found in data/ directory! Please run the download script first.")

    dfs = []
    for f in files:
        df = pd.read_csv(f)
        df['Date'] = pd.to_datetime(df['Date'])
        dfs.append(df)

    master_df = dfs[0]
    for df in dfs[1:]:
        master_df = pd.merge(master_df, df, on='Date', how='outer')

    master_df = master_df.sort_values('Date').reset_index(drop=True)
    master_df.set_index('Date', inplace=True)
    master_df = master_df.ffill().bfill()
    return master_df[sorted(master_df.columns)]


# -------------------------------------------------------------
# Core risk / return helpers
# -------------------------------------------------------------
def downside_deviation(returns, periods_per_year):
    """Annualised downside deviation: sqrt(mean(min(r, 0)^2)) * sqrt(periods)."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.minimum(r, 0.0) ** 2)) * np.sqrt(periods_per_year))


def safe_ratio(num, den):
    return num / den if den and den > 0 else 0.0


def drawdown_series(prices):
    running_max = prices.cummax()
    return (prices - running_max) / running_max


def per_period_rf(rf_rate, periods_per_year):
    """Annual risk-free rate converted to one period (compounding): (1 + rf)^(1/periods) - 1."""
    return (1.0 + rf_rate) ** (1.0 / periods_per_year) - 1.0


def risk_adjusted(returns, rf_rate, periods_per_year, benchmark_returns):
    """Textbook risk-adjusted measures for each column of periodic simple returns.

    Sharpe  = mean(r - rf_p) / std(r - rf_p) * sqrt(P)
    Sortino = mean(r - rf_p) / sqrt(mean(min(r - rf_p, 0)^2)) * sqrt(P)      (downside below the risk-free rate)
    Risk-Adjusted Return (M², Modigliani-Modigliani) = rf + Sharpe * sigma_benchmark (annualised),
        i.e. the return the index would have earned at the benchmark's volatility.
    rf_p = per-period risk-free rate. NaN where a ratio is undefined (no variation or no shortfall)."""
    returns = pd.DataFrame(returns)
    rf_p = per_period_rf(rf_rate, periods_per_year)
    excess = returns - rf_p
    root_p = np.sqrt(periods_per_year)
    mean_ex = excess.mean()
    sd = excess.std(ddof=1)
    shortfall = np.sqrt((np.minimum(excess, 0.0) ** 2).mean())
    sharpe = (mean_ex / sd.where(sd > 0)) * root_p
    sortino = (mean_ex / shortfall.where(shortfall > 0)) * root_p
    bench_sd = pd.Series(benchmark_returns).std(ddof=1) * root_p
    return pd.DataFrame({"Sharpe Ratio": sharpe, "Sortino Ratio": sortino,
                         "Risk-Adjusted Return": rf_rate + sharpe * bench_sd})


def window_risk_adjusted(prices, benchmark, start_pos, end_pos, rf_rate, periods_per_year=TRADING_DAYS):
    """Sharpe, Sortino and M² from daily returns inside each window (start_pos, end_pos].
    prices: (n, k) array; benchmark: (n,) array; returns three (W, k) arrays. Same formulas as `risk_adjusted`."""
    p = np.asarray(prices, dtype=float)
    b = np.asarray(benchmark, dtype=float)[:, None]
    r = np.vstack([np.zeros((1, p.shape[1])), p[1:] / p[:-1] - 1.0])
    rb = np.vstack([np.zeros((1, 1)), b[1:] / b[:-1] - 1.0])
    rf_p = per_period_rf(rf_rate, periods_per_year)
    shortfall_sq = np.minimum(r - rf_p, 0.0) ** 2
    shortfall_sq[0] = 0.0                                     # placeholder first row never enters a window
    s, e = start_pos + 1, end_pos + 1
    n = (end_pos - start_pos)[:, None].astype(float)

    def window_sum(a):
        c = _cumsum0(a)
        return c[e] - c[s]

    s1, s2, sd_ = window_sum(r), window_sum(r ** 2), window_sum(shortfall_sq)
    b1, b2 = window_sum(rb), window_sum(rb ** 2)
    root_p = np.sqrt(periods_per_year)
    with np.errstate(invalid='ignore', divide='ignore'):
        sd = np.sqrt(np.clip((s2 - s1 ** 2 / n) / (n - 1), 0, None))
        bench_sd = np.sqrt(np.clip((b2 - b1 ** 2 / n) / (n - 1), 0, None)) * root_p
        mean_ex = s1 / n - rf_p
        sharpe = np.where(sd > 0, mean_ex / sd, np.nan) * root_p
        down = np.sqrt(sd_ / n)
        sortino = np.where(down > 0, mean_ex / down, np.nan) * root_p
    return sharpe, sortino, rf_rate + sharpe * bench_sd


def run_metrics_analysis(df, rf_rate=RF_RATE, benchmark=None):
    """Point-to-point metrics per column. Volatilities and risk-adjusted ratios use weekly (W-SUN, i.e. Friday
    close) returns. `benchmark`: price Series (same dates) for the M² risk-adjusted return; omitted -> NaN."""
    metrics = {}
    years = (df.index[-1] - df.index[0]).days / 365.25
    returns_weekly = df.resample('W').last().pct_change().dropna()
    if benchmark is not None:
        bench_weekly = benchmark.resample('W').last().pct_change().dropna()
    else:
        bench_weekly = pd.Series(np.nan, index=returns_weekly.index)
    ra = risk_adjusted(returns_weekly, rf_rate, WEEKS, bench_weekly)
    for col in df.columns:
        p_start = df[col].iloc[0]
        p_end = df[col].iloc[-1]
        cagr = (p_end / p_start) ** (1 / years) - 1 if years > 0 else 0.0
        vol = returns_weekly[col].std() * np.sqrt(WEEKS) if len(returns_weekly) > 1 else 0.0
        dvol = downside_deviation(returns_weekly[col], WEEKS)
        metrics[col] = {
            "CAGR": cagr,
            "Volatility": vol,
            "Downside Volatility": dvol,
            "Return / Volatility": safe_ratio(cagr, vol),
            "Return / Downside Volatility": safe_ratio(cagr, dvol),
            "Sharpe Ratio": ra.loc[col, "Sharpe Ratio"],
            "Sortino Ratio": ra.loc[col, "Sortino Ratio"],
            "Risk-Adjusted Return": ra.loc[col, "Risk-Adjusted Return"],
            "Max Drawdown": drawdown_series(df[col]).min(),
        }
    return pd.DataFrame(metrics).T


# -------------------------------------------------------------
# XIRR (vectorised bisection)
# -------------------------------------------------------------
def xirr_matrix(cash_flows, years, low=-0.99, high=5.0, iterations=100):
    """Solve IRR row-wise. cash_flows, years: (W, K) arrays; years measured from each row's first flow.
    Assumes the usual SIP shape (outflows then one final inflow), so NPV is decreasing in r."""
    cf = np.asarray(cash_flows, dtype=float)
    t = np.asarray(years, dtype=float)
    lo = np.full(cf.shape[0], low)
    hi = np.full(cf.shape[0], high)

    def npv(r):
        return np.sum(cf / (1.0 + r[:, None]) ** t, axis=1)

    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        positive = npv(mid) > 0
        lo = np.where(positive, mid, lo)
        hi = np.where(positive, hi, mid)
    return (lo + hi) / 2.0


def calculate_xirr(cash_flows, dates):
    t0 = dates[0]
    years = [(d - t0).days / 365.25 for d in dates]
    return float(xirr_matrix([cash_flows], [years])[0])


# -------------------------------------------------------------
# Rolling lumpsum windows
# -------------------------------------------------------------
def _cumsum0(a):
    """Cumulative sum along axis 0 with a leading zero row: C[k] = sum(a[:k])."""
    return np.vstack([np.zeros((1,) + a.shape[1:]), np.cumsum(a, axis=0)])


def window_moments(prices, start_pos, end_pos):
    """Annualised volatility and downside volatility of daily returns in (start_pos, end_pos].
    prices: (n, k) array; start_pos/end_pos: integer arrays of equal length."""
    r = np.vstack([np.zeros((1, prices.shape[1])), prices[1:] / prices[:-1] - 1.0])
    c1, c2, cd = _cumsum0(r), _cumsum0(r ** 2), _cumsum0(np.minimum(r, 0.0) ** 2)
    s, e = start_pos + 1, end_pos + 1
    n = (end_pos - start_pos)[:, None].astype(float)
    sum1, sum2, sumd = c1[e] - c1[s], c2[e] - c2[s], cd[e] - cd[s]
    with np.errstate(invalid='ignore', divide='ignore'):
        var = (sum2 - sum1 ** 2 / n) / (n - 1)
        vol = np.sqrt(np.clip(var, 0, None)) * np.sqrt(TRADING_DAYS)
        dvol = np.sqrt(sumd / n) * np.sqrt(TRADING_DAYS)
    return vol, dvol


def window_positions(index, years):
    """Row positions (start, end) of every calendar N-year window that fits inside `index`."""
    targets = index - pd.DateOffset(years=years)
    start_pos = index.searchsorted(targets, side='right') - 1
    valid = (targets >= index[0]) & (start_pos >= 0)
    return start_pos[valid], np.arange(len(index))[valid]


def rolling_windows(prices, years):
    """For every end date with a full N-year history inside `prices`, return a dict of
    DataFrames indexed by end date: start (window start date), cagr, vol, dvol."""
    idx = prices.index
    start_pos, end_pos = window_positions(idx, years)
    empty = pd.DataFrame(columns=prices.columns, dtype=float)
    if len(end_pos) == 0:
        return {"start": pd.Series(dtype='datetime64[ns]'), "cagr": empty, "vol": empty, "dvol": empty}

    p = prices.to_numpy(dtype=float)
    elapsed = (idx[end_pos] - idx[start_pos]).days.to_numpy() / 365.25
    cagr = (p[end_pos] / p[start_pos]) ** (1.0 / elapsed[:, None]) - 1.0
    vol, dvol = window_moments(p, start_pos, end_pos)
    end_idx = idx[end_pos]
    return {
        "start": pd.Series(idx[start_pos], index=end_idx),
        "cagr": pd.DataFrame(cagr, index=end_idx, columns=prices.columns),
        "vol": pd.DataFrame(vol, index=end_idx, columns=prices.columns),
        "dvol": pd.DataFrame(dvol, index=end_idx, columns=prices.columns),
    }


# -------------------------------------------------------------
# SIP simulation
# -------------------------------------------------------------
def monthly_sip_dates(index):
    """First trading day of every month in the index."""
    s = pd.Series(index, index=index)
    return list(s.groupby(index.to_period('M')).min())


def simulate_sip(prices, sip_dates, amount=10000.0):
    """Monthly SIP into a single price series. Returns a DataFrame with value, invested,
    twr_return (flow-neutral daily return) and drawdown (flow-adjusted)."""
    cf = pd.Series(0.0, index=prices.index)
    cf.loc[sip_dates] = amount
    units = (cf / prices).cumsum()
    value = units * prices
    invested = cf.cumsum()

    # Time-weighted return strips out the day's contribution: (V_t - CF_t) / V_{t-1} - 1.
    prev = value.shift(1)
    twr = ((value - cf) / prev - 1.0).where(prev > 0)

    # Flow-adjusted drawdown: compare today's value with the best past value plus every rupee
    # contributed since then, so new instalments cannot hide a fall.
    # peak_t = max_s (V_s + C_t - C_s) = C_t + cummax(V - C)_t
    peak = invested + (value - invested).where(invested > 0).cummax()
    drawdown = (value / peak - 1.0).where(invested > 0).fillna(0.0)
    return pd.DataFrame({"value": value, "invested": invested, "cash_flow": cf,
                         "twr_return": twr, "drawdown": drawdown})


def rolling_sip(prices, years, amount=10000.0):
    """Rolling N-year monthly SIPs inside `prices`. One window per start month; each window
    has N*12 instalments and is valued on the first trading day of the following month.
    Returns dict of DataFrames indexed by valuation date: irr, vol, dvol, start."""
    m_dates = monthly_sip_dates(prices.index)
    n = int(round(years * 12))
    w = len(m_dates) - n
    if w <= 0:
        return None
    m_idx = pd.DatetimeIndex(m_dates)
    pos = prices.index.get_indexer(m_idx)
    p = prices.to_numpy(dtype=float)
    pm = p[pos]                                      # (M, k) prices on SIP dates

    starts = np.arange(w)
    inst = starts[:, None] + np.arange(n)[None, :]   # (W, n) instalment row numbers
    val_rows = starts + n                            # valuation row numbers
    day_num = (m_idx - m_idx[0]).days.to_numpy()
    t_inst = (day_num[inst] - day_num[starts][:, None]) / 365.25
    t_val = (day_num[val_rows] - day_num[starts]) / 365.25
    t = np.hstack([t_inst, t_val[:, None]])

    inv_cum = _cumsum0(1.0 / pm)                     # cumulative units per rupee
    irr = np.empty((w, p.shape[1]))
    for j in range(p.shape[1]):
        units = amount * (inv_cum[val_rows, j] - inv_cum[starts, j])
        final = units * pm[val_rows, j]
        cf = np.hstack([np.full((w, n), -amount), final[:, None]])
        irr[:, j] = xirr_matrix(cf, t)

    # SIP volatility: the flow-neutral return of a single-asset SIP is exactly the index's
    # daily return, so SIP volatility = index volatility over the SIP window.
    vol, dvol = window_moments(p, pos[starts], pos[val_rows])
    end_idx = m_idx[val_rows]
    cols = prices.columns
    return {
        "start": pd.Series(m_idx[starts], index=end_idx),
        "irr": pd.DataFrame(irr, index=end_idx, columns=cols),
        "vol": pd.DataFrame(vol, index=end_idx, columns=cols),
        "dvol": pd.DataFrame(dvol, index=end_idx, columns=cols),
    }


# -------------------------------------------------------------
# Deep-dive helpers (two-fund comparison)
# -------------------------------------------------------------
def distribution_stats(values):
    v = pd.Series(values).dropna()
    if v.empty:
        return {}
    return {
        "Windows": float(len(v)),
        "Mean": v.mean(),
        "Median": v.median(),
        "Mode (KDE peak)": kde_mode(v),
        "Std Dev": v.std(),
        "Skewness": float(stats.skew(v)) if len(v) > 2 else 0.0,
        "Minimum": v.min(),
        "5th Percentile": v.quantile(0.05),
        "10th Percentile": v.quantile(0.10),
        "25th Percentile": v.quantile(0.25),
        "75th Percentile": v.quantile(0.75),
        "90th Percentile": v.quantile(0.90),
        "95th Percentile": v.quantile(0.95),
        "Maximum": v.max(),
        "% Windows Negative": (v < 0).mean(),
        "% Windows Below 6% (FD rate)": (v < RF_RATE).mean(),
        "% Windows Above 12%": (v > 0.12).mean(),
        "% Windows Above 15%": (v > 0.15).mean(),
    }


def kde_curve(values, points=300):
    v = pd.Series(values).dropna().to_numpy()
    if len(v) < 3 or np.ptp(v) == 0:
        return np.array([]), np.array([])
    kde = stats.gaussian_kde(v)
    pad = 0.1 * np.ptp(v)
    x = np.linspace(v.min() - pad, v.max() + pad, points)
    return x, kde(x)


def kde_mode(values):
    x, y = kde_curve(values, points=600)
    return float(x[np.argmax(y)]) if len(x) else float('nan')


def drawdown_episodes(prices, top_n=5):
    """Largest peak-to-trough episodes. Recovery is the first date back at the old peak."""
    dd = drawdown_series(prices)
    under = dd < 0
    episodes = []
    if not under.any():
        return episodes
    group = (under != under.shift()).cumsum()
    for _, seg in dd[under].groupby(group[under]):
        start_loc = dd.index.get_loc(seg.index[0])
        peak_date = dd.index[start_loc - 1] if start_loc > 0 else seg.index[0]
        trough_date = seg.idxmin()
        end_loc = dd.index.get_loc(seg.index[-1])
        recovered = end_loc + 1 < len(dd)
        recovery_date = dd.index[end_loc + 1] if recovered else None
        episodes.append({
            "Peak": peak_date,
            "Trough": trough_date,
            "Recovery": recovery_date,
            "Depth": seg.min(),
            "Days to Trough": (trough_date - peak_date).days,
            "Days to Recover": (recovery_date - trough_date).days if recovered else None,
            "Days Underwater": ((recovery_date if recovered else dd.index[-1]) - peak_date).days,
        })
    episodes.sort(key=lambda e: e["Depth"])
    return episodes[:top_n]


def calendar_year_returns(prices):
    """Year-by-year return; first and last years are partial (labelled by the caller)."""
    year_end = prices.groupby(prices.index.year).last()
    prev = year_end.shift(1)
    prev.iloc[0] = prices.iloc[0]
    return year_end / prev - 1.0


def capture_ratios(ret_a, ret_b):
    """Up/down capture of A relative to B using geometric mean returns in B's up/down periods."""
    def geo(r):
        return (1 + r).prod() ** (1 / len(r)) - 1 if len(r) else np.nan
    up, down = ret_b > 0, ret_b < 0
    up_cap = geo(ret_a[up]) / geo(ret_b[up]) if up.any() else np.nan
    down_cap = geo(ret_a[down]) / geo(ret_b[down]) if down.any() else np.nan
    return up_cap, down_cap


def relationship_stats(prices_a, prices_b, rf_rate=RF_RATE):
    """How A behaves relative to B over the whole period."""
    pair = pd.concat([prices_a, prices_b], axis=1)
    wk = pair.resample('W').last().pct_change().dropna()
    mo = pair.resample('ME').last().pct_change().dropna()
    ra, rb = wk.iloc[:, 0], wk.iloc[:, 1]
    years = (pair.index[-1] - pair.index[0]).days / 365.25
    cagr_a = (prices_a.iloc[-1] / prices_a.iloc[0]) ** (1 / years) - 1
    cagr_b = (prices_b.iloc[-1] / prices_b.iloc[0]) ** (1 / years) - 1
    te = (ra - rb).std() * np.sqrt(WEEKS)
    up_cap, down_cap = capture_ratios(mo.iloc[:, 0], mo.iloc[:, 1])
    monthly_win = (mo.iloc[:, 0] > mo.iloc[:, 1]).mean()
    return {
        "Correlation (weekly returns)": ra.corr(rb),
        "Beta of A vs B (weekly)": ra.cov(rb) / rb.var() if rb.var() > 0 else np.nan,
        "Tracking Error (A - B, annualised)": te,
        "Information Ratio (CAGR gap / TE)": safe_ratio(cagr_a - cagr_b, te),
        "Up-Market Capture of A vs B (monthly)": up_cap,
        "Down-Market Capture of A vs B (monthly)": down_cap,
        "% Months A Beat B": monthly_win,
    }


# -------------------------------------------------------------
# Correlation of excess returns (diversification beyond the market)
# -------------------------------------------------------------
def weekly_returns(prices):
    return prices.resample('W').last().pct_change().dropna()


def excess_return_correlation(prices, benchmark, columns):
    """Pearson correlation of weekly *excess* returns (index return minus benchmark return).
    The benchmark itself is dropped (its excess return is identically zero). Returns an empty
    DataFrame when fewer than two indices remain."""
    cols = [c for c in columns if c != benchmark]
    if len(cols) < 2:
        return pd.DataFrame()
    wk = weekly_returns(prices[list(dict.fromkeys(cols + [benchmark]))])
    excess = wk[cols].sub(wk[benchmark], axis=0)
    return excess.corr(method='pearson')


def pair_table(corr):
    """Unique index pairs from a correlation matrix, sorted from lowest to highest correlation."""
    names = list(corr.columns)
    rows = [(a, b, corr.loc[a, b]) for i, a in enumerate(names) for b in names[i + 1:]]
    return pd.DataFrame(rows, columns=["Index A", "Index B", "Correlation"]).sort_values("Correlation").reset_index(drop=True)


def fund_correlations(prices, fund, benchmark, columns):
    """Correlation of one fund with every other index in `columns`, on weekly returns.
    'Excess Correlation' is measured after subtracting the benchmark from both sides, 'Raw Correlation' before.
    The fund and the benchmark are never listed as rows. Empty when the fund *is* the benchmark (its excess is zero)."""
    others = [c for c in columns if c not in (fund, benchmark)]
    empty = pd.DataFrame(columns=["Index", "Excess Correlation", "Raw Correlation"])
    if fund == benchmark or not others:
        return empty
    wk = weekly_returns(prices[list(dict.fromkeys([fund, benchmark] + others))])
    excess = wk.sub(wk[benchmark], axis=0)
    return pd.DataFrame({
        "Index": others,
        "Excess Correlation": [excess[fund].corr(excess[o]) for o in others],
        "Raw Correlation": [wk[fund].corr(wk[o]) for o in others],
    })


def rolling_return_bounds(prices, windows):
    """Min/max over *every* window length in `windows` that fits inside `prices`, for a two-column
    price frame (A, B): the rolling CAGR of either fund, and the excess A - B. Used to keep chart axes
    fixed while the user changes the window. Fractions, not percent; None if no window fits."""
    a, b = prices.columns[:2]
    lo = hi = ex_lo = ex_hi = None
    for w in windows:
        cagr = rolling_windows(prices[[a, b]], w)["cagr"]
        if cagr.empty:
            continue
        excess = cagr[a] - cagr[b]
        lo = cagr.min().min() if lo is None else min(lo, cagr.min().min())
        hi = cagr.max().max() if hi is None else max(hi, cagr.max().max())
        ex_lo = excess.min() if ex_lo is None else min(ex_lo, excess.min())
        ex_hi = excess.max() if ex_hi is None else max(ex_hi, excess.max())
    if lo is None:
        return None
    return {"cagr": (float(lo), float(hi)), "excess": (float(ex_lo), float(ex_hi))}


def cluster_order(corr):
    """Row/column order that puts similar indices next to each other: average-linkage hierarchical
    clustering on distance = 1 - correlation, with optimal leaf ordering. Returns a list of labels."""
    from scipy.cluster.hierarchy import linkage, leaves_list, optimal_leaf_ordering
    from scipy.spatial.distance import squareform
    names = list(corr.columns)
    if len(names) < 3:
        return names
    dist = np.clip(1.0 - corr.to_numpy(dtype=float), 0.0, 2.0)
    dist = (dist + dist.T) / 2.0
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(dist, checks=False)
    tree = optimal_leaf_ordering(linkage(condensed, method='average'), condensed)
    return [names[i] for i in leaves_list(tree)]



# -------------------------------------------------------------
# 95% confidence intervals (circular block bootstrap)
# -------------------------------------------------------------
# Each table's interval is for *that table's own statistic*, recomputed on resampled histories:
#   lumpsum CAGR | mean rolling CAGR (slider window) | SIP XIRR | mean rolling SIP IRR (slider window).
# Resampling: daily log returns are re-stitched in BOOT_BLOCK-day blocks (circular), keeping volatility
# clustering; the same blocks are used for every index so cross-index comparisons stay coherent.
# Percentile interval (2.5%, 97.5%). Fixed seed: identical inputs always give identical intervals.
BOOT_BLOCK = 126          # about six months of trading days
BOOT_SEED = 0
CI_LEVEL = 0.95


def _bootstrap_rows(m, B, block=BOOT_BLOCK, seed=BOOT_SEED):
    """(B, m) row indices of a circular block bootstrap of a length-m series."""
    rng = np.random.default_rng(seed)
    k = int(np.ceil(m / block))
    starts = rng.integers(0, m, size=(B, k))
    return ((starts[:, :, None] + np.arange(block)) % m).reshape(B, -1)[:, :m]


def _bootstrap_paths(prices, B):
    """Yield (column, C) where C is a (B, n) array of resampled cumulative log-price paths starting at 0."""
    p = prices.to_numpy(dtype=float)
    logret = np.log(p[1:] / p[:-1])
    rows = _bootstrap_rows(len(logret), B)
    for j, col in enumerate(prices.columns):
        yield col, np.hstack([np.zeros((B, 1)), np.cumsum(logret[rows, j], axis=1)])


def _interval(samples):
    """samples: dict column -> (B,) array. Returns DataFrame with 'low' and 'high'."""
    tail = (1 - CI_LEVEL) / 2 * 100
    return pd.DataFrame({c: np.percentile(v, [tail, 100 - tail]) for c, v in samples.items()},
                        index=["low", "high"]).T


def monthly_sip_irr(value_per_rupee, n_instalments, months_after_last):
    """Annual IRR of n equal monthly instalments of 1 rupee that are worth `value_per_rupee` rupees in
    total, `months_after_last` months after the last instalment. Closed-form annuity future value,
    solved by bisection; agrees with the exact XIRR to about 0.1 pp per window (instalment dates fall on
    first trading days, not exactly a month apart). Used only for bootstrap resamples."""
    R = np.asarray(value_per_rupee, dtype=float)
    lo, hi = np.full(R.shape, -0.3), np.full(R.shape, 0.3)          # monthly rate bounds

    def fv(i):
        i = np.where(np.abs(i) < 1e-12, 1e-12, i)
        return (1 + i) ** months_after_last * ((1 + i) ** n_instalments - 1) / i

    for _ in range(60):
        mid = (lo + hi) / 2
        over = fv(mid) > R
        hi, lo = np.where(over, mid, hi), np.where(over, lo, mid)
    return (1 + (lo + hi) / 2) ** 12 - 1


def ci_cagr(prices, B=600):
    """95% CI of the point-to-point lumpsum CAGR of each column over the whole frame."""
    years = (prices.index[-1] - prices.index[0]).days / 365.25
    return _interval({c: np.expm1(C[:, -1] / years) for c, C in _bootstrap_paths(prices, B)})


def ci_rolling_cagr_mean(prices, years, B=300):
    """95% CI of the mean rolling N-year lumpsum CAGR (same windows as `rolling_windows`)."""
    sp, ep = window_positions(prices.index, years)
    if len(ep) == 0:
        return None
    elapsed = (prices.index[ep] - prices.index[sp]).days.to_numpy() / 365.25
    return _interval({c: np.expm1((C[:, ep] - C[:, sp]) / elapsed).mean(axis=1)
                      for c, C in _bootstrap_paths(prices, B)})


def _months(a, b):
    return (b - a).days / (365.25 / 12)


def ci_sip_irr(prices, sip_dates, B=400):
    """95% CI of the monthly-SIP XIRR over the whole frame (instalments on `sip_dates`, valued at the end)."""
    pos = prices.index.get_indexer(pd.DatetimeIndex(sip_dates))
    n = len(pos)
    after_last = _months(sip_dates[-1], prices.index[-1])
    out = {}
    for c, C in _bootstrap_paths(prices, B):
        P = np.exp(C)
        out[c] = monthly_sip_irr((1.0 / P[:, pos]).sum(axis=1) * P[:, -1], n, after_last)
    return _interval(out)


def ci_rolling_sip_mean(prices, years, B=200):
    """95% CI of the mean rolling N-year monthly-SIP IRR (same windows as `rolling_sip`)."""
    m_idx = pd.DatetimeIndex(monthly_sip_dates(prices.index))
    n = int(round(years * 12))
    w = len(m_idx) - n
    if w <= 0:
        return None
    pos = prices.index.get_indexer(m_idx)
    starts = np.arange(w)
    val_rows = starts + n
    after_last = np.array([_months(m_idx[s + n - 1], m_idx[v]) for s, v in zip(starts, val_rows)])
    out = {}
    for c, C in _bootstrap_paths(prices, B):
        pm = np.exp(C[:, pos])
        units = np.hstack([np.zeros((B, 1)), np.cumsum(1.0 / pm, axis=1)])
        value = (units[:, val_rows] - units[:, starts]) * pm[:, val_rows]      # (B, w) value per rupee
        out[c] = monthly_sip_irr(value, n, after_last[None, :]).mean(axis=1)
    return _interval(out)



# -------------------------------------------------------------
# Risk-adjusted measures for the rolling tables
# -------------------------------------------------------------
def rolling_risk_adjusted(prices, benchmark, years, rf_rate):
    """Per-window Sharpe, Sortino and M² for the same N-year lumpsum windows as `rolling_windows`.
    benchmark: price Series on prices.index. Returns dict of DataFrames indexed by window end date."""
    sp, ep = window_positions(prices.index, years)
    if len(ep) == 0:
        return None
    sharpe, sortino, m2 = window_risk_adjusted(prices.to_numpy(float), benchmark.to_numpy(float), sp, ep, rf_rate)
    end_idx = prices.index[ep]
    return {k: pd.DataFrame(v, index=end_idx, columns=prices.columns)
            for k, v in (("sharpe", sharpe), ("sortino", sortino), ("m2", m2))}


def rolling_sip_risk_adjusted(prices, benchmark, years, rf_rate):
    """Per-window Sharpe, Sortino and M² for the same N-year SIP windows as `rolling_sip`
    (first instalment to valuation date). A single-index SIP's flow-neutral return equals the index's
    daily return, so these use the index's daily returns over each SIP window."""
    m_idx = pd.DatetimeIndex(monthly_sip_dates(prices.index))
    n = int(round(years * 12))
    w = len(m_idx) - n
    if w <= 0:
        return None
    pos = prices.index.get_indexer(m_idx)
    starts = np.arange(w)
    sharpe, sortino, m2 = window_risk_adjusted(prices.to_numpy(float), benchmark.to_numpy(float),
                                               pos[starts], pos[starts + n], rf_rate)
    end_idx = m_idx[starts + n]
    return {k: pd.DataFrame(v, index=end_idx, columns=prices.columns)
            for k, v in (("sharpe", sharpe), ("sortino", sortino), ("m2", m2))}
