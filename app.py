from functools import lru_cache

import numpy as np
import pandas as pd
import plotly.graph_objs as go
import dash
from dash import dcc, html, Input, Output, State, dash_table
from dash.dash_table.Format import Format, Scheme, Symbol, Group
import dash_bootstrap_components as dbc

import analytics as an
from analytics import RF_RATE

# -------------------------------------------------------------
# 1. DATA PREPARATION & MASTER LOAD
# -------------------------------------------------------------
df_daily = an.load_data()

index_list = sorted(list(df_daily.columns))
min_date = df_daily.index.min()
max_date = df_daily.index.max()

# Default selection of indices is ALL indices as requested by the user
DEFAULT_INDICES = index_list

# Years list for the dropdown selectors
year_list = sorted(list(set(df_daily.index.year)))

# Deep-dive colours: categorical slots 1 and 2 of the validated reference palette.
COLOR_A = "#2a78d6"
COLOR_B = "#eb6834"
DEFAULT_FUND_A = "Nifty500 Multifactor MQVLv 50"
DEFAULT_FUND_B = "Nifty 50"
DEFAULT_EXCESS_BENCHMARK = "Nifty 50"  # the dashboard-wide market benchmark
DEFAULT_CORR_FUND = "Nifty500 Multifactor MQVLv 50"
# One diverging scale for every correlation heatmap: blue = low / negative, grey = middle, red = high / positive
# (the blue and red poles of the validated reference palette with its neutral midpoint).
CORR_COLORSCALE = [[0.0, "#2a78d6"], [0.5, "#f0efec"], [1.0, "#e34948"]]
DEEP_DIVE_WINDOWS = list(range(1, 11))  # same 1-10 year range as the other rolling tabs

# -------------------------------------------------------------
# 2. SHARED UI HELPERS
# -------------------------------------------------------------
PCT = Format(precision=2, scheme=Scheme.fixed, symbol=Symbol.yes, symbol_suffix='%')
RATIO = Format(precision=2, scheme=Scheme.fixed)
INR = Format(precision=0, scheme=Scheme.fixed, group=Group.yes, symbol=Symbol.yes, symbol_prefix='₹')
INT = Format(precision=0, scheme=Scheme.fixed, group=Group.yes)


def make_table(records, columns, header_color='#2c3e50', sortable=True, font_size='13px', style_data_conditional=None, sort_by=None, column_widths=None, header_tooltips=None):
    """columns: list of (name, kind) where kind in {'text','pct','ratio','inr','int'}.
    Numeric columns stay numeric so native sorting is numeric, not alphabetical."""
    fmt = {'pct': PCT, 'ratio': RATIO, 'inr': INR, 'int': INT}
    cols = []
    for name, kind in columns:
        if kind == 'text':
            cols.append({'name': name, 'id': name, 'type': 'text'})
        else:
            cols.append({'name': name, 'id': name, 'type': 'numeric', 'format': fmt[kind]})
    return html.Div(
        dash_table.DataTable(
            data=records,
            columns=cols,
            sort_action="native" if sortable else "none",
            sort_by=sort_by or [],
            tooltip_header={k: {'value': v, 'type': 'markdown'} for k, v in (header_tooltips or {}).items()},
            tooltip_delay=0, tooltip_duration=None,
            css=[{'selector': '.dash-table-tooltip', 'rule': 'max-width: 360px; font-size: 12px;'}],
            # Fixed percentage widths let long names wrap inside a narrow card instead of forcing a horizontal scroll.
            style_cell_conditional=[{'if': {'column_id': name}, 'width': w, 'minWidth': w, 'maxWidth': w, 'whiteSpace': 'normal'}
                                    for name, w in (column_widths or {}).items()],
            style_header={'backgroundColor': header_color, 'color': 'white', 'fontWeight': 'bold', 'whiteSpace': 'normal'},
            style_cell={'textAlign': 'left', 'fontFamily': 'inherit', 'fontSize': font_size, 'padding': '10px'},
            style_table={'overflowX': 'auto'},
            style_data_conditional=[{'if': {'row_index': 'odd'}, 'backgroundColor': '#f8f9fa'}] + (style_data_conditional or [])
        ),
        className="table border rounded"
    )


def style_fig(fig, xaxis_title="Date", yaxis_title=None, hovermode="x unified", legend=True):
    fig.update_layout(
        xaxis_title=xaxis_title, yaxis_title=yaxis_title, hovermode=hovermode,
        margin=dict(l=20, r=20, t=10, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1) if legend else None,
        showlegend=legend,
        plot_bgcolor='white', paper_bgcolor='white'
    )
    fig.update_xaxes(showgrid=True, gridcolor='lightgray')
    fig.update_yaxes(showgrid=True, gridcolor='lightgray')
    return fig


def pct100(x):
    return None if x is None or pd.isna(x) else float(x) * 100


def empty_fig(message):
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(size=14, color="#6c757d"),
                       xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(plot_bgcolor='white', paper_bgcolor='white', margin=dict(l=20, r=20, t=10, b=20))
    return fig


HEATMAP_TEXT_MAX = 22   # print values inside cells only up to this many indices; beyond it they are hover-only


def corr_heatmap(corr, zmin, zmax, colorbar_title):
    """Readable correlation heatmap: clustered order, cells with thin gaps and a height that grows with the number of indices,
    full names in the hover,
    values printed in cells only while they fit."""
    order = an.cluster_order(corr)
    corr = corr.loc[order, order]
    n = len(order)
    show_text = n <= HEATMAP_TEXT_MAX
    fig = go.Figure(go.Heatmap(
        z=corr.to_numpy(), x=order, y=order, coloraxis="coloraxis", xgap=1, ygap=1,
        text=corr.round(2).to_numpy() if show_text else None,
        texttemplate="%{text:.2f}" if show_text else None,
        textfont=dict(size=11 if n <= 15 else 9),
        hovertemplate="%{y}<br>%{x}<br><b>%{z:.2f}</b><extra></extra>",
    ))
    cell = 30 if show_text else 22
    fig.update_layout(
        coloraxis=dict(colorscale=CORR_COLORSCALE, cmin=zmin, cmax=zmax,
                       colorbar=dict(title=dict(text=colorbar_title, side="right"), thickness=14)),
        margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor='white', paper_bgcolor='white',
        height=max(450, cell * n + 260),
    )
    tick_size = 11 if n <= 22 else 10
    fig.update_xaxes(tickangle=-50, tickfont=dict(size=tick_size), side="bottom", showgrid=False, automargin=True)
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=tick_size), showgrid=False, automargin=True)
    return fig


def card(title, body, extra_class="shadow mb-4"):
    return dbc.Card([dbc.CardHeader(title, className="font-weight-bold"), dbc.CardBody(body)], className=extra_class)


def fmt_date(d):
    return "Ongoing" if d is None or pd.isna(d) else pd.Timestamp(d).strftime('%d %b %Y')


# -------------------------------------------------------------
# 3. DASH APPLICATION INITIALIZATION
# -------------------------------------------------------------
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.FLATLY],
    title="Nifty Factor Analytics Dashboard"
)
server = app.server

