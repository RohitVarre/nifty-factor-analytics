"""Unit tests for analytics.py: synthetic series with known answers + reference (loop) implementations."""
import unittest
import numpy as np
import pandas as pd

import analytics as an


def const_growth(rate, start='2010-01-01', end='2022-12-31', cols=('x',)):
    d = pd.bdate_range(start, end)
    t = (d - d[0]).days / 365.25
    return pd.DataFrame({c: 100 * (1 + rate) ** t for c in cols}, index=d)


def old_scalar_xirr(cash_flows, dates):
    """The original app.py bisection, kept as a reference implementation."""
    t0 = dates[0]
    years = [(d - t0).days / 365.25 for d in dates]
    npv = lambda r: sum(cf / ((1 + r) ** y) for cf, y in zip(cash_flows, years))
    low, high = -0.99, 5.0
    for _ in range(100):
        mid = (low + high) / 2.0
        if npv(mid) > 0:
            low = mid
        else:
            high = mid
    return mid


class TestCoreMetrics(unittest.TestCase):
    def test_downside_deviation_formula(self):
        r = np.array([0.02, -0.01, 0.03, -0.02, 0.0])
        expected = np.sqrt(np.mean(np.array([0, -0.01, 0, -0.02, 0]) ** 2)) * np.sqrt(52)
        self.assertAlmostEqual(an.downside_deviation(r, 52), expected, places=12)

    def test_downside_deviation_all_positive_is_zero(self):
        self.assertEqual(an.downside_deviation([0.01, 0.02], 252), 0.0)

    def test_metrics_constant_growth(self):
        m = an.run_metrics_analysis(const_growth(0.10))
        self.assertAlmostEqual(m.loc['x', 'CAGR'], 0.10, places=6)
        self.assertAlmostEqual(m.loc['x', 'Max Drawdown'], 0.0, places=12)
        self.assertEqual(m.loc['x', 'Downside Volatility'], 0.0)
        self.assertEqual(m.loc['x', 'Return / Downside Volatility'], 0.0)  # guarded division

    def test_ratios_are_consistent(self):
        rng = np.random.default_rng(0)
        d = pd.bdate_range('2015-01-01', periods=1500)
        p = pd.DataFrame({'x': 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, len(d)))}, index=d)
        r = an.run_metrics_analysis(p, 0.06).loc['x']
        self.assertAlmostEqual(r['Return / Volatility'], r['CAGR'] / r['Volatility'])
        self.assertAlmostEqual(r['Return / Downside Volatility'], r['CAGR'] / r['Downside Volatility'])
        # Sharpe/Sortino are the textbook versions on weekly excess returns (not the old (CAGR - rf)/vol shortcut)
        wk = p.resample('W').last().pct_change().dropna()['x']
        ex = wk - ((1.06) ** (1 / 52) - 1)
        self.assertAlmostEqual(r['Sharpe Ratio'], ex.mean() / ex.std() * np.sqrt(52))
        self.assertAlmostEqual(r['Sortino Ratio'], ex.mean() / np.sqrt((np.minimum(ex, 0) ** 2).mean()) * np.sqrt(52))
        self.assertTrue(np.isnan(r['Risk-Adjusted Return']))          # no benchmark passed
        self.assertLess(r['Downside Volatility'], r['Volatility'] * 1.5)


class TestXirr(unittest.TestCase):
    def test_known_irr(self):
        dates = [pd.Timestamp('2020-01-01'), pd.Timestamp('2021-01-01')]
        self.assertAlmostEqual(an.calculate_xirr([-100, 110], dates), 1.1 ** (365.25 / 366) - 1, places=8)

    def test_matches_old_scalar_solver(self):
        rng = np.random.default_rng(1)
        dates = list(pd.date_range('2015-01-01', periods=37, freq='MS'))
        cfs = [-10000.0] * 36 + [float(rng.uniform(300000, 600000))]
        self.assertAlmostEqual(an.calculate_xirr(cfs, dates), old_scalar_xirr(cfs, dates), places=8)


