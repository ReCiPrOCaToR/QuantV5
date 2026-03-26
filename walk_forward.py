"""
walk_forward.py — Walk-Forward Validation for V2 Strategy
Tests if parameters are robust or overfitted.

Method:
  Split data into rolling windows. On each window:
    1. Train: Grid search to find best parameters
    2. Test:  Apply best params to next period (out-of-sample)
  If test results are consistent -> strategy is robust
  If test results vary wildly -> parameters are overfitted
"""
import logging
import itertools
from datetime import datetime

import pandas as pd
import numpy as np
from colorama import init as colorama_init, Fore, Style
from tabulate import tabulate

from config import Config, StrategyParams
from indicators import compute_all_indicators
from backtest_v4 import BacktestV4
from backtest_v2 import BacktestV2

colorama_init(autoreset=True)
logger = logging.getLogger("walk_forward")


def generate_windows(trading_days: list, train_days: int = 90, test_days: int = 45, step_days: int = 30):
    """Generate rolling train/test windows with configurable step"""
    windows = []
    # Convert step_days to approximate trading days (step_days / 5 * 7 calendar)
    step_idx = max(1, int(step_days * 5 / 7))  # approximate trading days
    i = 0
    while i + train_days + test_days <= len(trading_days):
        train_start = trading_days[i]
        train_end = trading_days[i + train_days - 1]
        test_start = trading_days[i + train_days]
        test_end_idx = min(i + train_days + test_days - 1, len(trading_days) - 1)
        test_end = trading_days[test_end_idx]
        windows.append({
            "train": (train_start, train_end),
            "test": (test_start, test_end),
            "train_days": train_days,
            "test_days": test_days,
        })
        i += step_idx
    return windows


PARAM_GRID = {
    "rebalance_interval": [2, 3, 5],
    "stop_loss": [1.2, 1.5, 2.5],
    "max_positions": [4],
}


def run_single_backtest(stock_data: dict, spy_df: pd.DataFrame,
                        trading_days: list, start_date, end_date,
                        params: dict) -> dict:
    """Run a single backtest with given params on a date range"""
    # Temporarily set config
    Config.apply_strategy(StrategyParams(
        rebalance_interval=params["rebalance_interval"],
        stop_loss=params["stop_loss"],
        max_positions=params["max_positions"],
    ))

    # Filter trading days to range
    window_days = [d for d in trading_days if d >= start_date and d <= end_date]
    if len(window_days) < 20:
        return {"total_pct": -999, "error": "too few days"}

    # We reuse the BacktestV2 engine but need to feed it the right data
    # For walk-forward, we run the simulation manually on the window
    engine = BacktestV4(initial_capital=100000)

    # Cut data to window + warmup
    # Use smaller warmup for windowed runs (indicators need 20+ days)
    warmup = 30
    window_start_idx = 0
    for i, d in enumerate(trading_days):
        if d >= start_date:
            window_start_idx = max(0, i - warmup)
            break

    cut_stock_data = {}
    for sym, df in stock_data.items():
        cut = df[(df.index >= trading_days[window_start_idx]) & (df.index <= end_date)]
        if len(cut) > warmup:
            cut_stock_data[sym] = cut

    cut_spy = spy_df[(spy_df.index >= trading_days[window_start_idx]) & (spy_df.index <= end_date)]

    if not cut_stock_data:
        return {"total_pct": -999, "error": "no data"}

    # Run engine with cut data
    universe = list(cut_stock_data.keys())
    results = engine.run_windowed(cut_stock_data, cut_spy, start_date, end_date, warmup_days=warmup)

    return results


