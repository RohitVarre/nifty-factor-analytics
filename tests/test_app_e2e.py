"""End-to-end tests of the Dash app through its real HTTP interface (Flask test client).

Every callback registered in app.py is fired through /_dash-update-component with the values
the layout ships with, then with edge-case inputs, exactly as the browser would send them.
"""
import json
import unittest

import base64

import numpy as np
import plotly

import app as dash_app

APP = dash_app.app
CLIENT = APP.server.test_client()
START, END = str(dash_app.min_date.date()), str(dash_app.max_date.date())


def arr(v):
    """Plotly 6 ships numeric arrays as {'dtype', 'bdata'} typed arrays; decode to a list."""
    if isinstance(v, dict) and 'bdata' in v:
        return np.frombuffer(base64.b64decode(v['bdata']), dtype=np.dtype(v['dtype'])).tolist()
    return list(v)


def find_component(component, cid):
    if getattr(component, 'id', None) == cid:
        return component
    children = getattr(component, 'children', None)
    if children is None:
        return None
    for child in (children if isinstance(children, (list, tuple)) else [children]):
        if hasattr(child, 'to_plotly_json'):
            found = find_component(child, cid)
            if found is not None:
                return found
    return None


def layout_value(cid, prop):
    comp = find_component(APP.layout, cid)
    assert comp is not None, f"component {cid} not in layout"
    return getattr(comp, prop, None)


def parse_outputs(output):
    if output.startswith('..'):
        parts = output.strip('.').split('...')
        return [dict(zip(('id', 'property'), p.rsplit('.', 1))) for p in parts], True
    cid, prop = output.rsplit('.', 1)
    return dict(id=cid, property=prop), False


DEPENDENCIES = json.loads(CLIENT.get('/_dash-dependencies').data)


def callback_for(output_id):
    for dep in DEPENDENCIES:
        if output_id in dep['output']:
            return dep
    raise KeyError(output_id)


def fire(dep, overrides=None, triggered=None):
    overrides = overrides or {}
    outputs, _ = parse_outputs(dep['output'])

    def val(i):
        key = f"{i['id']}.{i['property']}"
        return overrides[key] if key in overrides else layout_value(i['id'], i['property'])

    payload = {
        'output': dep['output'],
        'outputs': outputs,
        'inputs': [dict(i, value=val(i)) for i in dep['inputs']],
        'state': [dict(s, value=val(s)) for s in dep['state']],
        'changedPropIds': triggered or [f"{i['id']}.{i['property']}" for i in dep['inputs']],
    }
    # Encode exactly like Dash's front end would receive layout values (dates as ISO strings).
    body = json.dumps(payload, cls=plotly.utils.PlotlyJSONEncoder)
    return CLIENT.post('/_dash-update-component', data=body, content_type='application/json')


class TestLayout(unittest.TestCase):
    def test_index_page_serves(self):
        r = CLIENT.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'Nifty Factor Analytics Dashboard', r.data)

    def test_layout_endpoint(self):
        r = CLIENT.get('/_dash-layout')
        self.assertEqual(r.status_code, 200)
        body = r.data.decode()
        self.assertIn('Deep Dive Compare', body)
        self.assertNotIn('Best Times to Invest', body)

    def test_data_is_complete(self):
        self.assertEqual(len(dash_app.index_list), 41)   # 19 original + 22 added 2026-10-17, all from 1 Apr 2005
        self.assertEqual(dash_app.min_date, __import__('pandas').Timestamp('2005-04-01'))
        self.assertFalse(dash_app.df_daily.isna().any().any())


class TestEveryCallbackWithDefaults(unittest.TestCase):
    def test_all_callbacks_fire_without_error(self):
        for dep in DEPENDENCIES:
            with self.subTest(output=dep['output']):
                # prevent_initial_call callbacks need a real trigger value
                overrides = {'start-year-dropdown.value': 2010}
                r = fire(dep, overrides)
                self.assertIn(r.status_code, (200, 204), r.data[:500])
                if r.status_code == 200:
                    self.assertIn('response', json.loads(r.data))