class TestRolling(unittest.TestCase):
    def test_rolling_cagr_constant_growth(self):
        rw = an.rolling_windows(const_growth(0.15), 3)
        self.assertTrue(np.allclose(rw['cagr']['x'], 0.15, atol=1e-9))
        # first window must start on/after the first date and span ~3 calendar years
        span = (rw['cagr'].index.to_series() - rw['start']).dt.days
        self.assertTrue(((span >= 3 * 365 - 3) & (span <= 3 * 366 + 3)).all())

    def test_window_moments_match_pandas(self):
        rng = np.random.default_rng(2)
        d = pd.bdate_range('2012-01-01', '2020-12-31')
        p = pd.DataFrame({'x': 100 * np.cumprod(1 + rng.normal(0.0004, 0.012, len(d)))}, index=d)
        rw = an.rolling_windows(p, 2)
        for end in rw['cagr'].index[[0, 250, -1]]:
            start = rw['start'][end]
            r = p['x'].loc[start:end].pct_change().dropna()
            self.assertAlmostEqual(rw['vol'].loc[end, 'x'], r.std() * np.sqrt(252), places=10)
            self.assertAlmostEqual(rw['dvol'].loc[end, 'x'], an.downside_deviation(r, 252), places=10)

    def test_range_shorter_than_window_is_empty(self):
        rw = an.rolling_windows(const_growth(0.1, '2020-01-01', '2021-06-30'), 5)
        self.assertTrue(rw['cagr'].empty)

    def test_rolling_respects_input_range(self):
        p = const_growth(0.1, '2010-01-01', '2022-12-31')
        rw = an.rolling_windows(p.loc['2015-01-01':], 3)
        self.assertGreaterEqual(rw['start'].min(), pd.Timestamp('2015-01-01'))


class TestSip(unittest.TestCase):
    def test_constant_growth_sip_irr(self):
        rs = an.rolling_sip(const_growth(0.12), 3)
        self.assertTrue(np.allclose(rs['irr']['x'], 0.12, atol=1e-6))

    def test_rolling_sip_matches_loop_reference(self):
        rng = np.random.default_rng(3)
        d = pd.bdate_range('2012-01-01', '2019-12-31')
        p = pd.DataFrame({'x': 100 * np.cumprod(1 + rng.normal(0.0005, 0.011, len(d)))}, index=d)
        rs = an.rolling_sip(p, 2)
        months = an.monthly_sip_dates(p.index)
        for w in (0, 17, len(months) - 25):
            inst, val = months[w:w + 24], months[w + 24]
            units = sum(10000 / p.loc[m, 'x'] for m in inst)
            ref = old_scalar_xirr([-10000.0] * 24 + [units * p.loc[val, 'x']], inst + [val])
            self.assertAlmostEqual(rs['irr'].loc[val, 'x'], ref, places=8)

    def test_twr_equals_index_returns(self):
        p = const_growth(0.1, '2018-01-01', '2020-12-31')['x']
        p = p * (1 + 0.05 * np.sin(np.arange(len(p)) / 20))  # add wiggles
        sim = an.simulate_sip(p, an.monthly_sip_dates(p.index))
        twr = sim['twr_return'].dropna()
        self.assertTrue(np.allclose(twr, p.pct_change().loc[twr.index], atol=1e-12))

    def test_flow_adjusted_drawdown_not_masked_by_contributions(self):
        # Price halves in month 2 and stays flat; contributions keep flowing in.
        d = pd.bdate_range('2020-01-01', '2020-12-31')
        p = pd.Series(100.0, index=d)
        p[d >= '2020-03-01'] = 50.0
        sim = an.simulate_sip(p, an.monthly_sip_dates(d))
        # Before the fall: 2 instalments = 20k. After: 10k value + later 10k instalments at cost.
        # The loss of 10k on the earlier money must persist, not fade as new money arrives.
        dd_end = sim['drawdown'].iloc[-1]
        invested_end = sim['invested'].iloc[-1]
        self.assertAlmostEqual(dd_end, (invested_end - 10000) / invested_end - 1, places=10)
        # Worst point: day of the fall, 20k of old money now worth 10k plus the new 10k instalment.
        self.assertAlmostEqual(sim['drawdown'].min(), 20000 / 30000 - 1, places=10)


