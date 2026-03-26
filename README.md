# Alpaca Quant Trading Bot

Sector ETF Rotation strategy using Alpaca Paper Trading API.

## Strategy V5 — Sector ETF Rotation (Production)

### Core Logic

| Component | Detail |
|-----------|--------|
| **Universe** | 9 sector ETFs: XLK, XLE, XLF, XLV, XLU, XLP, XLI, XLRE, XBI |
| **Signal** | 30-day relative strength (ETF return minus SPY return) |
| **Selection** | Top 2 ETFs with positive RS |
| **Rebalance** | Every 15 trading days |
| **Trend filter** | SPY < SMA200 → 50% cash (bear market defense) |
| **Trailing stop** | 10% from peak price (individual ETF protection) |

### How It Works

1. Compute 30-day relative strength for each sector ETF vs SPY
2. Rank by RS, pick top 2 with positive RS
3. Sell positions no longer in top 2
4. Buy new top 2 positions
5. If SPY < SMA200: only deploy 50% capital
6. Monitor trailing stops daily (10% drawdown from peak)

### Risk Management

- **Trend filter**: Automatically reduces exposure in bear markets
- **Trailing stop**: Limits individual ETF losses to ~10%
- **Sector diversification**: Top 2 sectors reduce concentration risk
- **No leverage**: Cash-only, no margin

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Edit .env with your Alpaca Paper API keys

# 3. Scan only (no trading)
python live_trader_v5.py

# 4. Run backtest
python strategy_sector.py

# 5. Start web dashboard
python server.py
```

## Project Structure

```
alpaca-trading-bot/
├── strategy_sector.py  # V5 strategy + backtest engine
├── live_trader_v5.py   # V5 live trading engine
├── live_state_v5.json  # V5 deployment state
├── server.py           # Flask web dashboard
├── dashboard.html      # Dashboard UI
├── walk_forward.py     # Walk-forward validation
├── indicators.py       # Technical indicators
├── signals.py          # Signal scoring (legacy)
├── data_cache.py       # Disk cache for historical data
├── config.py           # Configuration
├── download_batch.py   # Batch data download
├── .env                # API keys
└── requirements.txt    # Dependencies
```

## Historical Versions

| Version | Approach | Status |
|---------|----------|--------|
| v1 | 6-factor stock scoring | Deprecated |
| v2 | Multi-factor momentum + quality | Deprecated |
| v3 | Pure trend-following | Deprecated |
| v4 | Single-factor momentum | Deprecated |
| **v5** | **Sector ETF rotation** | **Production** |

## Risk Disclaimer

1. **Paper Trading Only** — defaults to paper, change APCA_API_BASE_URL for live
2. **Not investment advice** — this is a technical demo
3. **Market risk** — past performance != future results