# -------------------------------------------------------------
# 4. INTERACTIVE LAYOUT DESIGN
# -------------------------------------------------------------
deep_dive_tab = dbc.Tab(label="Deep Dive Compare", tab_id="tab-deep-dive", children=[
    dbc.Row([
        dbc.Col(card("Head-to-Head Deep Dive Controls", [
            dbc.Alert([
                html.Strong("What this tab measures: lumpsum rolling returns (no SIP). "),
                "Each observation is a one-time investment held for the selected number of years, and its return is the "
                "point-to-point CAGR of the Total Return Index (dividends reinvested). A new window starts on every trading day "
                "inside the global date range, so windows overlap. For monthly-SIP rolling returns use the ",
                html.Strong("SIP Rolling Period"), " tab."
            ], color="info", className="mb-3"),
            dbc.Row([
                dbc.Col([
                    html.Label("Fund A:", className="font-weight-bold text-secondary mb-2"),
                    dcc.Dropdown(id='dd-fund-a', options=index_list, value=DEFAULT_FUND_A, clearable=False)
                ], width=12, md=6),
                dbc.Col([
                    html.Label("Fund B (benchmark):", className="font-weight-bold text-secondary mb-2"),
                    dcc.Dropdown(id='dd-fund-b', options=index_list, value=DEFAULT_FUND_B, clearable=False)
                ], width=12, md=6),
            ], className="mb-3"),
            html.Label("Select Rolling Window Length (Years):", className="font-weight-bold text-secondary mb-2"),
            dcc.Slider(
                id='dd-window',
                min=1, max=10, step=1,
                value=5,
                marks={i: f"{i} Year" if i == 1 else f"{i} Years" for i in DEEP_DIVE_WINDOWS},
                className="mb-2"
            ),
            html.Div(id='dd-warning', className="mt-3")
        ], "shadow mb-4 mt-3"), width=12),

        dbc.Col(card("Lumpsum Rolling CAGR Distribution (Histogram + KDE; dashed lines = medians, dotted lines = means)", [
            html.Div(id='dd-dist-caption', className="text-muted mb-2"),
            dcc.Graph(id='dd-distribution-chart', config={'displayModeBar': False})
        ]), width=12),

        dbc.Col(card("Distribution of Excess Return (A − B, same window; dashed = median, dotted = mean)", [
            html.Div(id='dd-excess-caption', className="text-muted mb-2"),
            dcc.Graph(id='dd-excess-chart', config={'displayModeBar': False})
        ]), width=12, lg=6),

        dbc.Col(card("Distribution Statistics (Lumpsum Rolling CAGR)", [
            html.Div(id='dd-stats-table')
        ]), width=12, lg=6),

        dbc.Col(card("Lumpsum Rolling CAGR Over Time (markers = worst ▼ and best ▲ windows)", [
            dcc.Graph(id='dd-rolling-chart', config={'displayModeBar': False})
        ]), width=12),

        dbc.Col(card("Extreme Windows: Lowest, Median & Highest Lumpsum Rolling Returns", [
            html.P("Each row is one window picked by the named index's return. The other index's return over the exact same dates "
                   "shows whether the pain (or the gain) was shared.", className="text-muted mb-3"),
            html.Div(id='dd-extremes-table')
        ]), width=12),

        dbc.Col(card("Path Through an Extreme Window (both rebased to 100 at window start)", [
            dbc.RadioItems(
                id='dd-path-selector', value='worst_a', inline=True,
                options=[{'label': 'Worst window of A', 'value': 'worst_a'},
                         {'label': 'Best window of A', 'value': 'best_a'},
                         {'label': 'Worst window of B', 'value': 'worst_b'},
                         {'label': 'Best window of B', 'value': 'best_b'}],
                className="mb-2"
            ),
            dcc.Graph(id='dd-path-chart', config={'displayModeBar': False})
        ]), width=12, lg=6),

        dbc.Col(card("Calendar-Year Returns", [
            html.Div(id='dd-calendar-caption', className="text-muted mb-2"),
            dcc.Graph(id='dd-calendar-chart', config={'displayModeBar': False})
        ]), width=12, lg=6),

        dbc.Col(card("Full-Period Head-to-Head Metrics", [
            html.Small("Sharpe, Sortino and the risk-adjusted return (M², at Nifty 50's volatility) use the risk-free rate set at "
                       "the top, from weekly returns. The Return / Volatility ratios use 0%.",
                       className="text-muted d-block mb-2"),
            html.Div(id='dd-metrics-table')
        ]), width=12, lg=6),

        dbc.Col(card("Relationship: How A Behaves Relative to B", [
            html.Div(id='dd-relationship-table')
        ]), width=12, lg=6),

        dbc.Col(card("Drawdowns from Peak", [
            dcc.Graph(id='dd-drawdown-chart', config={'displayModeBar': False})
        ]), width=12, lg=6),

        dbc.Col(card("Five Deepest Drawdown Episodes per Index", [
            html.Div(id='dd-episodes-table')
        ]), width=12, lg=6),
    ])
])