class TestDeepDiveHelpers(unittest.TestCase):
    def test_distribution_stats_symmetric(self):
        v = pd.Series(np.random.default_rng(4).normal(0.12, 0.05, 20000))
        s = an.distribution_stats(v)
        self.assertAlmostEqual(s['Median'], 0.12, delta=0.002)
        self.assertAlmostEqual(s['Mode (KDE peak)'], s['Median'], delta=0.01)  # peak at the median when symmetric
        self.assertAlmostEqual(s['% Windows Negative'], (v < 0).mean())
        self.assertLess(s['5th Percentile'], s['25th Percentile'])

    def test_drawdown_episodes(self):
        d = pd.bdate_range('2020-01-01', periods=10)
        p = pd.Series([100, 110, 99, 88, 105, 112, 111, 120, 90, 95], index=d, dtype=float)
        eps = an.drawdown_episodes(p, 5)
        self.assertEqual(len(eps), 3)
        worst = eps[0]
        self.assertAlmostEqual(worst['Depth'], 90 / 120 - 1)
        self.assertIsNone(worst['Recovery'])               # still underwater at the end
        second = eps[1]
        self.assertEqual(second['Peak'], d[1])
        self.assertEqual(second['Trough'], d[3])
        self.assertEqual(second['Recovery'], d[5])

    def test_calendar_year_returns(self):
        p = const_growth(0.1, '2019-01-01', '2021-12-31')['x']
        cy = an.calendar_year_returns(p)
        self.assertEqual(list(cy.index), [2019, 2020, 2021])
        self.assertTrue(np.allclose(cy.loc[[2020, 2021]], 0.1, atol=0.002))

    def test_capture_ratios(self):
        b = pd.Series([0.02, -0.01, 0.03, -0.02])
        up, down = an.capture_ratios(2 * b, b)
        self.assertGreater(up, 1.9)
        self.assertGreater(down, 1.9)

    def test_relationship_identical_series(self):
        base = const_growth(0.1, '2015-01-01', '2020-12-31')['x']
        p = base * (1 + 0.03 * np.sin(np.arange(len(base)) / 15))
        rel = an.relationship_stats(p.rename('a'), p.rename('b'))
        self.assertAlmostEqual(rel['Correlation (weekly returns)'], 1.0)
        self.assertAlmostEqual(rel['Beta of A vs B (weekly)'], 1.0)
        self.assertAlmostEqual(rel['Tracking Error (A - B, annualised)'], 0.0)