class TestInteractions(unittest.TestCase):
    def response(self, output_id, overrides, triggered=None):
        r = fire(callback_for(output_id), overrides, triggered)
        self.assertEqual(r.status_code, 200, r.data[:500])
        return json.loads(r.data)['response']

    def test_first_four_tabs_have_tables_but_no_charts(self):
        tabs = {t.tab_id: t for t in find_component(APP.layout, 'main-tabs').children}

        def ids(component, kind):
            found = []
            if type(component).__name__ == kind and getattr(component, 'id', None):
                found.append(component.id)
            children = getattr(component, 'children', None)
            for child in (children if isinstance(children, (list, tuple)) else [children] if children is not None else []):
                if hasattr(child, 'to_plotly_json'):
                    found += ids(child, kind)
            return found

        for tab_id, table_id in [('tab-growth', 'lumpsum-metrics-table-container'), ('tab-rolling', 'rolling-summary-table-container'),
                                 ('tab-sip', 'sip-cumulative-table-container'), ('tab-sip-rolling', 'sip-rolling-summary-table-container')]:
            with self.subTest(tab=tab_id):
                self.assertEqual(ids(tabs[tab_id], 'Graph'), [])
                self.assertIn(table_id, ids(tabs[tab_id], 'Div'))
        self.assertIsNone(find_component(APP.layout, 'log-btn'))   # the scale toggle went with the chart

    def test_tables_are_numeric_for_sorting(self):
        resp = self.response('lumpsum-metrics-table-container.children', {})
        table = resp['lumpsum-metrics-table-container']['children']['props']['children']['props']
        types = {c['id']: c.get('type') for c in table['columns']}
        self.assertEqual(types['Index'], 'text')
        for col in ['Annualized Return', 'Downside Volatility', 'Sharpe Ratio', 'Sortino Ratio', 'Risk-Adjusted Return (M²)', 'Maximum Drawdown']:
            self.assertEqual(types[col], 'numeric', col)
            self.assertIsInstance(table['data'][0][col], float)

    def test_downside_columns_present_everywhere(self):
        for output_id in ['lumpsum-metrics-table-container.children', 'rolling-summary-table-container.children',
                          'sip-cumulative-table-container.children', 'sip-rolling-summary-table-container.children']:
            cid = output_id.split('.')[0]
            resp = self.response(output_id, {})
            cols = [c['id'] for c in resp[cid]['children']['props']['children']['props']['columns']]
            with self.subTest(table=cid):
                self.assertTrue(any('Downside Volatility' in c and 'Ratio' not in c for c in cols), cols)
                self.assertTrue(any('Sharpe Ratio' in c for c in cols), cols)
                self.assertTrue(any('Sortino Ratio' in c for c in cols), cols)
                self.assertTrue(any('Risk-Adjusted Return' in c for c in cols), cols)
                # removed on request: min/max volatility and the rf = 0 ratios
                for gone in ('Lowest Volatility', 'Highest Volatility', 'Return / Volatility Ratio', 'Return / Downside Volatility Ratio'):
                    self.assertNotIn(gone, cols)

    def test_rolling_tabs_follow_date_range(self):
        for output_id, slider in [('rolling-caption.children', 'rolling-window-slider.value'),
                                  ('sip-rolling-caption.children', 'sip-rolling-window-slider.value')]:
            cid = output_id.split('.')[0]
            resp = self.response(output_id, {'date-picker.start_date': '2015-01-01', 'date-picker.end_date': '2022-12-31', slider: 3})
            caption = resp[cid]['children']
            with self.subTest(tab=cid):
                self.assertIn('3-year', caption)
                self.assertRegex(caption, r'(Jan|Feb) 2018 to .* 2022')   # first window ends 3y after the start, last at the end

    def test_period_captions(self):
        resp = self.response('lumpsum-caption.children', {'date-picker.start_date': '2010-01-01', 'date-picker.end_date': '2020-12-31'})
        self.assertIn('Period: 04 Jan 2010 to 31 Dec 2020', resp['lumpsum-caption']['children'])   # first actual trading day shown
        resp = self.response('sip-caption.children', {'date-picker.start_date': '2010-01-01', 'date-picker.end_date': '2020-12-31'})
        self.assertIn('132 instalments', resp['sip-caption']['children'])

    def test_short_range_gives_message_not_error(self):
        resp = self.response('rolling-summary-table-container.children',
                             {'date-picker.start_date': '2023-01-01', 'date-picker.end_date': '2024-01-01', 'rolling-window-slider.value': 5})
        self.assertIn('shorter than', json.dumps(resp))

    def test_year_dropdown_sync_clamps_to_data(self):
        resp = self.response('date-picker.start_date', {'end-year-dropdown.value': dash_app.max_date.year,
                                                        'date-picker.end_date': '2000-12-31'},
                             ['end-year-dropdown.value'])
        self.assertLessEqual(resp['date-picker']['end_date'], END)

    def test_empty_selection_everywhere(self):
        for dep in DEPENDENCIES:
            if any(i['id'] == 'index-dropdown' for i in dep['inputs']):
                with self.subTest(output=dep['output']):
                    r = fire(dep, {'index-dropdown.value': []})
                    self.assertEqual(r.status_code, 200, r.data[:300])


