"""
live_trader_v5.py - V5 Sector ETF Rotation live trading engine
Uses relative strength + trend filter for sector rotation
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from colorama import init as colorama_init, Fore, Style
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import Config

colorama_init(autoreset=True)
logger = logging.getLogger("live_trader_v5")

SECTOR_ETFS = ['XLK', 'XLE', 'XLF', 'XLV', 'XLU', 'XLP', 'XLI', 'XLRE', 'XBI']
STATE_FILE = Path(__file__).parent / "live_state_v5.json"


class LiveTraderV5:
    def __init__(self, capital=100000, top_n=2, lookback=30, rebalance_days=15, trailing_stop_pct=0.10):
        self.capital = capital
        self.top_n = top_n
        self.lookback = lookback
        self.rebalance_days = rebalance_days
        self.trailing_stop_pct = trailing_stop_pct

        self.trading_client = TradingClient(Config.API_KEY, Config.API_SECRET, paper=True)
        self.data_client = StockHistoricalDataClient(Config.API_KEY, Config.API_SECRET)

    def get_etf_data(self, symbol, days=300):
        """Fetch daily bars from Alpaca"""
        end = datetime.now()
        start = end - timedelta(days=days)
        try:
            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=start.strftime('%Y-%m-%d'),
                end=end.strftime('%Y-%m-%d')
            )
            resp = self.data_client.get_stock_bars(req)
            bars = resp[symbol] if hasattr(resp, '__getitem__') else list(resp)
            if not bars:
                return None
            df = pd.DataFrame([{
                'open': b.open, 'high': b.high, 'low': b.low,
                'close': b.close, 'volume': b.volume
            } for b in bars])
            df.index = pd.to_datetime([b.timestamp for b in bars]).tz_localize(None)
            return df
        except Exception as e:
            print(f"  {symbol}: ERROR {e}")
            return None

    def get_positions(self):
        """Get current Alpaca positions"""
        try:
            positions = self.trading_client.get_all_positions()
            result = {}
            for p in positions:
                result[p.symbol] = {
                    'qty': int(p.qty),
                    'market_value': float(p.market_value),
                    'current_price': float(p.current_price),
                    'unrealized_pl': float(p.unrealized_pl or 0),
                    'unrealized_plpc': float(p.unrealized_plpc or 0) * 100
                }
            return result
        except Exception as e:
            print(f"Error getting positions: {e}")
            return {}

    def get_account(self):
        """Get account info"""
        try:
            account = self.trading_client.get_account()
            return {
                'equity': float(account.equity),
                'cash': float(account.cash),
                'buying_power': float(account.buying_power),
                'portfolio_value': float(account.portfolio_value)
            }
        except Exception as e:
            print(f"Error getting account: {e}")
            return {}

    def compute_relative_strength(self, etf_close, spy_close, lookback=30):
        """RS = ETF return - SPY return"""
        if len(etf_close) < lookback or len(spy_close) < lookback:
            return -999
        etf_ret = etf_close.iloc[-1] / etf_close.iloc[-lookback] - 1
        spy_ret = spy_close.iloc[-1] / spy_close.iloc[-lookback] - 1
        return etf_ret - spy_ret

    def scan(self):
        """Run scan and return rankings + regime info"""
        print(Fore.CYAN + "\n" + "=" * 60)
        print("  [V5 SECTOR ROTATION] Live Scan")
        print("=" * 60 + Style.RESET_ALL)
        print(f"\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Get SPY data
        spy_df = self.get_etf_data('SPY', days=300)
        if spy_df is None or len(spy_df) < 200:
            print(Fore.RED + "Cannot load SPY data!" + Style.RESET_ALL)
            return {"error": "Cannot load SPY data"}

        spy_close = spy_df['close']
        spy_price = spy_close.iloc[-1]
        spy_sma200 = spy_close.tail(200).mean()
        bull_trend = bool(spy_price > spy_sma200)

        print(f"\nSPY: ${spy_price:.2f} vs SMA200 ${spy_sma200:.2f} -> {'BULL' if bull_trend else 'BEAR'}")

        # Get ETF data
        etf_data = {}
        for sym in SECTOR_ETFS:
            df = self.get_etf_data(sym, days=300)
            if df is not None and len(df) >= self.lookback:
                etf_data[sym] = df
            else:
                print(f"  {sym}: insufficient data")

        # Compute RS
        rankings = []
        for sym, df in etf_data.items():
            rs = self.compute_relative_strength(df['close'], spy_close, self.lookback)
            price = df['close'].iloc[-1]
            momentum_60 = (price / df['close'].iloc[-60] - 1) * 100 if len(df) >= 60 else 0
            rankings.append({'symbol': sym, 'rs': round(rs, 4), 'price': round(price, 2), 'momentum': round(momentum_60, 1)})

        rankings.sort(key=lambda x: x['rs'], reverse=True)
        for i, r in enumerate(rankings):
            marker = Fore.GREEN + "  -> BUY" + Style.RESET_ALL if i < self.top_n and r['rs'] > 0 else ""
            print(f"  {i+1}. {r['symbol']:4s} RS={r['rs']:+.4f} Price=${r['price']:.2f} Mom60={r['momentum']:+.1f}%{marker}")

        top_etfs = [r for r in rankings if r['rs'] > 0][:self.top_n]

        return {
            'rankings': rankings,
            'top': [r['symbol'] for r in top_etfs],
            'regime': 'BULL' if bull_trend else 'BEAR',
            'spy_price': round(spy_price, 2),
            'spy_sma200': round(spy_sma200, 2)
        }

    def execute_trades(self):
        """Execute trading decisions"""
        print(Fore.CYAN + "\n" + "=" * 60)
        print("  [V5 SECTOR ROTATION] Execute Trades")
        print("=" * 60 + Style.RESET_ALL)

        scan_result = self.scan()
        if 'error' in scan_result:
            return scan_result

        top_etfs = scan_result['top']
        bull_trend = scan_result['regime'] == 'BULL'
        account = self.get_account()
        positions = self.get_positions()

        print(f"\nAccount: ${account.get('equity', 0):.2f} equity, ${account.get('cash', 0):.2f} cash")
        print(f"Target positions: {top_etfs} (Bull={bull_trend})")

        orders = []

        # Sells: positions not in top
        target_symbols = set(top_etfs)
        for sym in list(positions.keys()):
            if sym not in target_symbols and sym in SECTOR_ETFS:
                qty = positions[sym]['qty']
                if qty > 0:
                    print(Fore.RED + f"  SELL {sym} x{qty}" + Style.RESET_ALL)
                    try:
                        order = self.trading_client.submit_order(
                            MarketOrderRequest(symbol=sym, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
                        )
                        orders.append({'symbol': sym, 'action': 'SELL', 'qty': qty, 'status': 'submitted'})
                    except Exception as e:
                        print(f"    Error: {e}")
                        orders.append({'symbol': sym, 'action': 'SELL', 'qty': qty, 'status': f'error: {e}'})

        # Buys: missing positions in top
        total_equity = account.get('equity', 100000)
        if bull_trend:
            per_position = total_equity / self.top_n
        else:
            per_position = total_equity * 0.50 / self.top_n

        for sym in top_etfs:
            if sym not in positions:
                # Find price from scan rankings
                price = next((r['price'] for r in scan_result['rankings'] if r['symbol'] == sym), 0)
                if price <= 0:
                    continue
                qty = int(per_position / price)
                if qty > 0:
                    print(Fore.GREEN + f"  BUY {sym} x{qty} @ ${price:.2f}" + Style.RESET_ALL)
                    try:
                        order = self.trading_client.submit_order(
                            MarketOrderRequest(symbol=sym, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
                        )
                        orders.append({'symbol': sym, 'action': 'BUY', 'qty': qty, 'price': price, 'status': 'submitted'})
                    except Exception as e:
                        print(f"    Error: {e}")
                        orders.append({'symbol': sym, 'action': 'BUY', 'qty': qty, 'price': price, 'status': f'error: {e}'})

        # Save state
        state = {
            'last_scan': datetime.now().isoformat(),
            'top_etfs': top_etfs,
            'regime': scan_result['regime'],
            'orders': orders,
            'positions': {k: v for k, v in positions.items() if k in SECTOR_ETFS}
        }
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2, default=str)

        print(f"\nOrders: {len(orders)} submitted")
        return state

    def check_trailing_stops(self):
        """Check and exit positions that hit trailing stops"""
        positions = self.get_positions()
        orders = []

        for sym, pos in positions.items():
            if sym not in SECTOR_ETFS:
                continue
            df = self.get_etf_data(sym, days=300)
            if df is None or len(df) < 2:
                continue
            current_price = float(df['close'].iloc[-1])
            high_price = float(df['close'].tail(30).max())
            dd = (current_price - high_price) / high_price

            if dd < -self.trailing_stop_pct:
                qty = pos['qty']
                print(Fore.RED + f"  TRAILING STOP {sym}: {dd*100:.1f}% drawdown, selling x{qty}" + Style.RESET_ALL)
                try:
                    order = self.trading_client.submit_order(
                        MarketOrderRequest(symbol=sym, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
                    )
                    orders.append({'symbol': sym, 'action': 'STOP_SELL', 'qty': qty, 'status': 'submitted'})
                except Exception as e:
                    print(f"    Error: {e}")

        return orders


def main():
    trader = LiveTraderV5()
    state = trader.execute_trades()
    print(json.dumps(state, indent=2, default=str))


if __name__ == '__main__':
    main()