class TestExcessCorrelation(unittest.TestCase):
    @staticmethod
    def _prices(weekly_returns_by_col):
        """Build daily price series (constant within each week, stepping on Fridays) from weekly returns."""
        weeks = pd.date_range('2015-01-02', periods=len(next(iter(weekly_returns_by_col.values()))), freq='W-FRI')
        days = pd.bdate_range(weeks[0] - pd.Timedelta(days=4), weeks[-1])
        out = {}
        for col, r in weekly_returns_by_col.items():
            level = pd.Series(100 * np.cumprod(1 + np.asarray(r)), index=weeks)
            out[col] = level.reindex(days, method='bfill')  # level reached on Friday applies to Mon-Fri of that week
        return pd.DataFrame(out)

    def test_common_market_move_is_removed(self):
        rng = np.random.default_rng(10)
        n = 400
        market = rng.normal(0.002, 0.02, n)
        a_tilt, b_tilt = rng.normal(0, 0.01, n), rng.normal(0, 0.01, n)
        # A and B both = market + independent tilts: raw correlation is high, excess correlation ~0.
        prices = self._prices({'M': market, 'A': market + a_tilt, 'B': market + b_tilt})
        wk = an.weekly_returns(prices)
        raw = wk[['A', 'B']].corr().loc['A', 'B']
        ex = an.excess_return_correlation(prices, 'M', ['A', 'B']).loc['A', 'B']
        self.assertGreater(raw, 0.7)
        self.assertLess(abs(ex), 0.25)

    def test_shared_and_opposite_tilts(self):
        rng = np.random.default_rng(11)
        n = 400
        market, tilt = rng.normal(0.002, 0.02, n), rng.normal(0, 0.01, n)
        prices = self._prices({'M': market, 'A': market + tilt, 'B': market + 2 * tilt, 'C': market - tilt})
        c = an.excess_return_correlation(prices, 'M', ['A', 'B', 'C'])
        self.assertGreater(c.loc['A', 'B'], 0.99)   # same bet
        self.assertLess(c.loc['A', 'C'], -0.99)     # opposite bet

    def test_benchmark_dropped_and_shape(self):
        rng = np.random.default_rng(12)
        prices = self._prices({k: rng.normal(0.001, 0.02, 300) for k in 'MABC'})
        c = an.excess_return_correlation(prices, 'M', ['M', 'A', 'B', 'C'])
        self.assertEqual(list(c.columns), ['A', 'B', 'C'])
        self.assertTrue(np.allclose(np.diag(c.to_numpy()), 1.0))
        self.assertTrue(an.excess_return_correlation(prices, 'M', ['M', 'A']).empty)  # only one left

    def test_pair_table(self):
        corr = pd.DataFrame([[1, .5, -.2], [.5, 1, .1], [-.2, .1, 1]], index=list('ABC'), columns=list('ABC'))
        pt = an.pair_table(corr)
        self.assertEqual(len(pt), 3)
        self.assertEqual((pt.loc[0, 'Index A'], pt.loc[0, 'Index B']), ('A', 'C'))
        self.assertAlmostEqual(pt.loc[0, 'Correlation'], -.2)

    def test_fund_correlations_match_matrix_and_raw(self):
        rng = np.random.default_rng(13)
        n = 400
        market, tilt = rng.normal(0.002, 0.02, n), rng.normal(0, 0.01, n)
        prices = self._prices({'M': market, 'F': market + tilt, 'A': market + 2 * tilt,
                               'B': market - tilt, 'C': market + rng.normal(0, 0.01, n)})
        t = an.fund_correlations(prices, 'F', 'M', ['M', 'F', 'A', 'B', 'C'])
        self.assertEqual(list(t['Index']), ['A', 'B', 'C'])            # fund and benchmark are never rows
        self.assertEqual(list(t.columns), ['Index', 'Excess Correlation', 'Raw Correlation'])
        by = t.set_index('Index')
        self.assertGreater(by.loc['A', 'Excess Correlation'], 0.99)    # same bet as F
        self.assertLess(by.loc['B', 'Excess Correlation'], -0.99)      # opposite bet
        # identical to the matrix view, and raw equals plain weekly-return correlation
        matrix = an.excess_return_correlation(prices, 'M', ['F', 'A', 'B', 'C'])
        for o in 'ABC':
            self.assertAlmostEqual(by.loc[o, 'Excess Correlation'], matrix.loc['F', o])
            self.assertAlmostEqual(by.loc[o, 'Raw Correlation'], an.weekly_returns(prices)[['F', o]].corr().loc['F', o])

    def test_fund_correlations_edge_cases(self):
        prices = self._prices({k: np.random.default_rng(14).normal(0.001, 0.02, 200) for k in 'MFA'})
        self.assertTrue(an.fund_correlations(prices, 'M', 'M', ['M', 'F', 'A']).empty)   # fund is the benchmark
        self.assertTrue(an.fund_correlations(prices, 'F', 'M', ['F', 'M']).empty)         # nothing left to compare