class TestDeepDive(unittest.TestCase):
    OUT = 'dd-distribution-chart.figure'

    def run_dd(self, **kw):
        overrides = {f'dd-{k.replace("_", "-")}.value': v for k, v in kw.items() if k in ('fund_a', 'fund_b', 'window')}
        overrides.update({f'date-picker.{k}': v for k, v in kw.items() if k in ('start_date', 'end_date')})
        r = fire(callback_for(self.OUT), overrides)
        self.assertEqual(r.status_code, 200, r.data[:500])
        return json.loads(r.data)['response']

    def test_every_window_and_several_pairs(self):
        pairs = [('Nifty500 Multifactor MQVLv 50', 'Nifty 50'), ('Nifty500 Momentum 50', 'Nifty500 Low Volatility 50'),
                 ('Nifty Microcap 250', 'Nifty Smallcap 250'), ('Nifty200 Value 30', 'Nifty500 Quality 50')]
        for a, b in pairs:
            for w in dash_app.DEEP_DIVE_WINDOWS:
                with self.subTest(a=a, b=b, window=w):
                    resp = self.run_dd(fund_a=a, fund_b=b, window=w)
                    names = [t['name'] for t in resp['dd-distribution-chart']['figure']['data']]
                    self.assertTrue(any(a in n for n in names) and any(b in n for n in names))
                    self.assertIn('beat', resp['dd-excess-caption']['children'])

    def test_median_lines_match_stats(self):
        import analytics as an
        a, b = 'Nifty500 Multifactor MQVLv 50', 'Nifty 50'
        resp = self.run_dd(fund_a=a, fund_b=b, window=5)
        fig = resp['dd-distribution-chart']['figure']
        rw = an.rolling_windows(dash_app.df_daily[[a, b]], 5)
        lines = [t for t in fig['data'] if t.get('yaxis') == 'y2']
        dashed = {t['name']: arr(t['x'])[0] for t in lines if t['line']['dash'] == 'dash'}
        dotted = {t['name']: arr(t['x'])[0] for t in lines if t['line']['dash'] == 'dot'}
        for fund in (a, b):
            med, mean = rw['cagr'][fund].median() * 100, rw['cagr'][fund].mean() * 100
            self.assertAlmostEqual(dashed[f"{fund} median {med:.1f}%"], med, places=6)
            self.assertAlmostEqual(dotted[f"{fund} mean {mean:.1f}%"], mean, places=6)
        # no labels drawn over the plot: values live in the legend, which sits below the chart
        self.assertFalse(fig['layout'].get('annotations'))
        self.assertFalse(fig['layout'].get('shapes'))
        self.assertLess(fig['layout']['legend']['y'], 0)

    def test_excess_chart_has_median_and_mean(self):
        import analytics as an
        a, b = 'Nifty500 Multifactor MQVLv 50', 'Nifty 50'
        resp = self.run_dd(fund_a=a, fund_b=b, window=5)
        fig = resp['dd-excess-chart']['figure']
        c = an.rolling_windows(dash_app.df_daily[[a, b]], 5)['cagr']
        ex = (c[a] - c[b]) * 100
        lines = {t['line']['dash']: (t['name'], arr(t['x'])[0]) for t in fig['data'] if t.get('yaxis') == 'y2'}
        self.assertEqual(lines['dash'][0], f"Median {ex.median():+.1f} pp")
        self.assertAlmostEqual(lines['dash'][1], ex.median(), places=6)
        self.assertEqual(lines['dot'][0], f"Mean {ex.mean():+.1f} pp")
        self.assertAlmostEqual(lines['dot'][1], ex.mean(), places=6)
        self.assertFalse(fig['layout'].get('annotations'))

    def test_extremes_table_rows(self):
        resp = self.run_dd(window=3)
        rows = resp['dd-extremes-table']['children']['props']['children']['props']['data']
        self.assertEqual([r['Scenario'] for r in rows],
                         ['Lowest window of A', 'Lowest window of B', 'Median window of A', 'Median window of B',
                          'Highest window of A', 'Highest window of B'])
        self.assertLessEqual(rows[0]['A CAGR'], rows[4]['A CAGR'])

    def test_window_control_matches_other_rolling_tabs(self):
        dd = find_component(APP.layout, 'dd-window')
        ref = find_component(APP.layout, 'rolling-window-slider')
        self.assertEqual(type(dd).__name__, type(ref).__name__)  # both dcc.Slider
        self.assertEqual((dd.min, dd.max, dd.step), (ref.min, ref.max, ref.step))

    def test_tab_states_lumpsum_not_sip(self):
        body = CLIENT.get('/_dash-layout').data.decode()
        self.assertIn('lumpsum rolling returns (no SIP)', body)
        resp = self.run_dd(window=4)
        self.assertIn('Lumpsum (one-time investment)', json.dumps(resp['dd-warning']))

    def test_same_fund_warns(self):
        resp = self.run_dd(fund_a='Nifty 50', fund_b='Nifty 50')
        self.assertIn('same index', json.dumps(resp['dd-warning']))

    def test_short_range_warns(self):
        resp = self.run_dd(window=10, start_date='2019-01-01', end_date='2024-01-01')
        self.assertIn('too few', json.dumps(resp['dd-warning']))

    def test_path_chart_all_modes(self):
        dep = callback_for('dd-path-chart.figure')
        for mode in ['worst_a', 'best_a', 'worst_b', 'best_b']:
            with self.subTest(mode=mode):
                r = fire(dep, {'dd-path-selector.value': mode})
                self.assertEqual(r.status_code, 200)
                fig = json.loads(r.data)['response']['dd-path-chart']['figure']
                self.assertAlmostEqual(arr(fig['data'][0]['y'])[0], 100.0)


