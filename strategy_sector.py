"""
Sector ETF Rotation Strategy v5
- Universe: 9 sector ETFs + SPY/QQQ/IWM for diversification
- Signal: 60-day return relative to SPY (relative strength)
- Ranking: Top 3 by relative strength (above SPY RS)
- Rebalance: Every 20 trading days
- Trend filter: SPY < SMA200 → 50% cash
- Stop-loss: Individual ETF drops 10% below entry (trailing)
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Tuple


SECTOR_ETFS = ['XLK', 'XLE', 'XLF', 'XLV', 'XLU', 'XLP', 'XLI', 'XLRE', 'XBI']

@dataclass
class Trade:
    symbol: str
    entry_date: datetime
    entry_price: float
    qty: int
    stop_price: float
    highest_price: float = 0.0
    exit_date: datetime = None
    exit_price: float = 0.0
    exit_reason: str = ""

    def close(self, date, price, reason):
        self.exit_date = date
        self.exit_price = price
        self.exit_reason = reason

    @property
    def pnl(self):
        if not self.exit_price:
            return 0
        return (self.exit_price - self.entry_price) * self.qty

    @property
    def pnl_pct(self):
        if not self.entry_price or not self.exit_price:
            return 0
        return (self.exit_price / self.entry_price - 1) * 100

    @property
    def holding_days(self):
        if not self.exit_date:
            return 0
        return (self.exit_date - self.entry_date).days


def compute_relative_strength(etf_close: pd.Series, spy_close: pd.Series, lookback: int = 60) -> float:
    """RS = ETF 60d return - SPY 60d return"""
    if len(etf_close) < lookback or len(spy_close) < lookback:
        return -999
    etf_ret = etf_close.iloc[-1] / etf_close.iloc[-lookback] - 1
    spy_ret = spy_close.iloc[-1] / spy_close.iloc[-lookback] - 1
    return etf_ret - spy_ret


class SectorRotation:
    def __init__(self, initial_capital=100000, top_n=2, lookback=30,
                 rebalance_days=15, trailing_stop_pct=0.10, cash_pct_bear=0.50):
        self.initial_capital = initial_capital
        self.top_n = top_n
        self.lookback = lookback
        self.rebalance_days = rebalance_days
        self.trailing_stop_pct = trailing_stop_pct
        self.cash_pct_bear = cash_pct_bear  # fraction of capital kept in cash during bear
        self.capital = initial_capital
        self.positions = {}
        self.closed_trades = []

    def run(self, etf_data: dict, spy_data: pd.DataFrame):
        """Run backtest."""
        # All dates
        all_dates = sorted(set(d for df in etf_data.values() for d in df.index))
        spy_dates = sorted(spy_data.index)

        # Warmup: need lookback + SMA200 days
        warmup = max(self.lookback, 200)
        trading_days = [d for d in all_dates if d >= spy_dates[warmup]]
        if not trading_days:
            return {"error": "Not enough data"}

        self.capital = self.initial_capital
        self.positions = {}
        self.closed_trades = []
        equity_curve = []
        last_rebalance_idx = -1

        for day_idx, current_date in enumerate(trading_days):
            spy_today = spy_data.loc[:current_date]
            if len(spy_today) < 200:
                continue

            spy_close = spy_today['close'].squeeze()
            spy_sma200 = spy_close.tail(200).mean()
            spy_price = spy_close.iloc[-1]
            bull_trend = spy_price > spy_sma200

            # Trailing stops
            to_close = []
            for sym, trade in self.positions.items():
                if sym not in etf_data:
                    continue
                df = etf_data[sym]
                if current_date not in df.index:
                    continue
                price = df.loc[current_date, 'close']
                if isinstance(price, pd.Series):
                    price = price.iloc[0]
                if price > trade.highest_price:
                    trade.highest_price = price
                if trade.highest_price > 0:
                    dd = (price - trade.highest_price) / trade.highest_price
                    if dd < -self.trailing_stop_pct:
                        to_close.append((sym, price, "trailing_stop"))

            for sym, price, reason in to_close:
                if sym in self.positions:
                    trade = self.positions[sym]
                    trade.close(current_date, price, reason)
                    self.capital += price * trade.qty
                    self.closed_trades.append(trade)
                    del self.positions[sym]

            # Rebalance every N days
            if day_idx - last_rebalance_idx >= self.rebalance_days or (day_idx == 0 and last_rebalance_idx == -1):
                last_rebalance_idx = day_idx

                # Compute RS for all ETFs
                rankings = []
                for sym, df in etf_data.items():
                    if sym == 'SPY':
                        continue
                    hist = df.loc[:current_date]
                    if len(hist) < self.lookback:
                        continue
                    rs = compute_relative_strength(hist['close'], spy_today['close'], self.lookback)
                    price = hist['close'].iloc[-1]
                    if isinstance(price, pd.Series):
                        price = price.iloc[0]
                    rankings.append((sym, rs, price))

                rankings.sort(key=lambda x: x[1], reverse=True)
                top_etfs = [r for r in rankings if r[1] > 0][:self.top_n]

                # Capital allocation
                total_equity = self.capital
                for sym, trade in self.positions.items():
                    if sym in etf_data and current_date in etf_data[sym].index:
                        price = etf_data[sym].loc[current_date, 'close']
                        if isinstance(price, pd.Series):
                            price = price.iloc[0]
                        total_equity += price * trade.qty

                target_equity = total_equity * (1 - self.cash_pct_bear) if not bull_trend else total_equity
                per_position = target_equity / max(len(top_etfs), 1)

                # Sells: remove positions not in top
                top_symbols = {r[0] for r in top_etfs}
                sell_symbols = set(self.positions.keys()) - top_symbols
                for sym in sell_symbols:
                    if sym in etf_data and current_date in etf_data[sym].index:
                        price = etf_data[sym].loc[current_date, 'close']
                        if isinstance(price, pd.Series):
                            price = price.iloc[0]
                        trade = self.positions[sym]
                        trade.close(current_date, price, "rebalance_sell")
                        self.capital += price * trade.qty
                        self.closed_trades.append(trade)
                        del self.positions[sym]

                # Buys: add missing top positions
                for sym, rs, price in top_etfs:
                    if sym in self.positions:
                        continue
                    qty = int(per_position / price) if price > 0 else 0
                    if qty > 0 and self.capital >= price * qty:
                        trade = Trade(sym, current_date, price, qty, price * (1 - self.trailing_stop_pct))
                        self.positions[sym] = trade
                        self.capital -= price * qty

            # Record equity
            equity = self.capital
            for sym, trade in self.positions.items():
                if sym in etf_data and current_date in etf_data[sym].index:
                    price = etf_data[sym].loc[current_date, 'close']
                    if isinstance(price, pd.Series):
                        price = price.iloc[0]
                    equity += price * trade.qty
            equity_curve.append({"date": current_date.strftime("%Y-%m-%d"), "equity": round(equity, 2)})

        # Final
        final_equity = self.capital
        for sym, trade in self.positions.items():
            if sym in etf_data:
                final_equity += trade.qty * etf_data[sym]['close'].iloc[-1]

        return self._build_result(equity_curve, final_equity)

    def run_windowed(self, etf_data, spy_data, start_date, end_date, warmup_days=60):
        """Run for a specific window (walk-forward)."""
        all_dates = sorted(set(d for df in etf_data.values() for d in df.index))
        trading_days = [d for d in all_dates if d >= start_date and d <= end_date]
        if len(trading_days) < 20:
            return {"total_pct": -999, "error": "too few days"}

        self.capital = self.initial_capital
        self.positions = {}
        self.closed_trades = []

        for day_idx, current_date in enumerate(trading_days):
            spy_today = spy_data.loc[:current_date]
            if len(spy_today) < 200:
                continue
            spy_close = spy_today['close'].squeeze()
            spy_sma200 = spy_close.tail(200).mean()
            spy_price = spy_close.iloc[-1]
            bull_trend = spy_price > spy_sma200

            # Trailing stops
            to_close = []
            for sym, trade in self.positions.items():
                if sym in etf_data and current_date in etf_data[sym].index:
                    price = etf_data[sym].loc[current_date, 'close']
                    if isinstance(price, pd.Series):
                        price = price.iloc[0]
                    if price > trade.highest_price:
                        trade.highest_price = price
                    if trade.highest_price > 0:
                        dd = (price - trade.highest_price) / trade.highest_price
                        if dd < -self.trailing_stop_pct:
                            to_close.append((sym, price, "trailing_stop"))
            for sym, price, reason in to_close:
                if sym in self.positions:
                    trade = self.positions[sym]
                    trade.close(current_date, price, reason)
                    self.capital += price * trade.qty
                    self.closed_trades.append(trade)
                    del self.positions[sym]

            if day_idx % self.rebalance_days == 0:
                rankings = []
                for sym, df in etf_data.items():
                    if sym == 'SPY':
                        continue
                    hist = df.loc[:current_date]
                    if len(hist) < self.lookback:
                        continue
                    rs = compute_relative_strength(hist['close'], spy_today['close'], self.lookback)
                    price = hist['close'].iloc[-1]
                    if isinstance(price, pd.Series):
                        price = price.iloc[0]
                    rankings.append((sym, rs, price))
                rankings.sort(key=lambda x: x[1], reverse=True)
                top_etfs = [r for r in rankings if r[1] > 0][:self.top_n]

                total_equity = self.capital
                for sym, trade in self.positions.items():
                    if sym in etf_data and current_date in etf_data[sym].index:
                        price = etf_data[sym].loc[current_date, 'close']
                        if isinstance(price, pd.Series):
                            price = price.iloc[0]
                        total_equity += price * trade.qty
                target_equity = total_equity * (1 - self.cash_pct_bear) if not bull_trend else total_equity
                per_position = target_equity / max(len(top_etfs), 1)

                top_symbols = {r[0] for r in top_etfs}
                sell_symbols = set(self.positions.keys()) - top_symbols
                for sym in sell_symbols:
                    if sym in etf_data and current_date in etf_data[sym].index:
                        price = etf_data[sym].loc[current_date, 'close']
                        if isinstance(price, pd.Series):
                            price = price.iloc[0]
                        trade = self.positions[sym]
                        trade.close(current_date, price, "rebalance_sell")
                        self.capital += price * trade.qty
                        self.closed_trades.append(trade)
                        del self.positions[sym]

                for sym, rs, price in top_etfs:
                    if sym in self.positions:
                        continue
                    qty = int(per_position / price) if price > 0 else 0
                    if qty > 0 and self.capital >= price * qty:
                        trade = Trade(sym, current_date, price, qty, price * (1 - self.trailing_stop_pct))
                        self.positions[sym] = trade
                        self.capital -= price * qty

        final_equity = self.capital
        for sym, trade in self.positions.items():
            if sym in etf_data:
                final_equity += trade.qty * etf_data[sym]['close'].iloc[-1]
        return {"total_pct": round((final_equity / self.initial_capital - 1) * 100, 2),
                "final_equity": round(final_equity, 2)}

    def _build_result(self, equity_curve, final_equity):
        returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]['equity']
            curr = equity_curve[i]['equity']
            if prev > 0:
                returns.append((curr - prev) / prev)

        equity_series = [e['equity'] for e in equity_curve]
        max_eq = equity_series[0]
        max_dd = 0
        max_dd_idx = 0
        for i, eq in enumerate(equity_series):
            if eq > max_eq:
                max_eq = eq
            dd = (max_eq - eq) / max_eq if max_eq > 0 else 0
            if dd > max_dd:
                max_dd = dd
                max_dd_idx = i

        total_return = (final_equity / self.initial_capital - 1) * 100
        daily_ret = np.array(returns)
        sharpe = (daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0

        wins = [t for t in self.closed_trades if t.pnl > 0]
        losses = [t for t in self.closed_trades if t.pnl < 0]
        total = len(self.closed_trades)

        gross_profit = sum(t.pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 1
        pf = gross_profit / gross_loss if gross_loss > 0 else 0
        avg_hold = np.mean([t.holding_days for t in self.closed_trades]) if self.closed_trades else 0

        return {
            "total_pct": round(total_return, 2),
            "final_equity": round(final_equity, 2),
            "returns": {"final": round(final_equity, 2), "initial": self.initial_capital},
            "risk": {
                "sharpe": round(sharpe, 3),
                "max_dd_pct": round(max_dd * 100, 2),
                "max_dd_date": equity_curve[max_dd_idx]['date'] if equity_curve else "",
                "avg_vol": round(np.std(daily_ret) * np.sqrt(252) * 100, 2)
            },
            "trades": {
                "total": total,
                "wins": len(wins),
                "losses": len(losses),
                "win_rate_pct": round(len(wins) / total * 100, 1) if total > 0 else 0,
                "pf": round(pf, 2),
                "avg_hold": round(avg_hold, 1),
                "expectancy": round(np.mean([t.pnl for t in self.closed_trades]), 2) if self.closed_trades else 0
            },
            "all_trades": [{
                "symbol": t.symbol,
                "entry_date": t.entry_date.strftime("%Y-%m-%d"),
                "exit_date": t.exit_date.strftime("%Y-%m-%d") if t.exit_date else "",
                "entry_price": round(t.entry_price, 2),
                "exit_price": round(t.exit_price, 2),
                "qty": t.qty,
                "pnl": round(t.pnl, 2),
                "pnl_pct": round(t.pnl_pct, 2),
                "holding_days": t.holding_days,
                "exit_reason": t.exit_reason
            } for t in self.closed_trades],
            "equity_curve": {
                "labels": [e['date'] for e in equity_curve],
                "values": [e['equity'] for e in equity_curve]
            }
        }
