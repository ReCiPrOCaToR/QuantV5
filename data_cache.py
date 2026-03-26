"""
data_cache.py — Market data disk cache
Prevents redundant API calls, saves to data/cache/ as pickle files.
Cache valid for 1 day (trading data changes daily).
"""
import os
import pickle
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).parent / "data" / "cache"
CACHE_MAX_AGE_HOURS = 6  # Re-fetch if older than 6 hours


def _cache_key(symbol: str, days: int, timeframe: str = "1Day") -> str:
    """Generate cache filename"""
    return f"{symbol}_{days}d_{timeframe}.pkl"


def _cache_path(key: str) -> Path:
    return CACHE_DIR / key


def _is_fresh(path: Path) -> bool:
    """Check if cache file is recent enough"""
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age < timedelta(hours=CACHE_MAX_AGE_HOURS)


def get(symbol: str, days: int, timeframe: str = "1Day") -> pd.DataFrame | None:
    """Load from cache if fresh, else return None"""
    key = _cache_key(symbol, days, timeframe)
    path = _cache_path(key)
    if not _is_fresh(path):
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def put(symbol: str, days: int, df: pd.DataFrame, timeframe: str = "1Day"):
    """Save DataFrame to disk cache"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(symbol, days, timeframe)
    path = _cache_path(key)
    try:
        with open(path, "wb") as f:
            pickle.dump(df, f)
    except Exception:
        pass


def clear():
    """Remove all cached files"""
    if CACHE_DIR.exists():
        for f in CACHE_DIR.iterdir():
            f.unlink()


def status() -> dict:
    """Return cache stats"""
    if not CACHE_DIR.exists():
        return {"files": 0, "total_size": 0}
    files = list(CACHE_DIR.glob("*.pkl"))
    total = sum(f.stat().st_size for f in files)
    return {
        "files": len(files),
        "total_size_mb": round(total / 1024 / 1024, 2),
        "oldest": min((f.stat().st_mtime for f in files), default=0),
    }