class TestExcessCorrelationTab(unittest.TestCase):
    OUT = 'excess-correlation-heatmap.figure'

    def run_ex(self, **overrides):
        r = fire(callback_for(self.OUT), overrides)
        self.assertEqual(r.status_code, 200, r.data[:500])
        return json.loads(r.data)['response']

    def test_defaults_render_everything(self):
        resp = self.run_ex()
        fig = resp['excess-correlation-heatmap']['figure']
        z = fig['data'][0]['z']
        z = np.array(arr(z) if isinstance(z, dict) else z, dtype=float)
        n = len(dash_app.index_list) - 1                      # 19 indices minus the benchmark
        self.assertEqual(z.size, n * n)
        self.assertEqual(fig['layout']['coloraxis']['cmin'], -1)
        self.assertEqual(fig['layout']['coloraxis']['cmax'], 1)
        self.assertIn('pairs', resp['excess-corr-caption']['children'])
        pairs = resp['excess-pairs-table']['children']['props']['children']['props']['data']
        self.assertEqual(len(pairs), 10)
        corrs = [p['Excess Correlation'] for p in pairs]
        self.assertEqual(corrs, sorted(corrs))                # lowest first
        self.assertNotIn('excess-average-table', resp)          # replaced by the per-fund table

    def test_benchmark_choice_changes_result(self):
        a = self.run_ex(**{'excess-benchmark.value': 'Nifty 50'})['excess-corr-caption']['children']
        b = self.run_ex(**{'excess-benchmark.value': 'Nifty 500'})['excess-corr-caption']['children']
        self.assertIn('minus Nifty 50', a)
        self.assertIn('minus Nifty 500', b)
        self.assertNotEqual(a, b)

    def test_follows_date_range_and_selection(self):
        resp = self.run_ex(**{'date-picker.start_date': '2020-01-01', 'date-picker.end_date': '2023-12-31'})
        self.assertIn('01 Jan 2020', resp['excess-corr-caption']['children'])
        resp = self.run_ex(**{'index-dropdown.value': ['Nifty 500', 'Nifty500 Momentum 50', 'Nifty500 Quality 50']})
        pairs = resp['excess-pairs-table']['children']['props']['children']['props']['data']
        self.assertEqual(len(pairs), 3)                       # 3 selected -> 3 pairs

    def test_too_few_indices_gives_message(self):
        for sel in ([], ['Nifty 50', 'Nifty 500'], ['Nifty 500']):  # benchmark (Nifty 50) is excluded from the count
            with self.subTest(selection=sel):
                resp = self.run_ex(**{'index-dropdown.value': sel})
                self.assertIn('at least two', resp['excess-corr-caption']['children'])