class TestRollingReturnBounds(unittest.TestCase):
    def test_bounds_equal_manual_min_max_over_all_windows(self):
        rng = np.random.default_rng(20)
        d = pd.bdate_range('2008-01-01', '2020-12-31')
        p = pd.DataFrame({'A': 100 * np.cumprod(1 + rng.normal(0.0006, 0.012, len(d))),
                          'B': 100 * np.cumprod(1 + rng.normal(0.0004, 0.010, len(d)))}, index=d)
        b = an.rolling_return_bounds(p, range(1, 11))
        cagrs = [an.rolling_windows(p, w)['cagr'] for w in range(1, 11)]
        self.assertAlmostEqual(b['cagr'][0], min(c.min().min() for c in cagrs))
        self.assertAlmostEqual(b['cagr'][1], max(c.max().max() for c in cagrs))
        self.assertAlmostEqual(b['excess'][0], min((c['A'] - c['B']).min() for c in cagrs))
        self.assertAlmostEqual(b['excess'][1], max((c['A'] - c['B']).max() for c in cagrs))
        # every individual window's data sits inside the shared bounds, so one axis fits them all
        for w in (1, 4, 10):
            c = an.rolling_windows(p, w)['cagr']
            self.assertGreaterEqual(c.min().min(), b['cagr'][0])
            self.assertLessEqual(c.max().max(), b['cagr'][1])

    def test_only_windows_that_fit_count(self):
        p = pd.DataFrame({'A': const_growth(0.10, '2018-01-01', '2021-06-30')['x'],
                          'B': const_growth(0.05, '2018-01-01', '2021-06-30')['x']})
        b = an.rolling_return_bounds(p, range(1, 11))      # only 1, 2, 3 year windows fit
        self.assertAlmostEqual(b['cagr'][0], 0.05, places=6)
        self.assertAlmostEqual(b['cagr'][1], 0.10, places=6)
        self.assertAlmostEqual(b['excess'][0], 0.05, places=6)

    def test_none_when_nothing_fits(self):
        p = pd.DataFrame({'A': const_growth(0.1, '2020-01-01', '2020-06-30')['x'], 'B': const_growth(0.1, '2020-01-01', '2020-06-30')['x']})
        self.assertIsNone(an.rolling_return_bounds(p, range(1, 11)))


class TestClusterOrder(unittest.TestCase):
    def test_similar_indices_end_up_adjacent(self):
        rng = np.random.default_rng(30)
        n = 500
        f1, f2 = rng.normal(0, 0.01, n), rng.normal(0, 0.01, n)
        cols = {}
        for name in ['a1', 'a2', 'a3']:
            cols[name] = f1 + rng.normal(0, 0.002, n)
        for name in ['b1', 'b2', 'b3']:
            cols[name] = f2 + rng.normal(0, 0.002, n)
        shuffled = ['a1', 'b1', 'a2', 'b2', 'a3', 'b3']
        corr = pd.DataFrame(cols)[shuffled].corr()
        order = an.cluster_order(corr)
        self.assertEqual(sorted(order), sorted(shuffled))
        groups = ''.join(name[0] for name in order)
        self.assertIn(groups, ('aaabbb', 'bbbaaa'))      # each family contiguous

    def test_tiny_matrices_keep_their_order(self):
        corr = pd.DataFrame([[1, .2], [.2, 1]], index=['x', 'y'], columns=['x', 'y'])
        self.assertEqual(an.cluster_order(corr), ['x', 'y'])


