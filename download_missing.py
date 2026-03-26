"""
download_missing.py - Download missing symbols individually
"""
import os
import pickle
import time
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv
from colorama import init as colorama_init, Fore, Style

colorama_init()
load_dotenv()

CACHE_DIR = Path(__file__).parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

API_KEY = os.getenv("APCA_API_KEY_ID")
SECRET_KEY = os.getenv("APCA_API_SECRET_KEY")
DATA_URL = "https://data.alpaca.markets"

from indicators import compute_all_indicators

MISSING = ['MSFT','NVDA','META','TSLA','ORCL','INTC','QCOM','TXN','MU','NOW',
           'SNOW','PLTR','PANW','SNPS','MRVL','JPM','V','MA','SPGI','MS',
           'WFC','SCHW','JNJ','UNH','LLY','MRK','PFE','TMO','ISRG','MDT',
           'NKE','PG','PEP','MCD','SBUX','LOW','TGT','WMT','XOM','SLB',
           'OXY','PSX','MPC','UNP','UPS','RTX','NFLX','T','VZ','SHW',
           'PLD','NEE','SPY','SH','XLU','XLV','XLP','XLE','XLF','XLK']


def download_one(symbol, days=730):
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    headers = {"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET_KEY}
    params = {
        "symbols": symbol,
        "timeframe": "1Day",
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "limit": 10000,
        "adjustment": "split",
        "feed": "iex",
    }
    resp = requests.get(f"{DATA_URL}/v2/stocks/bars", headers=headers, params=params, timeout=15)
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"
    
    data = resp.json()
    bars = data.get("bars", {}).get(symbol, [])
    if not bars:
        return None, "no bars"
    
    rows = [{"open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"], "volume": b["v"]} for b in bars]
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime([b["t"] for b in bars])
    df.index = df.index.tz_localize(None)
    
    if len(df) > 60:
        df = compute_all_indicators(df)
        cache_path = CACHE_DIR / f"{symbol}_730d_1Day.pkl"
        with open(cache_path, "wb") as f:
            pickle.dump(df, f)
        return df, "ok"
    return None, "too few rows"


def main():
    got = {}
    
    # Load existing batch
    combined_path = CACHE_DIR / "batch_100d.pkl"
    if combined_path.exists():
        with open(combined_path, "rb") as f:
            got = pickle.load(f)
        print(f"Loaded {len(got)} from cache")
    
    for i, sym in enumerate(MISSING):
        df, status = download_one(sym, days=730)
        if df is not None:
            got[sym] = df
            print(f"  [{i+1}/{len(MISSING)}] {sym}: {len(df)} rows OK")
        else:
            print(Fore.RED + f"  [{i+1}/{len(MISSING)}] {sym}: {status}" + Style.RESET_ALL)
        time.sleep(0.3)
    
    # Save combined
    with open(combined_path, "wb") as f:
        pickle.dump(got, f)
    
    print(Fore.GREEN + f"\nTotal: {len(got)} symbols" + Style.RESET_ALL)


if __name__ == "__main__":
    main()