class TestFundCorrelationTable(unittest.TestCase):
    OUT = 'fund-corr-table.children'

    def run_fc(self, **overrides):
        r = fire(callback_for(self.OUT), overrides)
        self.assertEqual(r.status_code, 200, r.data[:500])
        return json.loads(r.data)['response']

    def table_props(self, resp):
        return resp['fund-corr-table']['children']['props']['children']['props']

    def test_default_table(self):
        resp = self.run_fc()
        props = self.table_props(resp)
        fund, bm = dash_app.DEFAULT_CORR_FUND, dash_app.DEFAULT_EXCESS_BENCHMARK
        names = [r['Index'] for r in props['data']]
        self.assertEqual(len(names), len(dash_app.index_list) - 2)       # all indices minus fund and benchmark
        self.assertNotIn(fund, names)
        self.assertNotIn(bm, names)
        self.assertEqual([c['id'] for c in props['columns']], ['Index', 'Excess Correlation', 'Raw Correlation'])
        self.assertEqual(props['sort_action'], 'native')
        self.assertEqual(props['sort_by'], [{'column_id': 'Excess Correlation', 'direction': 'asc'}])
        for col in ('Excess Correlation', 'Raw Correlation'):
            self.assertEqual([c['type'] for c in props['columns'] if c['id'] == col], ['numeric'])  # sorts numerically
            self.assertTrue(all(isinstance(r[col], float) for r in props['data']))
        self.assertIn('Best diversifier', resp['fund-corr-caption']['children'])

    def test_values_match_analytics(self):
        import analytics as an
        fund, bm = 'Nifty500 Momentum 50', 'Nifty 50'
        resp = self.run_fc(**{'corr-fund.value': fund, 'excess-benchmark.value': bm})
        got = {r['Index']: r for r in self.table_props(resp)['data']}
        want = an.fund_correlations(dash_app.df_daily, fund, bm, dash_app.index_list).set_index('Index')
        self.assertEqual(set(got), set(want.index))
        for name, row in want.iterrows():
            self.assertAlmostEqual(got[name]['Excess Correlation'], row['Excess Correlation'])
            self.assertAlmostEqual(got[name]['Raw Correlation'], row['Raw Correlation'])

    def test_follows_selection_and_date_range(self):
        resp = self.run_fc(**{'index-dropdown.value': ['Nifty 500', 'Nifty500 Quality 50', 'Nifty500 Value 50']})
        self.assertEqual(len(self.table_props(resp)['data']), 3)
        resp = self.run_fc(**{'date-picker.start_date': '2020-01-01', 'date-picker.end_date': '2023-12-31'})
        self.assertIn('Best diversifier', resp['fund-corr-caption']['children'])

    def test_fund_equal_to_benchmark_explains(self):
        resp = self.run_fc(**{'corr-fund.value': 'Nifty 50', 'excess-benchmark.value': 'Nifty 50'})
        self.assertIn('excess return is zero', resp['fund-corr-caption']['children'])
        self.assertIsNone(resp['fund-corr-table']['children'])

    def test_nothing_to_compare_explains(self):
        resp = self.run_fc(**{'index-dropdown.value': []})
        self.assertIn('Select at least one index', resp['fund-corr-caption']['children'])


class TestCorrelationPalette(unittest.TestCase):
    def colorscale(self, output_id):
        r = fire(callback_for(output_id), {})
        fig = json.loads(r.data)['response'][output_id.split('.')[0]]['figure']
        return [tuple(stop) for stop in fig['layout']['coloraxis']['colorscale']]

    def test_both_heatmaps_share_one_scale_with_red_as_high(self):
        raw = self.colorscale('correlation-heatmap.figure')
        excess = self.colorscale('excess-correlation-heatmap.figure')
        self.assertEqual(raw, excess)
        self.assertEqual([tuple(x) for x in dash_app.CORR_COLORSCALE], raw)
        self.assertEqual(raw[0][1].lower(), '#2a78d6')      # low  = blue
        self.assertEqual(raw[-1][1].lower(), '#e34948')     # high = red