class TestConfidenceIntervals(unittest.TestCase):
    @staticmethod
    def random_walk(start='2008-01-01', end='2022-12-31', seed=40, cols=('x', 'y')):
        rng = np.random.default_rng(seed)
        d = pd.bdate_range(start, end)
        return pd.DataFrame({c: 100 * np.cumprod(1 + rng.normal(0.0005, 0.012, len(d))) for c in cols}, index=d)

    def test_monthly_sip_irr_matches_exact_xirr_on_regular_months(self):
        # Exact solver on exact month fractions (calculate_xirr rounds dates to whole days, so it is not used here).
        value = 52.0                                          # 36 instalments of 1 rupee worth 52 rupees
        t = [i / 12 for i in range(36)] + [37 / 12]           # valued 2 months after the last instalment
        exact = an.xirr_matrix([[-1.0] * 36 + [value]], [t])[0]
        approx = an.monthly_sip_irr(np.array([value]), 36, 2.0)[0]
        self.assertAlmostEqual(approx, exact, places=6)

    def test_zero_volatility_gives_zero_width(self):
        d = pd.date_range('2010-01-01', '2020-12-31', freq='D')        # every calendar day: identical daily returns
        p = pd.DataFrame({'x': 100 * 1.12 ** ((d - d[0]).days / 365.25)}, index=d)
        for ci in (an.ci_cagr(p), an.ci_rolling_cagr_mean(p, 3)):
            self.assertAlmostEqual(ci.loc['x', 'low'], 0.12, places=6)
            self.assertAlmostEqual(ci.loc['x', 'high'], 0.12, places=6)
        sip = an.ci_sip_irr(p, an.monthly_sip_dates(p.index))
        self.assertLess(sip.loc['x', 'high'] - sip.loc['x', 'low'], 1e-9)
        self.assertAlmostEqual(sip.loc['x', 'low'], 0.12, delta=0.002)

    def test_contains_point_estimates_and_is_deterministic(self):
        p = self.random_walk()
        cagr = an.run_metrics_analysis(p)['CAGR']
        ci = an.ci_cagr(p)
        for c in p.columns:
            self.assertLess(ci.loc[c, 'low'], cagr[c])
            self.assertGreater(ci.loc[c, 'high'], cagr[c])
        pd.testing.assert_frame_equal(ci, an.ci_cagr(p))
        roll = an.rolling_windows(p, 3)['cagr'].mean()
        rci = an.ci_rolling_cagr_mean(p, 3)
        self.assertTrue(((rci['low'] < roll) & (roll < rci['high'])).all())
        rs = an.rolling_sip(p, 3)['irr'].mean()
        sci = an.ci_rolling_sip_mean(p, 3)
        self.assertTrue(((sci['low'] < rs) & (rs < sci['high'])).all())

    def test_longer_history_gives_narrower_interval(self):
        p = self.random_walk('2000-01-01', '2022-12-31')
        long_ci, short_ci = an.ci_cagr(p), an.ci_cagr(p.loc['2018-01-01':])
        self.assertLess((long_ci['high'] - long_ci['low'])['x'], (short_ci['high'] - short_ci['low'])['x'])

    def test_each_section_has_its_own_interval(self):
        p = self.random_walk()
        cis = [an.ci_cagr(p), an.ci_rolling_cagr_mean(p, 3), an.ci_rolling_cagr_mean(p, 5),
               an.ci_sip_irr(p, an.monthly_sip_dates(p.index)), an.ci_rolling_sip_mean(p, 3), an.ci_rolling_sip_mean(p, 5)]
        lows = [round(c.loc['x', 'low'], 8) for c in cis]
        self.assertEqual(len(set(lows)), len(lows))

    def test_window_longer_than_range_returns_none(self):
        p = self.random_walk('2020-01-01', '2022-06-30')
        self.assertIsNone(an.ci_rolling_cagr_mean(p, 5))
        self.assertIsNone(an.ci_rolling_sip_mean(p, 5))