app.layout = dbc.Container([
    # Navigation Header
    dbc.Row([
        dbc.Col(
            html.Div([
                html.H1("Indian Indices Quantitative Analytics Dashboard", className="text-white mb-1", style={"fontWeight": "bold"}),
                html.P(f"A {(max_date - min_date).days / 365.25:.1f}-Year Study of {len(index_list)} Broad-Based & Factor Indices "
                       f"({min_date:%d %b %Y} - {max_date:%d %b %Y}, Total Return Index)",
                       className="text-white-50 fs-5 mb-0")
            ], className="p-4 bg-dark rounded-3 shadow mb-4 mt-3"),
            width=12
        )
    ]),

    # Global Controls Panel (Dropdowns for Start/End Years & dcc.DatePickerRange)
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("Global Controls & Alignment Settings", className="font-weight-bold text-dark"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Select Indices for Analysis:", className="font-weight-bold text-secondary mb-2"),
                            dcc.Dropdown(
                                id='index-dropdown',
                                options=[{'label': x, 'value': x} for x in index_list],
                                value=DEFAULT_INDICES,
                                multi=True,
                                placeholder="Choose indices...",
                                className="mb-3"
                            )
                        ], width=12, lg=4),

                        dbc.Col([
                            html.Label("Date Picker Calendar Range:", className="font-weight-bold text-secondary mb-2"),
                            html.Div([
                                dcc.DatePickerRange(
                                    id='date-picker',
                                    min_date_allowed=min_date,
                                    max_date_allowed=max_date,
                                    start_date=min_date.date(),
                                    end_date=max_date.date(),
                                    display_format='DD MMM YYYY',
                                    className="w-100"
                                )
                            ], style={"zIndex": "1000"}),
                            html.Small("Applies to every tab. Tip: you can type directly inside the boxes.", className="text-muted d-block mt-1 italic")
                        ], width=12, sm=6, lg=4),

                        dbc.Col([
                            html.Label("Jump Calendar directly to Year:", className="font-weight-bold text-secondary mb-2"),
                            dbc.Row([
                                dbc.Col([
                                    dcc.Dropdown(
                                        id='start-year-dropdown',
                                        options=[{'label': f"Start: {y}", 'value': y} for y in year_list],
                                        placeholder="Start Year",
                                        clearable=True
                                    )
                                ], width=6),
                                dbc.Col([
                                    dcc.Dropdown(
                                        id='end-year-dropdown',
                                        options=[{'label': f"End: {y}", 'value': y} for y in year_list],
                                        placeholder="End Year",
                                        clearable=True
                                    )
                                ], width=6)
                            ]),
                            html.Small("Selecting a year instantly syncs and jumps the calendar to that year!", className="text-muted d-block mt-1 italic")
                        ], width=12, sm=6, lg=4)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Label("Risk-Free Rate (% p.a.):", className="font-weight-bold text-secondary mb-2"),
                            dbc.Input(id='rf-rate', type="number", value=RF_RATE * 100, min=0, max=30, step=0.25,
                                      debounce=True, style={"maxWidth": "140px"}),
                        ], width="auto"),
                        dbc.Col(html.Small(
                            "Used for the Sharpe ratio, Sortino ratio and risk-adjusted return (M²) in every table and in "
                            "Deep Dive Compare. Indian 1-year T-bill / FD rates have mostly been 4–8%.",
                            className="text-muted d-block"), className="d-flex align-items-end pb-1"),
                    ], className="mt-2 g-3")
                ])
            ], className="shadow mb-4")
        ], width=12)
    ]),

    # Navigation Windows (Tabs)
    dbc.Tabs(id="main-tabs", active_tab="tab-growth", children=[
        # Tab 1: Cumulative Growth (Lumpsum)
        dbc.Tab(label="Cumulative Growth", tab_id="tab-growth", children=[
            dbc.Row([
                dbc.Col(card("Lumpsum Performance & Risk Metrics (Click Headers to Sort)", [
                    html.Small("Volatility, downside volatility, Sharpe, Sortino and risk-adjusted return (M², vs Nifty 50 volatility) "
                               "use weekly returns. Hover any column header for its exact formula.",
                               className="text-muted d-block mb-1"),
                    html.Small("95% CI columns: the range for the long-run value of this table’s return statistic, from block-bootstrap "
                               "resamples of the selected period (hover a CI column header for details). It is not the range of "
                               "returns you could get in a single year or window.", className="text-muted d-block mb-1"),
                    html.Div(id='lumpsum-caption', className="text-muted small mb-2"),
                    html.Div(id='lumpsum-metrics-table-container')
                ], "shadow mb-4 mt-3"), width=12)
            ])
        ]),

        # Tab 2: Rolling Period Returns (Lumpsum)
        dbc.Tab(label="Rolling Period Returns", tab_id="tab-rolling", children=[
            dbc.Row([
                dbc.Col(card("Rolling Return Controls", [
                    html.Label("Select Rolling Window Length (Years):", className="font-weight-bold text-secondary mb-2"),
                    dcc.Slider(
                        id='rolling-window-slider',
                        min=1, max=10, step=1,
                        value=5,
                        marks={i: f"{i} Year" if i == 1 else f"{i} Years" for i in range(1, 11)},
                        className="mb-4"
                    )
                ], "shadow mb-4 mt-3"), width=12),

                dbc.Col(card("Rolling Risk-Return Summary Statistics (Click Headers to Sort)", [
                    html.Small("Volatilities, Sharpe, Sortino and risk-adjusted return are computed from daily returns inside each "
                               "window, then averaged over all windows. Hover any column header for its exact formula.",
                               className="text-muted d-block mb-1"),
                    html.Small("95% CI columns: the range for the long-run value of this table’s return statistic, from block-bootstrap "
                               "resamples of the selected period (hover a CI column header for details). It is not the range of "
                               "returns you could get in a single year or window.", className="text-muted d-block mb-1"),
                    html.Div(id='rolling-caption', className="text-muted small mb-2"),
                    html.Div(id='rolling-summary-table-container')
                ]), width=12)
            ])
        ]),

        # Tab 3: SIP Cumulative
        dbc.Tab(label="SIP Cumulative", tab_id="tab-sip", children=[
            dbc.Row([
                dbc.Col(card("SIP Cumulative Performance & Risk Metrics (Click Headers to Sort)", [
                    html.Small("Annualized Return is the SIP XIRR. Volatilities use the SIP's flow-neutral daily returns. "
                               "Maximum Drawdown is flow-adjusted: measured against the previous peak value plus every instalment "
                               "added since, so new money cannot mask a fall.", className="text-muted d-block mb-1"),
                    html.Small("95% CI columns: the range for the long-run value of this table’s return statistic, from block-bootstrap "
                               "resamples of the selected period (hover a CI column header for details). It is not the range of "
                               "returns you could get in a single year or window.", className="text-muted d-block mb-1"),
                    html.Div(id='sip-caption', className="text-muted small mb-2"),
                    html.Div(id='sip-cumulative-table-container')
                ], "shadow mb-4 mt-3"), width=12)
            ])
        ]),

        # Tab 4: SIP Rolling Period
        dbc.Tab(label="SIP Rolling Period", tab_id="tab-sip-rolling", children=[
            dbc.Row([
                dbc.Col(card("SIP Rolling Period Controls", [
                    html.Label("Select SIP Holding Period Window (Years):", className="font-weight-bold text-secondary mb-2"),
                    dcc.Slider(
                        id='sip-rolling-window-slider',
                        min=1, max=10, step=1,
                        value=5,
                        marks={i: f"{i} Yr SIP" if i == 1 else f"{i} Yrs SIP" for i in range(1, 11)},
                        className="mb-4"
                    )
                ], "shadow mb-4 mt-3"), width=12),

                dbc.Col(card("SIP Rolling Performance Stats (Click Headers to Sort)", [
                    html.Small("A single-index SIP's flow-neutral return equals the index's daily return, so SIP volatility is the "
                               "index volatility over each SIP window.", className="text-muted d-block mb-1"),
                    html.Small("95% CI columns: the range for the long-run value of this table’s return statistic, from block-bootstrap "
                               "resamples of the selected period (hover a CI column header for details). It is not the range of "
                               "returns you could get in a single year or window.", className="text-muted d-block mb-1"),
                    html.Div(id='sip-rolling-caption', className="text-muted small mb-2"),
                    html.Div(id='sip-rolling-summary-table-container')
                ]), width=12)
            ])
        ]),

        # Tab 5: Deep Dive Compare (two indices)
        deep_dive_tab,

        # Tab 6: Correlation Analysis
        dbc.Tab(label="Correlation Analysis", tab_id="tab-corr", children=[
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Weekly Returns Pearson Correlation Heatmap", className="font-weight-bold"),
                        dbc.CardBody([
                            html.P("Shows correlation of weekly Friday-to-Friday returns over the chosen period. "
                                   "Almost everything is highly correlated here because all indices share the same market move; "
                                   "the excess-return view below removes that shared part. Colours run from 0.4 (blue) to 1.0 (red), the same palette as the excess view. "
                                   "Indices are ordered so similar ones sit next to each other; hover any cell for the pair and its value.",
                                   className="text-muted mb-3"),
                            dcc.Graph(id='correlation-heatmap', config={'displayModeBar': False})
                        ])
                    ], className="shadow mb-4 mt-3")
                ], width=12),

                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Excess-Return Correlation (diversification beyond the market)", className="font-weight-bold"),
                        dbc.CardBody([
                            dbc.Alert([
                                html.Strong("How to read this: "),
                                "each index's weekly return has the benchmark's weekly return subtracted first (its ",
                                html.Strong("excess return"), "), then those excess returns are correlated. "
                                "A value near ", html.Strong("+1"), " (red) means the two indices make the same bets relative to the benchmark (little diversification). "
                                "Near ", html.Strong("0"), " (grey) they are unrelated; ", html.Strong("negative"),
                                " (blue) means one tends to win when the other loses against the benchmark, which is the most diversifying pairing. "
                                "The benchmark itself is left out (its excess return is zero). ",
                                html.Strong("Choose the benchmark deliberately: "),
                                "if it makes up most of another index (Nifty 50 inside Nifty 500, say), that index's excess return is mostly "
                                "the opposite of the size tilt, so strongly negative pairs then reflect market-cap size rather than factor diversification."
                            ], color="info", className="mb-3"),
                            dbc.Row([
                                dbc.Col([
                                    html.Label("Benchmark to subtract:", className="font-weight-bold text-secondary mb-2"),
                                    dcc.Dropdown(id='excess-benchmark', options=index_list, value=DEFAULT_EXCESS_BENCHMARK, clearable=False)
                                ], width=12, md=6),
                            ], className="mb-3"),
                            html.Div(id='excess-corr-caption', className="text-muted mb-2"),
                            dcc.Graph(id='excess-correlation-heatmap', config={'displayModeBar': False})
                        ])
                    ], className="shadow mb-4")
                ], width=12, xl=8),

                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("One Fund vs All Others", className="font-weight-bold"),
                        dbc.CardBody([
                            html.P("Pick a fund to see its correlation with every other selected index, both after removing the benchmark "
                                   "(Excess) and before (Raw). Click a column header to sort ascending or descending; it starts with the "
                                   "lowest excess correlation first, i.e. the best diversifiers.", className="text-muted mb-3"),
                            html.Label("Fund:", className="font-weight-bold text-secondary mb-2"),
                            dcc.Dropdown(id='corr-fund', options=index_list, value=DEFAULT_CORR_FUND, clearable=False, className="mb-3"),
                            html.Div(id='fund-corr-caption', className="text-muted mb-2"),
                            html.Div(id='fund-corr-table')
                        ])
                    ], className="shadow mb-4")
                ], width=12, xl=4),

                dbc.Col(card("Most Diversifying Pairs (lowest excess-return correlation)", [
                    html.Div(id='excess-pairs-table')
                ]), width=12),
            ])
        ])
    ])
], fluid=True)

# -------------------------------------------------------------
# 5. DASHBOARD CALLBACKS (LOGIC & INTERACTIVITY)
# -------------------------------------------------------------

def to_day(value):
    """DatePickerRange sends ISO strings; accept anything pandas can parse and drop any timezone."""
    if value is None:
        return None
    ts = pd.Timestamp(value)
    return (ts.tz_convert(None) if ts.tzinfo else ts).normalize()


def filter_dates(start_date, end_date, columns=None):
    df = df_daily.loc[to_day(start_date):to_day(end_date)]
    return df if columns is None else df[columns]


# Callback to sync Year dropdown selectors directly to the dcc.DatePickerRange calendar
@app.callback(
    [Output('date-picker', 'start_date'),
     Output('date-picker', 'end_date')],
    [Input('start-year-dropdown', 'value'),
     Input('end-year-dropdown', 'value')],
    [State('date-picker', 'start_date'),
     State('date-picker', 'end_date')],
    prevent_initial_call=True
)
def sync_year_dropdowns_to_datepicker(start_year, end_year, current_start, current_end):
    trigger_id = dash.callback_context.triggered_id

    start_str = current_start
    end_str = current_end

    if trigger_id == 'start-year-dropdown' and start_year is not None:
        try:
            curr_start_dt = pd.to_datetime(current_start)
            # Preserve month and day if possible, only swap the year component
            new_start_dt = pd.Timestamp(year=int(start_year), month=curr_start_dt.month, day=curr_start_dt.day)
        except Exception:
            new_start_dt = pd.Timestamp(year=int(start_year), month=1, day=1)
        start_str = min(max(new_start_dt, min_date), max_date).strftime('%Y-%m-%d')

    if trigger_id == 'end-year-dropdown' and end_year is not None:
        try:
            curr_end_dt = pd.to_datetime(current_end)
            new_end_dt = pd.Timestamp(year=int(end_year), month=curr_end_dt.month, day=curr_end_dt.day)
        except Exception:
            new_end_dt = pd.Timestamp(year=int(end_year), month=12, day=31)
        end_str = min(max(new_end_dt, min_date), max_date).strftime('%Y-%m-%d')

    return start_str, end_str


