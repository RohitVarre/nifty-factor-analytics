import os
import sys
import time
import json
import datetime as dt
import requests
import pandas as pd

# Define directories for caching and output
CACHE_DIR = "cache"
DATA_DIR = "data"
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# niftyindices.com moved this endpoint from /Backpage.aspx/... to /BackPage/... in 2026.
# The old URL now returns the site's HTML home page with HTTP 200.
TRI_URL = "https://www.niftyindices.com/BackPage/getTotalReturnIndexString"
HEADERS = {
    "Content-Type": "application/json; charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.niftyindices.com/reports/historical-data"
}

FIRST_YEAR = 2005
TODAY = dt.date.today()
CURRENT_YEAR = TODAY.year

# List of 19 indices to analyze (all available from April 2005)
symbols = {
    # Broad-based Indices
    "Nifty 50": "Nifty 50",
    "Nifty Next 50": "Nifty Next 50",
    "Nifty 500": "Nifty 500",
    "Nifty Midcap 150": "Nifty Midcap 150",
    "Nifty Smallcap 250": "Nifty Smallcap 250",
    "Nifty Smallcap 500": "Nifty Smallcap 500",
    "Nifty Microcap 250": "Nifty Microcap250",
    "Nifty Total Market": "Nifty Total Mkt",
    # Strategic / Factor Indices
    "Nifty500 Low Volatility 50": "Nifty500 Low Volatility 50",
    "Nifty500 Momentum 50": "Nifty500 Momentum 50",
    "Nifty500 Quality 50": "Nifty500 Quality 50",
    "Nifty200 Momentum 30": "Nifty200 Momentum 30",
    "Nifty200 Alpha 30": "Nifty200 Alpha 30",
    "Nifty500 Multifactor MQVLv 50": "Nifty500 Multifactor MQVLv 50",
    "Nifty Total Market Momentum Quality 50": "Nifty Total Market Momentum Quality 50",
    "Nifty500 Multicap Momentum Quality 50": "Nifty500 Multicap Momentum Quality 50",
    "Nifty200 Value 30": "Nifty200 Value 30",
    "Nifty500 Value 50": "Nifty500 Value 50",
    "Nifty200 Quality 30": "Nifty200 Quality 30",
    # Added 2026-10-17: every other NSE strategy index with TRI history from 1 Apr 2005
    # (see reference/nse_equity_indices.csv). API names reuse existing cache file names where they exist.
    "Nifty Alpha 50": "NIFTY ALPHA 50",
    "Nifty100 Alpha 30": "Nifty100 Alpha 30",
    "Nifty Low Volatility 50": "Nifty Low Volatility 50",
    "Nifty100 Low Volatility 30": "NIFTY100 LOWVOL30",
    "Nifty Alpha Low-Volatility 30": "Nifty Alpha Low-Volatility 30",
    "Nifty Alpha Quality Low-Volatility 30": "Nifty Alpha Quality Low-Volatility 30",
    "Nifty Alpha Quality Value Low-Volatility 30": "Nifty Alpha Quality Value Low-Volatility 30",
    "Nifty Quality Low-Volatility 30": "Nifty Quality Low-Volatility 30",
    "Nifty Midcap150 Momentum 50": "Nifty Midcap150 Momentum 50",
    "Nifty Midcap150 Quality 50": "Nifty Midcap150 Quality 50",
    "Nifty MidSmallcap400 Momentum Quality 100": "Nifty MidSmallcap400 Momentum Quality 100",
    "Nifty Smallcap250 Momentum Quality 100": "Nifty Smallcap250 Momentum Quality 100",
    "Nifty Smallcap250 Quality 50": "Nifty Smallcap250 Quality 50",
    "Nifty500 Growth 50": "Nifty500 Growth 50",
    "Nifty High Dividend Yield 15": "Nifty High Dividend Yield 15",
    "Nifty High Beta 50": "Nifty High Beta 50",
    "Nifty50 Equal Weight": "Nifty50 Equal Weight",
    "Nifty100 Equal Weight": "Nifty100 Equal Weight",
    "Nifty500 Equal Weight": "Nifty500 Equal Weight",
    "Nifty500 LargeMidSmall Equal-Cap Weighted": "Nifty500 LargeMidSmall Equal-Cap Weighted",
    "Nifty500 Multicap 50:25:25": "Nifty500 Multicap 50:25:25",
    "Nifty MidSmallcap400 50:50": "Nifty MidSmallcap400 50:50",
}


