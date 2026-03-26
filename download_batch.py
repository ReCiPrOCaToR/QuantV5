"""
download_batch.py - Batch download 100 stocks via Alpaca Data API v2
Uses /v2/stocks/bars endpoint (up to 200 symbols per request)
"""
import os
import time
import pickle
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
BASE_URL = os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

DATA_URL = "https://data.alpaca.markets"

# 100 liquid stocks across all sectors
UNIVERSE_100 = [
    # Tech (25)
    "AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","AMD","AVGO","CRM",
    "ORCL","ADBE","INTC","CSCO","QCOM","TXN","AMAT","MU","NOW","SNOW",
    "PLTR","PANW","SNPS","CDNS","MRVL",
    # Finance (12)
    "JPM","GS","V","MA","BLK","SPGI","MS","BAC","WFC","AXP","SCHW","C",
    # Healthcare (12)
    "JNJ","UNH","LLY","ABBV","MRK","PFE","TMO","ABT","DHR","BMY","ISRG","MDT",
    # Consumer (12)
    "COST","NKE","PG","KO","PEP","MCD","SBUX","HD","LOW","TGT","WMT","EL",
    # Energy (8)
    "XOM","CVX","COP","SLB","EOG","OXY","PSX","MPC",
    # Industrial (8)
    "CAT","DE","HON","UNP","UPS","GE","RTX","BA",
    # Communication (5)
    "NFLX","DIS","CMCSA","T","VZ",
    # Materials (4)
    "LIN","APD","SHW","ECL",
    # REIT (4)
    "AMT","PLD","CCI","EQIX",
    # Utilities (2)
    "NEE","DUK",
    # Sectors ETF + Hedge
    "SPY","SH","XLU","XLV","XLP","XLE","XLF","XLK",
]


def download_bars(symbols, days=730):
    """Download daily bars for multiple symbols via Alpaca Data API v2."""
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    
    headers = {
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": SECRET_KEY,
    }
    
    all_data = {}
    batch_size = 50  # Alpaca limit
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]
        sym_str = ",".join(batch)
        
        url = f"{DATA_URL}/v2/stocks/bars"
        params = {
            "symbols": sym_str,
            "timeframe": "1Day",
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "limit": 10000,
            "adjustment": "split",
            "feed": "iex",  # Free tier
        }
        
        print(f"  Downloading batch {i//batch_size+1}/{(len(symbols)-1)//batch_size+1} ({len(batch)} symbols)...")
        
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        
        if resp.status_code != 200:
            print(Fore.RED + f"  [ERROR] {resp.status_code}: {resp.text[:200]}" + Style.RESET_ALL)
            continue
        
        data = resp.json()
        bars = data.get("bars", {})
        
        for sym, bar_list in bars.items():
            if not bar_list:
                continue
            
            rows = []
            for bar in bar_list:
                rows.append({
                    "open": bar["o"],
                    "high": bar["h"],
                    "low": bar["l"],
                    "close": bar["c"],
                    "volume": bar["v"],
                })
            
            df = pd.DataFrame(rows)
            df.index = pd.to_datetime([bar["t"] for bar in bar_list])
            df.index = df.index.tz_localize(None)  # Strip timezone
            
            if len(df) > 60:
                # Compute indicators
                from indicators import compute_all_indicators
                df = compute_all_indicators(df)
                all_data[sym] = df
                
                # Cache individually
                cache_path = CACHE_DIR / f"{sym}_{days}d_1Day.pkl"
                with open(cache_path, "wb") as f:
                    pickle.dump(df, f)
        
        time.sleep(0.5)  # Rate limit
    
    return all_data


def main():
    print(Fore.CYAN + "\n" + "="*60)
    print("  BATCH DOWNLOAD - 100 Stocks")
    print("="*60 + Style.RESET_ALL)
    
    print(f"\n  API Key: {API_KEY[:8]}...")
    print(f"  Stocks: {len(UNIVERSE_100)}")
    
    result = download_bars(UNIVERSE_100, days=730)
    
    print(Fore.GREEN + f"\n  Downloaded: {len(result)} symbols" + Style.RESET_ALL)
    for sym, df in sorted(result.items()):
        print(f"  {sym}: {len(df)} rows ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
    
    # Save combined cache
    combined_path = CACHE_DIR / "batch_100d.pkl"
    with open(combined_path, "wb") as f:
        pickle.dump(result, f)
    print(f"\n  Combined cache: {combined_path} ({len(result)} symbols)")


if __name__ == "__main__":
    main()