# ---- 95% confidence intervals (one per table, each for that table's own statistic) ----
CI_NOTE = ("95% CI = range for the *long-run* value of this statistic, from 6-month block bootstrap resamples of "
           "the selected period. It is **not** the range of returns you could get in any single year or window.")


@lru_cache(maxsize=64)
def cached_ci(kind, columns, start_date, end_date, years=None):
    """kind: 'cagr' | 'rolling' | 'sip' | 'rolling_sip'. Cached so revisiting a tab or table is instant."""
    prices = filter_dates(start_date, end_date, list(columns))
    if kind == 'cagr':
        return an.ci_cagr(prices)
    if kind == 'rolling':
        return an.ci_rolling_cagr_mean(prices, years)
    if kind == 'sip':
        return an.ci_sip_irr(prices, an.monthly_sip_dates(prices.index))
    return an.ci_rolling_sip_mean(prices, years)


def period_caption(start, end, extra=""):
    return f"{extra}Period: {pd.Timestamp(start):%d %b %Y} to {pd.Timestamp(end):%d %b %Y}."


# ---- risk-adjusted columns shared by the four tables ----
M2_BENCHMARK = "Nifty 50"


def rf_from(value):
    """Risk-free rate from the picker (% p.a.) as a fraction; blank or invalid -> the default."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return RF_RATE
    return min(max(v, 0.0), 30.0) / 100


def risk_tooltips(rf, period_note):
    return {
        "Sharpe": (f"Sharpe ratio = mean excess return / standard deviation, annualised. Excess return = return minus "
                   f"the risk-free rate ({rf*100:.2f}% p.a., set at the top). {period_note}"),
        "Sortino": (f"Sortino ratio = mean excess return / downside deviation below the risk-free rate "
                    f"({rf*100:.2f}% p.a.), annualised. Only shortfalls below the risk-free rate count as risk. {period_note}"),
        "Risk-Adj": (f"Risk-adjusted return (M², Modigliani-Modigliani) = risk-free rate + Sharpe x {M2_BENCHMARK} volatility: "
                     f"the return this index would have delivered at {M2_BENCHMARK}'s level of risk. It is on an average-return "
                     f"(arithmetic) basis, so compare it across indices rather than with the CAGR/XIRR column. {period_note}"),
    }


def tooltips_for(columns, tips):
    """Map each column name containing 'Sharpe' / 'Sortino' / 'Risk-Adjusted' to its explanation."""
    out = {}
    for c in columns:
        if "Sharpe" in c:
            out[c] = tips["Sharpe"]
        elif "Sortino" in c:
            out[c] = tips["Sortino"]
        elif "Risk-Adjusted" in c:
            out[c] = tips["Risk-Adj"]
    return out


def nan_to_none(x):
    return None if x is None or pd.isna(x) else float(x)


# Callback for TAB 1: Lumpsum metrics table
@app.callback(
    [Output('lumpsum-caption', 'children'),
     Output('lumpsum-metrics-table-container', 'children')],
    [Input('index-dropdown', 'value'),
     Input('date-picker', 'start_date'),
     Input('date-picker', 'end_date'),
     Input('rf-rate', 'value')]
)
def update_tab1(selected_indices, start_date, end_date, rf_value):
    if not selected_indices:
        return None, html.Div("Please select at least one index to display performance.", className="text-warning")

    df_filtered = filter_dates(start_date, end_date, selected_indices)
    if len(df_filtered) < 2:
        return None, html.Div("No data available for the selected dates.", className="text-danger")

    rf = rf_from(rf_value)
    bench = filter_dates(start_date, end_date)[M2_BENCHMARK]
    m = an.run_metrics_analysis(df_filtered, rf, benchmark=bench)
    ci = cached_ci('cagr', tuple(selected_indices), str(start_date), str(end_date))
    records = [{
        "Index": idx,
        "Annualized Return": pct100(r["CAGR"]),
        "CAGR 95% CI Low": float(ci.loc[idx, 'low']) * 100,
        "CAGR 95% CI High": float(ci.loc[idx, 'high']) * 100,
        "Annualized Volatility": pct100(r["Volatility"]),
        "Downside Volatility": pct100(r["Downside Volatility"]),
        "Sharpe Ratio": nan_to_none(r["Sharpe Ratio"]),
        "Sortino Ratio": nan_to_none(r["Sortino Ratio"]),
        "Risk-Adjusted Return (M²)": pct100(r["Risk-Adjusted Return"]),
        "Maximum Drawdown": pct100(r["Max Drawdown"]),
    } for idx, r in m.iterrows()]
    cols = [("Index", "text"), ("Annualized Return", "pct"), ("CAGR 95% CI Low", "pct"), ("CAGR 95% CI High", "pct"),
            ("Annualized Volatility", "pct"), ("Downside Volatility", "pct"), ("Sharpe Ratio", "ratio"),
            ("Sortino Ratio", "ratio"), ("Risk-Adjusted Return (M²)", "pct"), ("Maximum Drawdown", "pct")]
    tips = tooltips_for([c for c, _ in cols], risk_tooltips(rf, "Uses weekly returns over the selected period."))
    tips.update({c: "Lumpsum CAGR over the selected period. " + CI_NOTE for c in ("CAGR 95% CI Low", "CAGR 95% CI High")})
    table = make_table(records, cols, header_tooltips=tips)
    caption = period_caption(df_filtered.index[0], df_filtered.index[-1],
                             f"{len(records)} indices, one-time investment at the start. Risk-free rate {rf*100:.2f}% p.a. ")
    return caption, table


# Callback for TAB 2: Rolling lumpsum returns table
@app.callback(
    [Output('rolling-caption', 'children'),
     Output('rolling-summary-table-container', 'children')],
    [Input('index-dropdown', 'value'),
     Input('rolling-window-slider', 'value'),
     Input('date-picker', 'start_date'),
     Input('date-picker', 'end_date'),
     Input('rf-rate', 'value')]
)
def update_tab2(selected_indices, rolling_years, start_date, end_date, rf_value):
    if not selected_indices:
        return None, html.Div("Select indices to view rolling stats.", className="text-warning")

    prices = filter_dates(start_date, end_date, selected_indices)
    rw = an.rolling_windows(prices, rolling_years)
    if rw["cagr"].empty:
        msg = f"The selected date range is shorter than {rolling_years} year(s); widen the range or shorten the window."
        return None, html.Div(msg, className="text-danger")

    rf = rf_from(rf_value)
    ra = an.rolling_risk_adjusted(prices, filter_dates(start_date, end_date)[M2_BENCHMARK], rolling_years, rf)
    ci = cached_ci('rolling', tuple(selected_indices), str(start_date), str(end_date), rolling_years)
    records = []
    for col in selected_indices:
        cagr, vol, dvol = rw["cagr"][col], rw["vol"][col], rw["dvol"][col]
        records.append({
            "Index": col,
            "Mean Annualized Return": cagr.mean() * 100,
            "Mean Return 95% CI Low": float(ci.loc[col, 'low']) * 100,
            "Mean Return 95% CI High": float(ci.loc[col, 'high']) * 100,
            "Mean Annualized Volatility": vol.mean() * 100,
            "Mean Downside Volatility": dvol.mean() * 100,
            "Mean Sharpe Ratio": nan_to_none(ra["sharpe"][col].mean()),
            "Mean Sortino Ratio": nan_to_none(ra["sortino"][col].mean()),
            "Mean Risk-Adjusted Return (M²)": nan_to_none(ra["m2"][col].mean() * 100),
            "Worst-Case CAGR": cagr.min() * 100,
            "Best-Case CAGR": cagr.max() * 100,
        })
    cols = [("Index", "text"), ("Mean Annualized Return", "pct"), ("Mean Return 95% CI Low", "pct"),
            ("Mean Return 95% CI High", "pct"), ("Mean Annualized Volatility", "pct"), ("Mean Downside Volatility", "pct"),
            ("Mean Sharpe Ratio", "ratio"), ("Mean Sortino Ratio", "ratio"), ("Mean Risk-Adjusted Return (M²)", "pct"),
            ("Worst-Case CAGR", "pct"), ("Best-Case CAGR", "pct")]
    tips = tooltips_for([c for c, _ in cols], risk_tooltips(
        rf, f"Computed from daily returns inside each {rolling_years}-year window, then averaged over all windows."))
    tips.update({c: f"Mean of all rolling {rolling_years}-year lumpsum CAGRs. " + CI_NOTE
                 for c in ("Mean Return 95% CI Low", "Mean Return 95% CI High")})
    table = make_table(records, cols, font_size='12px', header_tooltips=tips)
    caption = (f"{len(rw['cagr']):,} overlapping {rolling_years}-year windows ending "
               f"{rw['cagr'].index[0]:%d %b %Y} to {rw['cagr'].index[-1]:%d %b %Y}. Risk-free rate {rf*100:.2f}% p.a.")
    return caption, table


# Callback for TAB 3: SIP cumulative table
@app.callback(
    [Output('sip-caption', 'children'),
     Output('sip-cumulative-table-container', 'children')],
    [Input('index-dropdown', 'value'),
     Input('date-picker', 'start_date'),
     Input('date-picker', 'end_date'),
     Input('rf-rate', 'value')]
)
def update_tab3(selected_indices, start_date, end_date, rf_value):
    if not selected_indices:
        return None, html.Div("Select indices to view SIP stats.", className="text-warning")

    df_filtered = filter_dates(start_date, end_date, selected_indices)
    if df_filtered.empty:
        return None, html.Div("No data available for dates selected.", className="text-danger")

    sip_dates = an.monthly_sip_dates(df_filtered.index)
    if len(sip_dates) < 2:
        return None, html.Div("Selected range is too short for a monthly SIP.", className="text-danger")

    rf = rf_from(rf_value)
    end_date_val = df_filtered.index[-1]
    sip_amt = 10000.0
    bench = filter_dates(start_date, end_date)[M2_BENCHMARK]
    ci = cached_ci('sip', tuple(selected_indices), str(start_date), str(end_date))
    records, twr_all = [], {}
    sims = {}
    for col in selected_indices:
        sim = an.simulate_sip(df_filtered[col], sip_dates, sip_amt)
        sims[col] = sim
        twr_all[col] = sim["twr_return"]
    twr_df = pd.DataFrame(twr_all).dropna()
    bench_twr = bench.pct_change().reindex(twr_df.index)        # benchmark over the same SIP days
    ra = an.risk_adjusted(twr_df, rf, an.TRADING_DAYS, bench_twr)
    for col in selected_indices:
        sim = sims[col]
        final_val = sim["value"].iloc[-1]
        cash_flows = [-sip_amt] * len(sip_dates) + [final_val]
        sip_irr = an.calculate_xirr(cash_flows, list(sip_dates) + [end_date_val])
        twr = twr_df[col]
        records.append({
            "Index": col,
            "Annualized Return": sip_irr * 100,
            "SIP XIRR 95% CI Low": float(ci.loc[col, 'low']) * 100,
            "SIP XIRR 95% CI High": float(ci.loc[col, 'high']) * 100,
            "Annualized Volatility": twr.std() * np.sqrt(an.TRADING_DAYS) * 100,
            "Downside Volatility": an.downside_deviation(twr, an.TRADING_DAYS) * 100,
            "Sharpe Ratio": nan_to_none(ra.loc[col, "Sharpe Ratio"]),
            "Sortino Ratio": nan_to_none(ra.loc[col, "Sortino Ratio"]),
            "Risk-Adjusted Return (M²)": nan_to_none(ra.loc[col, "Risk-Adjusted Return"] * 100),
            "Maximum Drawdown": sim["drawdown"].min() * 100,
            "Total Invested": sim["invested"].iloc[-1],
            "Final Value": final_val,
        })

    cols = [("Index", "text"), ("Annualized Return", "pct"), ("SIP XIRR 95% CI Low", "pct"), ("SIP XIRR 95% CI High", "pct"),
            ("Annualized Volatility", "pct"), ("Downside Volatility", "pct"), ("Sharpe Ratio", "ratio"),
            ("Sortino Ratio", "ratio"), ("Risk-Adjusted Return (M²)", "pct"), ("Maximum Drawdown", "pct"),
            ("Total Invested", "inr"), ("Final Value", "inr")]
    tips = tooltips_for([c for c, _ in cols], risk_tooltips(
        rf, "Uses the SIP portfolio's flow-neutral daily returns from the first instalment, which for a single index "
            "equal the index's own daily returns."))
    tips.update({c: "Monthly-SIP XIRR over the selected period. " + CI_NOTE for c in ("SIP XIRR 95% CI Low", "SIP XIRR 95% CI High")})
    table = make_table(records, cols, header_color='#2980b9', header_tooltips=tips)
    caption = period_caption(sip_dates[0], end_date_val,
                             f"₹{sip_amt:,.0f} on the first trading day of each month, {len(sip_dates)} instalments. "
                             f"Risk-free rate {rf*100:.2f}% p.a. ")
    return caption, table


# Callback for TAB 4: SIP rolling table
@app.callback(
    [Output('sip-rolling-caption', 'children'),
     Output('sip-rolling-summary-table-container', 'children')],
    [Input('index-dropdown', 'value'),
     Input('sip-rolling-window-slider', 'value'),
     Input('date-picker', 'start_date'),
     Input('date-picker', 'end_date'),
     Input('rf-rate', 'value')]
)
def update_tab4(selected_indices, rolling_years, start_date, end_date, rf_value):
    if not selected_indices:
        return None, html.Div("Select indices to view rolling SIP stats.", className="text-warning")

    prices = filter_dates(start_date, end_date, selected_indices)
    rs = an.rolling_sip(prices, rolling_years)
    if rs is None:
        msg = f"The selected date range is too short for a {rolling_years}-year rolling SIP."
        return None, html.Div(msg, className="text-danger")

    rf = rf_from(rf_value)
    ra = an.rolling_sip_risk_adjusted(prices, filter_dates(start_date, end_date)[M2_BENCHMARK], rolling_years, rf)
    ci = cached_ci('rolling_sip', tuple(selected_indices), str(start_date), str(end_date), rolling_years)
    records = []
    for col in selected_indices:
        irr, vol, dvol = rs["irr"][col], rs["vol"][col], rs["dvol"][col]
        records.append({
            "Index": col,
            "Mean Annualized Return": irr.mean() * 100,
            "Mean SIP IRR 95% CI Low": float(ci.loc[col, 'low']) * 100,
            "Mean SIP IRR 95% CI High": float(ci.loc[col, 'high']) * 100,
            "Mean Annualized Volatility": vol.mean() * 100,
            "Mean Downside Volatility": dvol.mean() * 100,
            "Mean Sharpe Ratio": nan_to_none(ra["sharpe"][col].mean()),
            "Mean Sortino Ratio": nan_to_none(ra["sortino"][col].mean()),
            "Mean Risk-Adjusted Return (M²)": nan_to_none(ra["m2"][col].mean() * 100),
            "Worst-Case SIP IRR": irr.min() * 100,
            "Best-Case SIP IRR": irr.max() * 100,
        })
    cols = [("Index", "text"), ("Mean Annualized Return", "pct"), ("Mean SIP IRR 95% CI Low", "pct"),
            ("Mean SIP IRR 95% CI High", "pct"), ("Mean Annualized Volatility", "pct"), ("Mean Downside Volatility", "pct"),
            ("Mean Sharpe Ratio", "ratio"), ("Mean Sortino Ratio", "ratio"), ("Mean Risk-Adjusted Return (M²)", "pct"),
            ("Worst-Case SIP IRR", "pct"), ("Best-Case SIP IRR", "pct")]
    tips = tooltips_for([c for c, _ in cols], risk_tooltips(
        rf, f"Computed from the SIP's flow-neutral daily returns in each {rolling_years}-year SIP window "
            "(first instalment to valuation), then averaged over all windows."))
    tips.update({c: f"Mean of all rolling {rolling_years}-year monthly-SIP IRRs. " + CI_NOTE
                 for c in ("Mean SIP IRR 95% CI Low", "Mean SIP IRR 95% CI High")})
    table = make_table(records, cols, header_color='#16a085', font_size='12px', header_tooltips=tips)
    caption = (f"{len(rs['irr']):,} rolling {rolling_years}-year monthly SIPs, valued "
               f"{rs['irr'].index[0]:%d %b %Y} to {rs['irr'].index[-1]:%d %b %Y}. Risk-free rate {rf*100:.2f}% p.a.")
    return caption, table


# -------------------------------------------------------------
# TAB 5: Deep Dive Compare
# -------------------------------------------------------------
DD_OUTPUTS = [
    'dd-warning', 'dd-dist-caption', 'dd-distribution-chart', 'dd-excess-caption', 'dd-excess-chart',
    'dd-stats-table', 'dd-rolling-chart', 'dd-extremes-table', 'dd-calendar-caption', 'dd-calendar-chart',
    'dd-metrics-table', 'dd-relationship-table', 'dd-drawdown-chart', 'dd-episodes-table'
]
DD_FIGURES = {'dd-distribution-chart', 'dd-excess-chart', 'dd-rolling-chart', 'dd-calendar-chart', 'dd-drawdown-chart'}


def deep_dive_blank(message, level="text-warning"):
    out = []
    for oid in DD_OUTPUTS:
        if oid == 'dd-warning':
            out.append(html.Div(message, className=level))
        elif oid in DD_FIGURES:
            out.append(empty_fig(message))
        else:
            out.append(None)
    return out


def fixed_range(bounds, pad=0.03):
    """Axis range (in %) for a (lo, hi) pair of fractions, with a little breathing room."""
    lo, hi = bounds[0] * 100, bounds[1] * 100
    return [lo - pad * (hi - lo), hi + pad * (hi - lo)]


def bin_width(bounds):
    """Histogram bin width (in %): the fixed range split into 100 bins, so bars keep the same width whichever window is shown."""
    span_pct = (bounds[1] - bounds[0]) * 100
    return max(span_pct / 100, 0.05)


def add_stat_line(fig, x, color, dash, label, legendgroup=None):
    """Full-height vertical line drawn as a trace on a hidden 0-1 overlay axis, so its value lives in the
    legend (and the hover) instead of a label sitting on top of the bars. Clicking the legend entry hides it."""
    fig.add_trace(go.Scatter(
        x=[x, x], y=[0, 1], yaxis="y2", mode="lines", name=label, legendgroup=legendgroup,
        line=dict(color=color, width=2, dash=dash), hovertemplate=label + "<extra></extra>",
    ))


def legend_below(fig):
    """Legend under the x-axis title, items toggled one at a time, and the hidden axis for stat lines."""
    fig.update_layout(
        yaxis2=dict(overlaying="y", range=[0, 1], visible=False, fixedrange=True),
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0, groupclick="toggleitem"),
        margin=dict(l=20, r=20, t=10, b=20),
    )


def distribution_figure(ca, cb, name_a, name_b, bounds):
    lo, size = bounds[0] * 100, bin_width(bounds)
    hi = bounds[1] * 100
    fig = go.Figure()
    peak = 0.0
    for series, name, color in [(ca, name_a, COLOR_A), (cb, name_b, COLOR_B)]:
        v = series * 100
        fig.add_trace(go.Histogram(
            x=v, name=f"{name} (histogram)", histnorm='probability density', legendgroup=name,
            xbins=dict(start=lo, end=hi + size, size=size), marker=dict(color=color, line=dict(color='white', width=1)),
            opacity=0.35, hovertemplate="%{x:.1f}% p.a.<br>density %{y:.3f}<extra>" + name + "</extra>"
        ))
        x, y = an.kde_curve(v)
        if len(x):
            peak = max(peak, y.max())
            fig.add_trace(go.Scatter(x=x, y=y, mode='lines', name=f"{name} (KDE)", legendgroup=name,
                                     line=dict(color=color, width=2),
                                     hovertemplate="%{x:.1f}% p.a.<extra>" + name + " KDE</extra>"))
    # Median dashed, mean dotted, in each fund's colour; their values are shown in the legend, not on the plot.
    for series, name, color in [(ca, name_a, COLOR_A), (cb, name_b, COLOR_B)]:
        add_stat_line(fig, series.median() * 100, color, 'dash', f"{name} median {series.median() * 100:.1f}%", name)
        add_stat_line(fig, series.mean() * 100, color, 'dot', f"{name} mean {series.mean() * 100:.1f}%", name)
    fig.update_layout(barmode='overlay', bargap=0)
    style_fig(fig, xaxis_title="Lumpsum Rolling CAGR (% p.a.)", yaxis_title="Probability Density", hovermode="closest")
    fig.update_xaxes(range=fixed_range(bounds))   # same x-axis for every window length; density axis autoscales
    legend_below(fig)
    return fig


def extremes_rows(cagr, starts, fund_a, fund_b, prices):
    rows = []
    for label, pick in [("Lowest", "idxmin"), ("Median", "median"), ("Highest", "idxmax")]:
        for fund in (fund_a, fund_b):
            s = cagr[fund]
            if pick == "median":
                end = (s - s.median()).abs().idxmin()
            else:
                end = getattr(s, pick)()
            start = starts.loc[end]
            window = prices.loc[start:end]
            rows.append({
                "Scenario": f"{label} window of {'A' if fund == fund_a else 'B'}",
                "Picked By": fund,
                "Start": start.strftime('%d %b %Y'),
                "End": end.strftime('%d %b %Y'),
                "A CAGR": cagr.loc[end, fund_a] * 100,
                "B CAGR": cagr.loc[end, fund_b] * 100,
                "A − B": (cagr.loc[end, fund_a] - cagr.loc[end, fund_b]) * 100,
                "A Max DD in Window": an.drawdown_series(window[fund_a]).min() * 100,
                "B Max DD in Window": an.drawdown_series(window[fund_b]).min() * 100,
            })
    return rows


@app.callback(
    [Output(oid, 'figure' if oid in DD_FIGURES else 'children') for oid in DD_OUTPUTS],
    [Input('dd-fund-a', 'value'),
     Input('dd-fund-b', 'value'),
     Input('dd-window', 'value'),
     Input('date-picker', 'start_date'),
     Input('date-picker', 'end_date'),
     Input('rf-rate', 'value')]
)
def update_deep_dive(fund_a, fund_b, window_years, start_date, end_date, rf_value=None):
    if not fund_a or not fund_b:
        return deep_dive_blank("Select two indices to compare.")
    if fund_a == fund_b:
        return deep_dive_blank("Fund A and Fund B are the same index; pick two different indices.")

    prices = filter_dates(start_date, end_date, [fund_a, fund_b])
    if len(prices) < 30:
        return deep_dive_blank("Not enough data in the selected date range.", "text-danger")
    rw = an.rolling_windows(prices, window_years)
    if len(rw["cagr"]) < 20:
        return deep_dive_blank(f"The selected date range has too few {window_years}-year windows; widen the range or shorten the window.",
                               "text-danger")

    bounds = an.rolling_return_bounds(prices, DEEP_DIVE_WINDOWS)
    cagr = rw["cagr"]
    ca, cb = cagr[fund_a], cagr[fund_b]
    excess = ca - cb
    n = len(cagr)
    warning = html.Div(
        f"Lumpsum (one-time investment) rolling returns: {n:,} overlapping {window_years}-year windows ending {cagr.index[0]:%d %b %Y} to {cagr.index[-1]:%d %b %Y}. "
        "Overlapping windows are highly correlated, so treat frequencies as descriptive, not as independent trials.",
        className="text-muted small"
    )

    # 1. Distribution
    fig_dist = distribution_figure(ca, cb, fund_a, fund_b, bounds['cagr'])
    sa, sb = an.distribution_stats(ca), an.distribution_stats(cb)
    dist_caption = (f"A: median {sa['Median']*100:.1f}%, KDE peak {sa['Mode (KDE peak)']*100:.1f}%, skew {sa['Skewness']:.2f}. "
                    f"B: median {sb['Median']*100:.1f}%, KDE peak {sb['Mode (KDE peak)']*100:.1f}%, skew {sb['Skewness']:.2f}. "
                    "For a symmetric distribution the peak sits on the median; skew pulls them apart. "
                    "The x-axis is fixed to the lowest and highest rolling return of these two funds across all 1-10 year windows, "
                    "so it does not rescale when you move the slider (the density axis does).")

    # 2. Excess return distribution, coloured by who won
    ex = excess * 100
    size = bin_width(bounds['excess'])
    bins = dict(start=bounds['excess'][0] * 100, end=bounds['excess'][1] * 100 + size, size=size)
    fig_ex = go.Figure()
    for mask, label, color in [(ex >= 0, f"A ahead ({fund_a})", COLOR_A), (ex < 0, f"B ahead ({fund_b})", COLOR_B)]:
        fig_ex.add_trace(go.Histogram(x=ex[mask], name=label, xbins=bins,
                                      marker=dict(color=color, line=dict(color='white', width=1)),
                                      hovertemplate="%{x:.1f} pp: %{y} windows<extra></extra>"))
    fig_ex.add_vline(x=0, line=dict(color="#212529", width=1))
    add_stat_line(fig_ex, ex.median(), "#52514e", 'dash', f"Median {ex.median():+.1f} pp")
    add_stat_line(fig_ex, ex.mean(), "#52514e", 'dot', f"Mean {ex.mean():+.1f} pp")
    fig_ex.update_layout(barmode='stack', bargap=0.02)
    style_fig(fig_ex, xaxis_title="A − B Rolling CAGR (percentage points)", yaxis_title="Number of Windows", hovermode="closest")
    fig_ex.update_xaxes(range=fixed_range(bounds['excess']))
    legend_below(fig_ex)
    win = (excess > 0).mean()
    excess_caption = (f"A beat B in {win*100:.1f}% of windows. Median edge {ex.median():+.2f} pp, "
                      f"worst {ex.min():+.2f} pp, best {ex.max():+.2f} pp.")

    # 3. Statistics table
    se = an.distribution_stats(excess)
    # Threshold rows compare a return with 6/12/15% and mean nothing for a return *difference*.
    no_excess = {"% Windows Below 6% (FD rate)", "% Windows Above 12%", "% Windows Above 15%"}

    def fmt_stat(key, v):
        if v is None or pd.isna(v):
            return "—"
        if key == "Windows":
            return f"{v:,.0f}"
        if key == "Skewness":
            return f"{v:.2f}"
        return f"{v * 100:.2f}%"

    records = [{"Statistic": key, "Fund A": fmt_stat(key, sa[key]), "Fund B": fmt_stat(key, sb[key]),
                "A − B (excess)": "—" if key in no_excess else fmt_stat(key, se[key])} for key in sa]
    records.append({"Statistic": "% Windows Won", "Fund A": f"{win * 100:.2f}%", "Fund B": f"{(1 - win) * 100:.2f}%",
                    "A − B (excess)": "—"})
    stats_table = html.Div([
        html.Small(f"A = {fund_a}; B = {fund_b}. Returns are % p.a. The excess column is the distribution of A − B "
                   "(so its '% Windows Negative' is the share of windows B won).", className="text-muted d-block mb-2"),
        make_table(records, [("Statistic", "text"), ("Fund A", "text"), ("Fund B", "text"), ("A − B (excess)", "text")],
                   header_color='#8e44ad', sortable=False, font_size='12px')
    ])

    # 4. Rolling over time with extremes marked
    fig_roll = go.Figure()
    for name, s, color in [(fund_a, ca, COLOR_A), (fund_b, cb, COLOR_B)]:
        fig_roll.add_trace(go.Scatter(x=s.index, y=s * 100, name=name, mode='lines', line=dict(color=color, width=2)))
        for pick, symbol in [("idxmin", "triangle-down"), ("idxmax", "triangle-up")]:
            d = getattr(s, pick)()
            fig_roll.add_trace(go.Scatter(
                x=[d], y=[s[d] * 100], mode='markers', showlegend=False,
                marker=dict(symbol=symbol, size=13, color=color, line=dict(color='white', width=2)),
                hovertemplate=f"{'Worst' if pick == 'idxmin' else 'Best'} window of {name}<br>"
                              f"{rw['start'][d]:%d %b %Y} → {d:%d %b %Y}<br>%{{y:.2f}}% p.a.<extra></extra>"))
    fig_roll.add_hline(y=0, line=dict(color="#212529", width=1))
    style_fig(fig_roll, xaxis_title="Window End Date", yaxis_title=f"Lumpsum Rolling {window_years}Y CAGR (% p.a.)")

    # 5. Extremes table
    extremes = extremes_rows(cagr, rw["start"], fund_a, fund_b, prices)
    extremes_table = make_table(extremes, [
        ("Scenario", "text"), ("Picked By", "text"), ("Start", "text"), ("End", "text"), ("A CAGR", "pct"),
        ("B CAGR", "pct"), ("A − B", "pct"), ("A Max DD in Window", "pct"), ("B Max DD in Window", "pct")
    ], header_color='#8e44ad', sortable=False, font_size='12px')

    # 6. Calendar years
    cy = an.calendar_year_returns(prices) * 100
    labels = [str(y) for y in cy.index]
    if prices.index[0] > pd.Timestamp(year=prices.index[0].year, month=1, day=10):
        labels[0] += "*"
    if prices.index[-1] < pd.Timestamp(year=prices.index[-1].year, month=12, day=20):
        labels[-1] += " YTD"
    fig_cy = go.Figure()
    for name, color in [(fund_a, COLOR_A), (fund_b, COLOR_B)]:
        fig_cy.add_trace(go.Bar(x=labels, y=cy[name], name=name, marker=dict(color=color, line=dict(color='white', width=2)),
                                hovertemplate="%{x}: %{y:.1f}%<extra>" + name + "</extra>"))
    fig_cy.update_layout(barmode='group', bargap=0.25, bargroupgap=0.05)
    style_fig(fig_cy, xaxis_title="Calendar Year", yaxis_title="Return (%)", hovermode="x unified")
    fig_cy.update_xaxes(tickangle=-45, automargin=True)
    years_won = int((cy[fund_a] > cy[fund_b]).sum())
    cal_caption = (f"A beat B in {years_won} of {len(cy)} calendar years. "
                   f"A best/worst year: {cy[fund_a].max():.1f}% / {cy[fund_a].min():.1f}%; "
                   f"B best/worst year: {cy[fund_b].max():.1f}% / {cy[fund_b].min():.1f}%. "
                   "* partial first year; YTD = year to date.")

    # 7. Full-period metrics
    m = an.run_metrics_analysis(prices, rf_from(rf_value), benchmark=filter_dates(start_date, end_date)[M2_BENCHMARK])
    dd = an.drawdown_series(prices)
    ep_a, ep_b = an.drawdown_episodes(prices[fund_a], 5), an.drawdown_episodes(prices[fund_b], 5)
    longest = {f: max((e["Days Underwater"] for e in an.drawdown_episodes(prices[f], 10_000)), default=0) for f in (fund_a, fund_b)}
    metric_rows = [
        ("CAGR", "pct"), ("Volatility", "pct"), ("Downside Volatility", "pct"), ("Return / Volatility", "ratio"),
        ("Return / Downside Volatility", "ratio"), ("Sharpe Ratio", "ratio"), ("Sortino Ratio", "ratio"),
        ("Risk-Adjusted Return", "pct"), ("Max Drawdown", "pct"),
    ]
    raw = [(key, kind, m.loc[fund_a, key], m.loc[fund_b, key]) for key, kind in metric_rows]
    raw += [
        ("Current Drawdown", "pct", dd[fund_a].iloc[-1], dd[fund_b].iloc[-1]),
        ("Longest Time Underwater (days)", "days", longest[fund_a], longest[fund_b]),
        ("Best Calendar Year", "pct", cy[fund_a].max() / 100, cy[fund_b].max() / 100),
        ("Worst Calendar Year", "pct", cy[fund_a].min() / 100, cy[fund_b].min() / 100),
    ]
    fmt_kind = {"pct": lambda v: f"{v * 100:.2f}%", "ratio": lambda v: f"{v:.2f}", "days": lambda v: f"{v:,.0f}"}
    fmt_diff = {"pct": lambda v: f"{v * 100:+.2f} pp", "ratio": lambda v: f"{v:+.2f}", "days": lambda v: f"{v:+,.0f}"}
    mrecords = [{"Metric": key, "Fund A": fmt_kind[kind](a), "Fund B": fmt_kind[kind](b), "A − B": fmt_diff[kind](a - b)}
                for key, kind, a, b in raw]
    metrics_table = make_table(mrecords, [("Metric", "text"), ("Fund A", "text"), ("Fund B", "text"), ("A − B", "text")],
                               header_color='#2c3e50', sortable=False, font_size='12px')

    # 8. Relationship
    rel = an.relationship_stats(prices[fund_a], prices[fund_b], RF_RATE)
    pct_keys = {"Tracking Error (A - B, annualised)", "Up-Market Capture of A vs B (monthly)",
                "Down-Market Capture of A vs B (monthly)", "% Months A Beat B"}
    rel_records = [{"Measure": k, "Value": "—" if pd.isna(v) else (f"{v * 100:.2f}%" if k in pct_keys else f"{v:.2f}")}
                   for k, v in rel.items()]
    rel_table = html.Div([
        make_table(rel_records, [("Measure", "text"), ("Value", "text")], header_color='#2c3e50', sortable=False, font_size='12px'),
        html.Small("Capture > 100% in up markets and < 100% in down markets is the ideal asymmetry. "
                   "Beta > 1 means A amplifies B's weekly moves.", className="text-muted d-block mt-2")
    ])

    # 9. Drawdowns
    fig_dd = go.Figure()
    for name, color in [(fund_a, COLOR_A), (fund_b, COLOR_B)]:
        fig_dd.add_trace(go.Scatter(x=dd.index, y=dd[name] * 100, name=name, mode='lines', line=dict(color=color, width=2)))
    style_fig(fig_dd, yaxis_title="Drawdown (%)")
    fig_dd.update_yaxes(range=[dd.min().min() * 100 - 5, 2])

    ep_records = []
    for fund, eps in [(fund_a, ep_a), (fund_b, ep_b)]:
        for i, e in enumerate(eps, 1):
            ep_records.append({
                "Index": f"{'A' if fund == fund_a else 'B'}: {fund}", "#": i, "Peak": fmt_date(e["Peak"]),
                "Trough": fmt_date(e["Trough"]), "Recovered": fmt_date(e["Recovery"]), "Depth": e["Depth"] * 100,
                "Days to Trough": e["Days to Trough"], "Days to Recover": e["Days to Recover"],
            })
    episodes_table = make_table(ep_records, [
        ("Index", "text"), ("#", "int"), ("Peak", "text"), ("Trough", "text"), ("Recovered", "text"),
        ("Depth", "pct"), ("Days to Trough", "int"), ("Days to Recover", "int")
    ], header_color='#c0392b', sortable=False, font_size='12px')

    return [warning, dist_caption, fig_dist, excess_caption, fig_ex, stats_table, fig_roll, extremes_table,
            cal_caption, fig_cy, metrics_table, rel_table, fig_dd, episodes_table]


@app.callback(
    Output('dd-path-chart', 'figure'),
    [Input('dd-fund-a', 'value'),
     Input('dd-fund-b', 'value'),
     Input('dd-window', 'value'),
     Input('dd-path-selector', 'value'),
     Input('date-picker', 'start_date'),
     Input('date-picker', 'end_date')]
)
def update_deep_dive_path(fund_a, fund_b, window_years, which, start_date, end_date):
    if not fund_a or not fund_b or fund_a == fund_b:
        return empty_fig("Pick two different indices.")
    prices = filter_dates(start_date, end_date, [fund_a, fund_b])
    rw = an.rolling_windows(prices, window_years)
    if len(rw["cagr"]) < 20:
        return empty_fig("Not enough windows in the selected date range.")
    fund = fund_a if which.endswith('_a') else fund_b
    s = rw["cagr"][fund]
    end = s.idxmin() if which.startswith('worst') else s.idxmax()
    start = rw["start"][end]
    path = prices.loc[start:end]
    path = path / path.iloc[0] * 100
    fig = go.Figure()
    for name, color in [(fund_a, COLOR_A), (fund_b, COLOR_B)]:
        fig.add_trace(go.Scatter(x=path.index, y=path[name], name=name, mode='lines', line=dict(color=color, width=2),
                                 hovertemplate="%{y:.1f}<extra>" + name + "</extra>"))
    fig.add_hline(y=100, line=dict(color="#212529", width=1, dash='dot'))
    style_fig(fig, yaxis_title="Value (Base = 100 at window start)")
    fig.update_layout(
        title=dict(text=f"{'Worst' if which.startswith('worst') else 'Best'} {window_years}Y window of {fund}: "
                        f"{start:%d %b %Y} → {end:%d %b %Y}", font=dict(color="#212529", size=13),
                   x=0.01, xanchor="left", y=0.98, yanchor="top"),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="left", x=0),
        margin=dict(l=20, r=20, t=40, b=20))
    return fig


# Callback for TAB 6: Correlation matrix
@app.callback(
    Output('correlation-heatmap', 'figure'),
    [Input('index-dropdown', 'value'),
     Input('date-picker', 'start_date'),
     Input('date-picker', 'end_date')]
)
def update_tab6(selected_indices, start_date, end_date):
    if not selected_indices or len(selected_indices) < 2:
        return empty_fig("Select at least two indices.")

    df_filtered_weekly = filter_dates(start_date, end_date, selected_indices).resample('W').last()
    corr_matrix_filtered = df_filtered_weekly.pct_change().dropna().corr(method='pearson')

    fig = corr_heatmap(corr_matrix_filtered, 0.4, 1.0, "Correlation")
    return fig


# Excess-return correlation (second half of the Correlation tab)
EXCESS_OUTPUTS = [Output('excess-corr-caption', 'children'), Output('excess-correlation-heatmap', 'figure'),
                  Output('excess-pairs-table', 'children')]


@app.callback(
    EXCESS_OUTPUTS,
    [Input('index-dropdown', 'value'),
     Input('excess-benchmark', 'value'),
     Input('date-picker', 'start_date'),
     Input('date-picker', 'end_date')]
)
def update_excess_correlation(selected_indices, benchmark, start_date, end_date):
    def blank(msg):
        return msg, empty_fig(msg), None

    if not benchmark:
        return blank("Pick a benchmark.")
    others = [c for c in (selected_indices or []) if c != benchmark]
    if len(others) < 2:
        return blank(f"Select at least two indices other than the benchmark ({benchmark}).")

    prices = filter_dates(start_date, end_date)
    if len(prices) < 60:
        return blank("Not enough data in the selected date range.")
    corr = an.excess_return_correlation(prices, benchmark, others)

    fig = corr_heatmap(corr, -1, 1, "Excess-return correlation")

    pairs = an.pair_table(corr)
    weeks = len(an.weekly_returns(prices[[benchmark]]))
    caption = (f"Weekly returns minus {benchmark}, {weeks:,} weeks from {prices.index[0]:%d %b %Y} to {prices.index[-1]:%d %b %Y}. "
               f"Across {len(pairs)} pairs the median correlation is {pairs['Correlation'].median():.2f}; "
               f"{int((pairs['Correlation'] < 0).sum())} pairs are negative. "
               "Rows are ordered so similar indices sit together; hover a cell for the pair and value.")

    low = pairs.head(10)
    pairs_table = make_table(
        [{"Index A": r["Index A"], "Index B": r["Index B"], "Excess Correlation": r["Correlation"]} for _, r in low.iterrows()],
        [("Index A", "text"), ("Index B", "text"), ("Excess Correlation", "ratio")],
        header_color='#8e44ad', sortable=False, font_size='12px')
    return caption, fig, pairs_table


# One fund vs every other index (beside the excess heatmap)
@app.callback(
    [Output('fund-corr-caption', 'children'), Output('fund-corr-table', 'children')],
    [Input('corr-fund', 'value'),
     Input('index-dropdown', 'value'),
     Input('excess-benchmark', 'value'),
     Input('date-picker', 'start_date'),
     Input('date-picker', 'end_date')]
)
def update_fund_correlation(fund, selected_indices, benchmark, start_date, end_date):
    if not fund or not benchmark:
        return "Pick a fund.", None
    if fund == benchmark:
        return (f"{fund} is the current benchmark, so its excess return is zero. Pick another fund, or change the benchmark.", None)
    prices = filter_dates(start_date, end_date)
    if len(prices) < 60:
        return "Not enough data in the selected date range.", None
    table = an.fund_correlations(prices, fund, benchmark, selected_indices or [])
    if table.empty:
        return f"Select at least one index other than {fund} and the benchmark ({benchmark}).", None

    best = table.loc[table["Excess Correlation"].idxmin()]
    worst = table.loc[table["Excess Correlation"].idxmax()]
    caption = (f"{fund} against {len(table)} indices, weekly returns, benchmark {benchmark}. "
               f"Best diversifier: {best['Index']} ({best['Excess Correlation']:.2f}); most similar: {worst['Index']} ({worst['Excess Correlation']:.2f}).")
    records = table.to_dict('records')
    return caption, make_table(
        records, [("Index", "text"), ("Excess Correlation", "ratio"), ("Raw Correlation", "ratio")],
        header_color='#8e44ad', sortable=True, font_size='12px',
        sort_by=[{'column_id': 'Excess Correlation', 'direction': 'asc'}],
        column_widths={'Index': '46%', 'Excess Correlation': '27%', 'Raw Correlation': '27%'})


# -------------------------------------------------------------
# 6. RUN THE APPLICATION SERVER
# -------------------------------------------------------------
if __name__ == '__main__':
    print("\nStarting Dash server...")
    print("Dashboard will be available at: http://127.0.0.1:4400/")
    app.run(debug=True, port=4400)