class WalkForwardValidator:
    """Walk-Forward Validation engine"""

    def __init__(self, train_days=90, test_days=45):
        self.train_days = train_days
        self.test_days = test_days
        self.results = []

    def run(self, universe: list, lookback_days=730):
        """Run full walk-forward validation"""

        print(Fore.CYAN + "\n" + "="*60)
        print("  [WALK-FORWARD] Validation")
        print("="*60 + Style.RESET_ALL)

        # Load data via yfinance (no Alpaca needed)
        print(f"\nLoading data ({lookback_days}d)...")
        engine = BacktestV4(initial_capital=100000)
        engine.load_batch(days=730)
        spy_df = engine.load_data("SPY", days=lookback_days)
        stock_data = {}
        for sym in universe:
            df = engine.load_data(sym, days=lookback_days)
            if df is not None and len(df) > self.train_days:
                stock_data[sym] = df
                print(f"  {sym}: {len(df)} rows")

        if not stock_data:
            return {"error": "No data loaded"}

        # Find common trading days
        all_dates = sorted(set(d for df in stock_data.values() for d in df.index))
        warmup = 60
        trading_days = all_dates[warmup:]

        # Auto-scale train/test to fit available data
        total_days = len(trading_days)
        train_days = self.train_days
        test_days = self.test_days

        if total_days < train_days + test_days:
            test_days = max(20, int(total_days * 0.3))
            train_days = total_days - test_days
            print(Fore.YELLOW + f"  [AUTO-SCALE] {total_days}d available, adjusting windows: "
                  f"train={train_days}d, test={test_days}d" + Style.RESET_ALL)

        if total_days < train_days + test_days:
            return {"error": f"Not enough data: {total_days} days"}

        # Generate windows
        windows = generate_windows(trading_days, train_days, test_days)
        print(f"\n{len(windows)} windows to evaluate:")
        if not windows:
            return {"error": f"Not enough data ({total_days}d) for walk-forward"}
        for i, w in enumerate(windows):
            print(f"  Window {i+1}: Train {w['train'][0].strftime('%Y-%m-%d')} -> {w['train'][1].strftime('%Y-%m-%d')} "
                  f"| Test {w['test'][0].strftime('%Y-%m-%d')} -> {w['test'][1].strftime('%Y-%m-%d')}")

        # Run walk-forward
        wf_results = []
        # Use smaller param grid for shorter data periods
        if total_days < 100:
            param_grid = {
                "rebalance_interval": [2, 3, 5],
                "stop_loss": [1.5, 1.8, 2.5],
                "max_positions": [3, 4],
            }
        else:
            param_grid = PARAM_GRID

        for i, w in enumerate(windows):
            print(Fore.YELLOW + f"\n--- Window {i+1}/{len(windows)} ---" + Style.RESET_ALL)

            # TRAIN: Grid search - use top-N median for robustness
            print("  Training: grid searching...")
            param_scores = []  # (score, params) pairs

            param_combos = list(itertools.product(
                param_grid["rebalance_interval"],
                param_grid["stop_loss"],
                param_grid["max_positions"],
            ))

            for ri, sl, mp in param_combos:
                params = {"rebalance_interval": ri, "stop_loss": sl, "max_positions": mp}
                try:
                    train_result = run_single_backtest(
                        stock_data, spy_df, trading_days,
                        w["train"][0], w["train"][1], params
                    )
                    score = train_result.get("total_pct", -999)
                    param_scores.append((score, params))
                except Exception as e:
                    print(f"    [ERROR] Param {params}: {e}")
                    import traceback; traceback.print_exc()

            if not param_scores:
                print(f"    No valid params found, skipping")
                continue

            # Sort by score descending, pick median of top 3 for robustness
            param_scores.sort(key=lambda x: x[0], reverse=True)
            top_n = param_scores[:min(3, len(param_scores))]
            # Use the params that appear most frequently in top-3, or median if all different
            best_score = top_n[0][0]
            best_params = top_n[len(top_n)//2][1]  # Median of top-N (reduces overfitting)

            print(f"    Best train: {best_score:.2f}% (top-3: {[f'{s:.2f}%' for s,_ in top_n]}) | Params: {best_params}")

            # TEST: Apply best params
            print("  Testing on out-of-sample...")
            try:
                test_result = run_single_backtest(
                    stock_data, spy_df, trading_days,
                    w["test"][0], w["test"][1], best_params
                )
                test_return = test_result.get("total_pct", -999)
                print(Fore.GREEN + f"    Test result: {test_return:.2f}%" + Style.RESET_ALL)

                wf_results.append({
                    "window": i + 1,
                    "train_start": w["train"][0].strftime("%Y-%m-%d"),
                    "train_end": w["train"][1].strftime("%Y-%m-%d"),
                    "test_start": w["test"][0].strftime("%Y-%m-%d"),
                    "test_end": w["test"][1].strftime("%Y-%m-%d"),
                    "train_return": best_score,
                    "test_return": test_return,
                    "params": best_params,
                })
            except Exception as e:
                print(f"    Test error: {e}")

        # Summary
        if not wf_results:
            return {"error": "No valid windows"}

        print(Fore.CYAN + "\n" + "="*60)
        print("  [WALK-FORWARD] RESULTS")
        print("="*60 + Style.RESET_ALL)

        # Results table
        table_data = []
        for r in wf_results:
            table_data.append([
                r["window"],
                f"{r['train_start']} -> {r['train_end']}",
                f"{r['test_start']} -> {r['test_end']}",
                f"{r['train_return']:+.2f}%",
                f"{r['test_return']:+.2f}%",
                f"R{r['params']['rebalance_interval']}/S{r['params']['stop_loss']}/P{r['params']['max_positions']}",
            ])

        print(tabulate(table_data,
                       headers=["#", "Train Period", "Test Period", "Train %", "Test %", "Params"],
                       tablefmt="grid"))

        # Statistics
        test_returns = [r["test_return"] for r in wf_results]
        train_returns = [r["train_return"] for r in wf_results]

        print(f"\n{'='*40}")
        print(f"  STATISTICS")
        print(f"{'='*40}")
        print(f"  Train avg:  {np.mean(train_returns):+.2f}%  |  Test avg:  {np.mean(test_returns):+.2f}%")
        print(f"  Train std:  {np.std(train_returns):.2f}%    |  Test std:  {np.std(test_returns):.2f}%")
        print(f"  Train min:  {min(train_returns):+.2f}%  |  Test min:  {min(test_returns):+.2f}%")
        print(f"  Train max:  {max(train_returns):+.2f}%  |  Test max:  {max(test_returns):+.2f}%")
        print(f"  Test > 0:   {sum(1 for r in test_returns if r > 0)}/{len(test_returns)} windows")
        print(f"  Degradation: {(np.mean(train_returns) - np.mean(test_returns)):.2f}%")

        # Verdict
        print(f"\n{'='*40}")
        avg_degradation = np.mean(train_returns) - np.mean(test_returns)
        positive_tests = sum(1 for r in test_returns if r > 0)
        total_tests = len(test_returns)

        if avg_degradation < 5 and positive_tests >= total_tests * 0.6:
            verdict = "[OK] ROBUST - Strategy is likely NOT overfitted"
            color = Fore.GREEN
        elif avg_degradation < 10 and positive_tests >= total_tests * 0.4:
            verdict = "[WARN] MODERATE - Some overfitting risk, proceed with caution"
            color = Fore.YELLOW
        else:
            verdict = "[FAIL] OVERFITTED - Strategy is likely overfitted to historical data"
            color = Fore.RED

        print(color + f"  VERDICT: {verdict}" + Style.RESET_ALL)
        print(f"{'='*40}")

        return {
            "windows": wf_results,
            "test_avg": round(np.mean(test_returns), 2),
            "test_std": round(np.std(test_returns), 2),
            "train_avg": round(np.mean(train_returns), 2),
            "degradation": round(avg_degradation, 2),
            "positive_tests": positive_tests,
            "total_tests": total_tests,
            "verdict": verdict,
        }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
    Config.apply_strategy(StrategyParams.fast())
    validator = WalkForwardValidator(train_days=120, test_days=60)
    validator.run(Config.UNIVERSE, lookback_days=730)