def parse_response(text):
    """The endpoint answers with a bare JSON list (content-type text/html); the old one
    wrapped a JSON string in {'d': ...}. Accept both, reject anything else (e.g. HTML)."""
    payload = json.loads(text)
    if isinstance(payload, dict):
        payload = payload.get('d')
        if isinstance(payload, str):
            payload = json.loads(payload)
    if not isinstance(payload, list):
        raise ValueError("unexpected response shape")
    return pd.DataFrame(payload)


def fetch_index_tri_year(symbol_api, year):
    cache_path = os.path.join(CACHE_DIR, f"{symbol_api.replace(' ', '_').replace(':', '_')}_{year}.csv")
    # Past years are immutable, so the cache is trusted. The current year is always re-fetched
    # because its cache file only holds data up to the day it was downloaded.
    if os.path.exists(cache_path) and year < CURRENT_YEAR:
        return pd.read_csv(cache_path)

    start_date = f"01-Jan-{year}" if year > FIRST_YEAR else "01-Apr-2005"
    end_date = f"31-Dec-{year}" if year < CURRENT_YEAR else TODAY.strftime("%d-%b-%Y")

    inner_payload = {
        "name": symbol_api,
        "startDate": start_date,
        "endDate": end_date,
        "indexName": symbol_api
    }
    payload = {"cinfo": json.dumps(inner_payload)}

    # Retry logic up to 3 times
    for attempt in range(3):
        try:
            response = requests.post(TRI_URL, headers=HEADERS, json=payload, timeout=30)
            if response.status_code == 200:
                df = parse_response(response.text)
                if not df.empty:
                    df.to_csv(cache_path, index=False)
                    print(f"  * Cached {symbol_api} for {year} ({len(df)} records)")
                    time.sleep(0.5) # small delay to prevent blocking
                    return df
                print(f"  * Empty response for {symbol_api} in {year}")
                return pd.DataFrame()
            print(f"  * Attempt {attempt+1} failed for {symbol_api} in {year}: Status {response.status_code}")
        except Exception as e:
            print(f"  * Attempt {attempt+1} error for {symbol_api} in {year}: {e}")
        time.sleep(1.0)

    # Fall back to a stale current-year cache rather than silently dropping the year.
    if os.path.exists(cache_path):
        print(f"  * Using stale cache for {symbol_api} in {year}")
        return pd.read_csv(cache_path)
    return pd.DataFrame()


def main():
    print(f"Starting year-by-year index TRI download ({FIRST_YEAR} - {TODAY:%d %b %Y}):")
    failures = []
    for name, symbol_api in symbols.items():
        print(f"\nDownloading data for: {name} (API Name: {symbol_api})")
        all_dfs = []
        missing_years = []
        for year in range(FIRST_YEAR, CURRENT_YEAR + 1):
            df_year = fetch_index_tri_year(symbol_api, year)
            if df_year.empty:
                missing_years.append(year)
            else:
                all_dfs.append(df_year)

        # Never overwrite a good data file with a series that has holes in it.
        if missing_years or not all_dfs:
            print(f"FAILED: {name} is missing years {missing_years}; keeping the existing data file")
            failures.append(name)
            continue

        combined_df = pd.concat(all_dfs, ignore_index=True)
        # Parse Date and sort
        combined_df['Date'] = pd.to_datetime(combined_df['Date'], format='%d %b %Y', errors='coerce')
        combined_df['TotalReturnsIndex'] = pd.to_numeric(combined_df['TotalReturnsIndex'], errors='coerce')
        combined_df = combined_df.dropna(subset=['Date', 'TotalReturnsIndex']).sort_values('Date').reset_index(drop=True)

        # Keep only required columns and rename
        combined_df = combined_df[['Date', 'TotalReturnsIndex']].rename(columns={'TotalReturnsIndex': name})
        combined_df = combined_df.drop_duplicates(subset=['Date']).reset_index(drop=True)

        # Save to data directory
        out_path = os.path.join(DATA_DIR, f"{name.replace(' ', '_').replace(':', '-')}_TRI.csv")
        combined_df.to_csv(out_path, index=False)
        print(f"SUCCESS: Saved {name} TRI to {out_path} ({len(combined_df)} records, {combined_df['Date'].min().strftime('%Y-%m-%d')} to {combined_df['Date'].max().strftime('%Y-%m-%d')})")

    if failures:
        print(f"\n{len(failures)} index(es) failed: {failures}")
        sys.exit(1)
    print("\nAll indices downloaded successfully.")


if __name__ == "__main__":
    main()