class TestDeepDiveFixedAxes(unittest.TestCase):
    FIGS = ('dd-distribution-chart', 'dd-excess-chart')

    def run_dd(self, window, a='Nifty500 Multifactor MQVLv 50', b='Nifty 50', **dates):
        overrides = {'dd-fund-a.value': a, 'dd-fund-b.value': b, 'dd-window.value': window}
        overrides.update({f'date-picker.{k}': v for k, v in dates.items()})
        r = fire(callback_for('dd-distribution-chart.figure'), overrides)
        self.assertEqual(r.status_code, 200, r.data[:500])
        resp = json.loads(r.data)['response']
        return {name: resp[name]['figure'] for name in self.FIGS}

    @staticmethod
    def x_range(fig):
        return [round(v, 9) for v in fig['layout']['xaxis']['range']]

    @staticmethod
    def x_values(fig):
        out = []
        for t in fig['data']:
            if t.get('type') == 'histogram':
                out += arr(t['x']) if isinstance(t['x'], dict) else list(t['x'])
        return out

    def test_x_axes_do_not_move_when_the_window_changes(self):
        runs = {w: self.run_dd(w) for w in (1, 2, 5, 8, 10)}
        for name in self.FIGS:
            ranges = {w: self.x_range(f[name]) for w, f in runs.items()}
            with self.subTest(chart=name):
                self.assertEqual(len({tuple(r) for r in ranges.values()}), 1, ranges)

    def test_bin_width_is_also_fixed(self):
        runs = [self.run_dd(w) for w in (1, 5, 10)]
        for name in self.FIGS:
            sizes = {f[name]['data'][0]['xbins']['size'] for f in runs}
            with self.subTest(chart=name):
                self.assertEqual(len(sizes), 1)

    def test_range_contains_every_window(self):
        for w in (1, 3, 10):
            figs = self.run_dd(w)
            for name in self.FIGS:
                lo, hi = self.x_range(figs[name])
                xs = self.x_values(figs[name])
                with self.subTest(window=w, chart=name):
                    self.assertTrue(xs)
                    self.assertGreaterEqual(min(xs), lo)
                    self.assertLessEqual(max(xs), hi)

    def test_range_matches_analytics_bounds(self):
        import analytics as an
        a, b = 'Nifty500 Multifactor MQVLv 50', 'Nifty 50'
        bounds = an.rolling_return_bounds(dash_app.df_daily[[a, b]], dash_app.DEEP_DIVE_WINDOWS)
        figs = self.run_dd(5)
        lo, hi = self.x_range(figs['dd-distribution-chart'])
        span = (bounds['cagr'][1] - bounds['cagr'][0]) * 100
        self.assertAlmostEqual(lo, bounds['cagr'][0] * 100 - 0.03 * span, places=6)
        self.assertAlmostEqual(hi, bounds['cagr'][1] * 100 + 0.03 * span, places=6)

    def test_range_follows_the_funds_and_the_date_range(self):
        base = self.x_range(self.run_dd(5)['dd-distribution-chart'])
        other_pair = self.x_range(self.run_dd(5, a='Nifty Microcap 250', b='Nifty500 Low Volatility 50')['dd-distribution-chart'])
        short = self.x_range(self.run_dd(2, start_date='2018-01-01', end_date='2024-12-31')['dd-distribution-chart'])
        self.assertNotEqual(base, other_pair)
        self.assertNotEqual(base, short)

    def test_density_axis_is_not_forced(self):
        fig = self.run_dd(5)['dd-distribution-chart']
        self.assertFalse(fig['layout']['yaxis'].get('range'))     # density autoscales