class TestRiskAdjusted(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(50)
        self.r = pd.DataFrame({'a': rng.normal(0.003, 0.02, 600), 'b': rng.normal(0.001, 0.03, 600)})
        self.bench = pd.Series(rng.normal(0.002, 0.025, 600))

    def test_per_period_rf_compounds_back_to_annual(self):
        self.assertAlmostEqual((1 + an.per_period_rf(0.065, 252)) ** 252, 1.065)

    def test_known_answer(self):
        rf, P = 0.07, 52
        out = an.risk_adjusted(self.r, rf, P, self.bench)
        rf_p = 1.07 ** (1 / 52) - 1
        for c in 'ab':
            ex = self.r[c] - rf_p
            sharpe = ex.mean() / ex.std(ddof=1) * np.sqrt(P)
            sortino = ex.mean() / np.sqrt((np.minimum(ex, 0) ** 2).mean()) * np.sqrt(P)
            m2 = rf + sharpe * self.bench.std(ddof=1) * np.sqrt(P)
            self.assertAlmostEqual(out.loc[c, 'Sharpe Ratio'], sharpe)
            self.assertAlmostEqual(out.loc[c, 'Sortino Ratio'], sortino)
            self.assertAlmostEqual(out.loc[c, 'Risk-Adjusted Return'], m2)

    def test_m2_of_the_benchmark_is_its_own_average_return(self):
        rf, P = 0.06, 252
        out = an.risk_adjusted(self.bench.to_frame('bm'), rf, P, self.bench)
        expected = rf + (self.bench.mean() - an.per_period_rf(rf, P)) * P
        self.assertAlmostEqual(out.loc['bm', 'Risk-Adjusted Return'], expected)

    def test_higher_risk_free_rate_lowers_sharpe_and_sortino(self):
        lo = an.risk_adjusted(self.r, 0.02, 52, self.bench)
        hi = an.risk_adjusted(self.r, 0.10, 52, self.bench)
        self.assertTrue((hi['Sharpe Ratio'] < lo['Sharpe Ratio']).all())
        self.assertTrue((hi['Sortino Ratio'] < lo['Sortino Ratio']).all())

    def test_undefined_ratios_are_nan(self):
        flat = pd.DataFrame({'x': [0.01] * 50})                       # no variation, never below a 0% rf
        out = an.risk_adjusted(flat, 0.0, 52, self.bench[:50])
        self.assertTrue(np.isnan(out.loc['x', 'Sharpe Ratio']))
        self.assertTrue(np.isnan(out.loc['x', 'Sortino Ratio']))

    def test_rolling_windows_match_a_direct_calculation(self):
        rng = np.random.default_rng(51)
        d = pd.bdate_range('2010-01-01', '2018-12-31')
        p = pd.DataFrame({k: 100 * np.cumprod(1 + rng.normal(0.0005, 0.012, len(d))) for k in ('x', 'y')}, index=d)
        bench = pd.Series(100 * np.cumprod(1 + rng.normal(0.0004, 0.011, len(d))), index=d)
        ra = an.rolling_risk_adjusted(p, bench, 3, 0.065)
        starts = an.rolling_windows(p, 3)['start']
        for end in ra['sharpe'].index[[0, 300, -1]]:
            sl = p.loc[starts[end]:end].pct_change().dropna()
            direct = an.risk_adjusted(sl, 0.065, 252, bench.loc[starts[end]:end].pct_change().dropna())
            for c in ('x', 'y'):
                self.assertAlmostEqual(ra['sharpe'].loc[end, c], direct.loc[c, 'Sharpe Ratio'], places=8)
                self.assertAlmostEqual(ra['sortino'].loc[end, c], direct.loc[c, 'Sortino Ratio'], places=8)
                self.assertAlmostEqual(ra['m2'].loc[end, c], direct.loc[c, 'Risk-Adjusted Return'], places=8)

    def test_rolling_sip_windows_run_first_instalment_to_valuation(self):
        rng = np.random.default_rng(52)
        d = pd.bdate_range('2010-01-01', '2016-12-31')
        p = pd.DataFrame({'x': 100 * np.cumprod(1 + rng.normal(0.0005, 0.012, len(d)))}, index=d)
        bench = pd.Series(100 * np.cumprod(1 + rng.normal(0.0004, 0.011, len(d))), index=d)
        ra = an.rolling_sip_risk_adjusted(p, bench, 2, 0.06)
        rs = an.rolling_sip(p, 2)
        self.assertEqual(list(ra['sharpe'].index), list(rs['irr'].index))
        end = ra['sharpe'].index[10]
        start = rs['start'][end]
        direct = an.risk_adjusted(p.loc[start:end].pct_change().dropna(), 0.06, 252,
                                  bench.loc[start:end].pct_change().dropna())
        self.assertAlmostEqual(ra['sharpe'].loc[end, 'x'], direct.loc['x', 'Sharpe Ratio'], places=8)


if __name__ == '__main__':
    unittest.main()
