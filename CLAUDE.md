# QuantV5 - V5 Sector ETF Rotation

## Project

Sector ETF rotation strategy on Alpaca Paper Trading. See `trading-knowledge.md` in the workspace root for full documentation.

## Key Files

- `strategy_sector.py` - Strategy + backtest (SectorRotation class)
- `live_trader_v5.py` - Live trading (LiveTraderV5 class, SECTOR_ETFS module constant)
- `server.py` - Flask dashboard (V5 only, no V2/V4 code)
- `dashboard.html` - Frontend UI

## Strategy

- Universe: 9 sector ETFs (XLK/XLE/XLF/XLV/XLU/XLP/XLI/XLRE/XBI)
- Signal: 30-day relative strength vs SPY
- Hold: Top 2 with positive RS
- Rebalance: Every 15 trading days
- Bear market: SPY < SMA200 → 50% cash
- Stop: 10% trailing from peak

## Known Issues

1. data_cache.get() has 6-hour freshness check - touch cache files if stale
2. SECTOR_ETFS is a module-level constant, not a class attribute
3. Only 730d cache exists for sector ETFs
4. Market orders don't fill outside US market hours (22:00-04:00 Beijing)