class TestReadableHeatmaps(unittest.TestCase):
    def fig(self, output_id, **overrides):
        r = fire(callback_for(output_id), overrides)
        self.assertEqual(r.status_code, 200, r.data[:300])
        return json.loads(r.data)['response'][output_id.split('.')[0]]['figure']

    def test_order_is_clustered(self):
        import analytics as an
        fig = self.fig('correlation-heatmap.figure')
        order = list(fig['data'][0]['x'])
        corr = an.weekly_returns(dash_app.df_daily).corr()
        self.assertEqual(order, an.cluster_order(corr))
        self.assertEqual(sorted(order), sorted(dash_app.index_list))
        self.assertEqual(list(fig['data'][0]['y']), order)

    def test_values_hidden_when_crowded_and_shown_when_few(self):
        full = self.fig('excess-correlation-heatmap.figure')
        self.assertFalse(full['data'][0].get('texttemplate'))              # 40 indices: hover only
        self.assertIn('%{z:.2f}', full['data'][0]['hovertemplate'])
        few = ['Nifty 500', 'Nifty500 Momentum 50', 'Nifty500 Quality 50', 'Nifty500 Value 50', 'Nifty500 Low Volatility 50']
        small = self.fig('excess-correlation-heatmap.figure', **{'index-dropdown.value': few})
        self.assertEqual(small['data'][0]['texttemplate'], '%{text:.2f}')

    def test_cells_have_gaps_and_height_scales_with_count(self):
        full = self.fig('correlation-heatmap.figure')
        self.assertEqual(full['data'][0]['xgap'], 1)
        few = self.fig('correlation-heatmap.figure', **{'index-dropdown.value': dash_app.index_list[:5]})
        self.assertGreater(full['layout']['height'], few['layout']['height'])
        self.assertGreaterEqual(full['layout']['height'], 22 * len(dash_app.index_list))   # ~22px per row at 41 indices


class TestConfidenceIntervalColumns(unittest.TestCase):
    TABLES = {
        'lumpsum-metrics-table-container': ('Annualized Return', 'CAGR 95% CI Low', 'CAGR 95% CI High', None),
        'rolling-summary-table-container': ('Mean Annualized Return', 'Mean Return 95% CI Low', 'Mean Return 95% CI High', 'rolling-window-slider'),
        'sip-cumulative-table-container': ('Annualized Return', 'SIP XIRR 95% CI Low', 'SIP XIRR 95% CI High', None),
        'sip-rolling-summary-table-container': ('Mean Annualized Return', 'Mean SIP IRR 95% CI Low', 'Mean SIP IRR 95% CI High', 'sip-rolling-window-slider'),
    }

    def table(self, cid, **overrides):
        r = fire(callback_for(f'{cid}.children'), overrides)
        self.assertEqual(r.status_code, 200, r.data[:300])
        return json.loads(r.data)['response'][cid]['children']['props']['children']['props']

    def test_ci_columns_present_numeric_and_bracket_the_value(self):
        for cid, (point, low, high, _) in self.TABLES.items():
            props = self.table(cid)
            types = {c['id']: c.get('type') for c in props['columns']}
            with self.subTest(table=cid):
                self.assertEqual((types[low], types[high]), ('numeric', 'numeric'))
                self.assertIn(low, props['tooltip_header'])
                self.assertEqual(len(props['data']), len(dash_app.index_list))
                for row in props['data']:
                    self.assertLess(row[low], row[point], row['Index'])
                    self.assertGreater(row[high], row[point], row['Index'])

    def test_rolling_cis_follow_their_slider(self):
        for cid, (_, low, _, slider) in self.TABLES.items():
            if not slider:
                continue
            a = {r['Index']: r[low] for r in self.table(cid, **{f'{slider}.value': 3})['data']}
            b = {r['Index']: r[low] for r in self.table(cid, **{f'{slider}.value': 7})['data']}
            with self.subTest(table=cid):
                self.assertNotEqual(a, b)

    def test_each_table_has_its_own_interval(self):
        name = 'Nifty500 Multifactor MQVLv 50'
        lows = []
        for cid, (_, low, _, _) in self.TABLES.items():
            row = next(r for r in self.table(cid)['data'] if r['Index'] == name)
            lows.append(round(row[low], 6))
        self.assertEqual(len(set(lows)), 4, lows)

    def test_ci_follows_date_range(self):
        full = next(r for r in self.table('lumpsum-metrics-table-container')['data'] if r['Index'] == 'Nifty 50')
        short = next(r for r in self.table('lumpsum-metrics-table-container',
                                           **{'date-picker.start_date': '2018-01-01'})['data'] if r['Index'] == 'Nifty 50')
        self.assertGreater(short['CAGR 95% CI High'] - short['CAGR 95% CI Low'],
                           full['CAGR 95% CI High'] - full['CAGR 95% CI Low'])     # less history, wider interval


