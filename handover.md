> **Superseded (2026-09-28):** see [AGENTS.md](AGENTS.md) and [README.md](README.md). This file is kept for history; its port (8050), API endpoint, date range and findings are out of date.

# Project Handover Guide: Quantitative Analysis of Indian Stock Indices (2005 - 2026)

Welcome to the **Indian Indices Quantitative Analysis** workspace. This document serves as your developer and researcher handbook, providing all necessary details, architecture secrets, mathematical frameworks, and operational steps required to seamlessly resume or extend this project in a future session.

---

## 1. Executive Summary & Scope

This project is an institutional-grade, cycle-tested quantitative study of **19 broad-based and strategic factor stock indices in India** spanning over **21 years (April 1, 2005 to June 17, 2026)**.

### Core Quantitative Philosophy: The TRI Advantage
Unlike standard index analyses that evaluate simple Price Return Indices (PRI), this project is built entirely on **Total Return Index (TRI)** data. Dividends represent a massive portion of long-term compounding in India. Evaluating strategic factor indices (such as Momentum or Quality) without dividends creates an inaccurate comparison. Tracking TRI data ensures a 100% fair, robust, and mathematically sound evaluation of actual investor outcomes.

---

## 2. Directory Architecture & File Guide

The workspace is organized into a clean, minimalist structure:

```text
index_analysis/
├── data/                       # Aligned master CSV datasets for each index (2005 - 2026)
├── cache/                      # Year-by-year downloaded CSV caches (prevents server spamming)
├── results/                    # Compiled high-resolution static charts and matrices
│   ├── correlation_heatmap_all.png
│   ├── cumulative_returns_all_log.png
│   ├── portfolio_performance_comparison.png
│   └── weekly_returns_correlation_matrix.csv
├── app.py                      # Interactive Dash Web Application & Dashboard
├── download_new_indices.py     # Automated 19-index year-by-year TRI scraper
├── Indian_Indices_Analysis.ipynb # Pre-executed, saved, interactive Jupyter Notebook
└── handover.md                 # Project handover document (this file)
```

### Core Files:
1.  **`app.py`**: The interactive Plotly Dash dashboard. It includes global date and multi-select index controls, dynamic metric calculations on-the-fly, rolling CAGR and Volatility analysis, weekly returns correlation heatmap, and an interactive Scipy-based factor portfolio optimizer.
2.  **`download_new_indices.py`**: Automated data pipeline. Queries the official `niftyindices.com` database, caches year-by-year records to `/cache/` (so that subsequent runs do not hit the server and are completed instantly), merges year-by-year caches into continuous historical datasets, and saves them to `/data/`.
3.  **`Indian_Indices_Analysis.ipynb`**: Your master Jupyter Notebook, containing rich LaTeX commentary, pre-executed and embedded charts, and rolling returns/volatilities calculations.

---

## 3. Data Acquisition Secrets (Direct API Scraping)

We bypass Yahoo Finance's severe data gaps (missing strategic indices, short histories) by querying the official National Stock Exchange (NSE) database directly.

### The Endpoint:
*   **Total Return Index (TRI):** `https://www.niftyindices.com/Backpage.aspx/getTotalReturnIndexString`
*   **Standard Price Index (PRI):** `https://www.niftyindices.com/Backpage.aspx/getHistoricaldatatabletoString`

### Payload Structure:
The NSE server is highly sensitive and expects parameters wrapped inside a stringified JSON value under the key **`cinfo`**:

```python
import requests
import json

headers = {
    "Content-Type": "application/json; charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36..."
}

payload = {
    "cinfo": json.dumps({
        "name": "NIFTY500 MOMENTUM 50",
        "startDate": "01-Jan-2024",
        "endDate": "15-Jan-2024",
        "indexName": "NIFTY500 MOMENTUM 50" # Some methods require both name and indexName
    })
}

response = requests.post(url, headers=headers, json=payload)
raw_data = json.loads(response.json()['d']) # 'd' contains stringified inner JSON array
```

### Critical API Index Display Names:
*   **Nifty Microcap 250:** officially named **`Nifty Microcap250`** (no space).
*   **Nifty Total Market:** officially named **`Nifty Total Mkt`** (abbreviated).

---

## 4. Setup, Environment & Operation

The project was executed in the conda environment **`main`**.

### Required Python Libraries:
Ensure you have the following packages installed:
```bash
pip install pandas numpy matplotlib seaborn plotly dash dash-bootstrap-components scipy tabulate
```

### Running the Project:

*   **To run the interactive dashboard:**
    ```bash
    python app.py
    ```
    Once started, navigate your browser to **[http://127.0.0.1:8050/](http://127.0.0.1:8050/)**.

*   **To download/re-compile raw datasets:**
    ```bash
    python download_new_indices.py
    ```

*   **To open and run the Jupyter Notebook:**
    ```bash
    jupyter notebook Indian_Indices_Analysis.ipynb
    ```

---

## 5. Core Quantitative Findings

1.  **Multi-Factor Dominance (`MQVLv`):**
    *   **`Nifty500 Multifactor MQVLv 50`** combines Momentum, Quality, Value, and Low Volatility in equal parts. It achieved a **19.74% CAGR** (vs. Nifty 50's **13.66%**) over the 21.2-year history.
    *   It has the highest individual Sortino Ratio (**1.17**), a standard Sharpe of **0.78**, and a maximum drawdown of **-53.93%** (better than Nifty 50's **-59.50%** drawdown during the 2008 Financial Crisis).
2.  **The Rolling 5-Year Return Boundary:**
    *   Pure momentum strategies sometimes suffer from negative 5-year rolling returns (e.g. `Nifty500 Momentum 50` had a worst-case 5-year rolling return of **-4.76% p.a.**).
    *   In contrast, multi-factor and blended strategies like **`Nifty500 Multicap Momentum Quality 50`** had **zero negative 5-year periods** over the entire 21 years (worst-case return of **+4.76% p.a.**, mean of **+21.39% p.a.**). This completely eliminates the risk of 5-year capital loss while crushing the benchmark.
3.  **Maximum Sortino Synergy (Portfolio Optimization):**
    *   The Dash live Scipy optimizer solves for a weight structure of **~61.8% Low Volatility, ~30.7% Momentum, and ~7.5% Quality** when blending Nifty 500 factor indices.
    *   This portfolio achieves a Sortino of **1.24** — higher than any individual factor on its own, with volatility (~15.4%) lower than the standard Nifty 50 benchmark!

---

## 6. Future Roadmap Ideas (Resuming in a Future Session)

If you wish to expand this project, consider the following high-value quantitative research ideas:

1.  **Introduce Rebalancing Friction & Transaction Costs:**
    *   Currently, the optimized portfolios assume zero rebalancing cost. Introducing a **0.25% - 0.50% friction penalty** on semi-annual rebalancing would make the simulation extremely realistic.
2.  **Backtest an Active Rebalancing Strategy:**
    *   Write a backtest script that recalculates the Scipy optimal weights dynamically every month or quarter using a rolling look-back window (e.g., 36 months) and rebalances the portfolio accordingly, tracking its performance out-of-sample.
3.  **Factor Business-Cycle Rotator:**
    *   Model factor performance against economic regimes in India (using macro indicators like inflation, GDP growth, or 10-year G-Sec yield shifts). Create a rule-based rotator that shifts weights into *Value/Low-Vol* during contractions and *Momentum/Alpha* during expansions.

---

*Handover complete. Every detail, script, and database secret is preserved. You are ready to launch!*