class TestRiskFreeRatePicker(unittest.TestCase):
    TABLES = {
        'lumpsum-metrics-table-container': ('Sharpe Ratio', 'Sortino Ratio', 'Risk-Adjusted Return (M²)'),
        'rolling-summary-table-container': ('Mean Sharpe Ratio', 'Mean Sortino Ratio', 'Mean Risk-Adjusted Return (M²)'),
        'sip-cumulative-table-container': ('Sharpe Ratio', 'Sortino Ratio', 'Risk-Adjusted Return (M²)'),
        'sip-rolling-summary-table-container': ('Mean Sharpe Ratio', 'Mean Sortino Ratio', 'Mean Risk-Adjusted Return (M²)'),
    }

    def rows(self, cid, rf):
        r = fire(callback_for(f'{cid}.children'), {'rf-rate.value': rf})
        self.assertEqual(r.status_code, 200, r.data[:300])
        props = json.loads(r.data)['response'][cid]['children']['props']['children']['props']
        return {row['Index']: row for row in props['data']}, props

    def test_picker_exists_with_default(self):
        picker = find_component(APP.layout, 'rf-rate')
        self.assertAlmostEqual(picker.value, 6.0)

    def test_every_table_responds_to_the_rate(self):
        for cid, (sharpe, sortino, m2) in self.TABLES.items():
            low, _ = self.rows(cid, 2)
            high, _ = self.rows(cid, 10)
            with self.subTest(table=cid):
                for name in ('Nifty 50', 'Nifty500 Multifactor MQVLv 50'):
                    self.assertGreater(low[name][sharpe], high[name][sharpe])
                    self.assertGreater(low[name][sortino], high[name][sortino])
                    self.assertNotEqual(low[name][m2], high[name][m2])

    def test_lumpsum_values_match_analytics(self):
        import analytics as an
        rows, props = self.rows('lumpsum-metrics-table-container', 7.5)
        m = an.run_metrics_analysis(dash_app.df_daily, 0.075, benchmark=dash_app.df_daily['Nifty 50'])
        for name in ('Nifty 50', 'Nifty Midcap150 Momentum 50'):
            self.assertAlmostEqual(rows[name]['Sharpe Ratio'], m.loc[name, 'Sharpe Ratio'])
            self.assertAlmostEqual(rows[name]['Sortino Ratio'], m.loc[name, 'Sortino Ratio'])
            self.assertAlmostEqual(rows[name]['Risk-Adjusted Return (M²)'], m.loc[name, 'Risk-Adjusted Return'] * 100)
        self.assertIn('7.50%', props['tooltip_header']['Sharpe Ratio']['value'])

    def test_blank_or_invalid_rate_falls_back_to_default(self):
        default, _ = self.rows('lumpsum-metrics-table-container', 6)
        for bad in (None, '', 'abc'):
            with self.subTest(value=bad):
                got, _ = self.rows('lumpsum-metrics-table-container', bad)
                self.assertAlmostEqual(got['Nifty 50']['Sharpe Ratio'], default['Nifty 50']['Sharpe Ratio'])

    def test_sip_tables_use_the_sip_period(self):
        lump, _ = self.rows('lumpsum-metrics-table-container', 6)
        sip, _ = self.rows('sip-cumulative-table-container', 6)
        # same index, different sampling (weekly vs daily) and span (first instalment onward): close but not identical
        a, b = lump['Nifty 50']['Sharpe Ratio'], sip['Nifty 50']['Sharpe Ratio']
        self.assertNotEqual(round(a, 6), round(b, 6))
        self.assertLess(abs(a - b), 0.2)

    def test_deep_dive_metrics_follow_the_rate(self):
        dep = callback_for('dd-metrics-table.children')
        tables = []
        for rf in (2, 10):
            r = fire(dep, {'rf-rate.value': rf})
            data = json.loads(r.data)['response']['dd-metrics-table']['children']['props']['children']['props']['data']
            tables.append({row['Metric']: row for row in data})
        self.assertIn('Risk-Adjusted Return', tables[0])
        self.assertNotEqual(tables[0]['Sharpe Ratio']['Fund A'], tables[1]['Sharpe Ratio']['Fund A'])


if __name__ == '__main__':
    unittest.main()
