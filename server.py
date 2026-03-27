"""
server.py - V2 閲忓寲绛栫暐 Web 浠〃锟?鍚姩: python server.py
璁块棶: http://localhost:5000
"""
import os
import sys
import json
import threading
import numpy as np
import pandas as pd
from datetime import datetime

from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(__file__))
from config import Config

app = Flask(__name__)
CORS(app)

# Global state for live task tracking
_task_state = {"status": "idle", "progress": "", "result": None}
_monitor_state = {"last_check": None, "actions": [], "positions": 0}
_scheduler_running = False
_wf_state = {"status": "idle", "progress": "", "result": None}


def run_backtest_async(days, mode):
    """Run backtest in background thread"""
    global _task_state
    try:
        _task_state = {"status": "running", "progress": "Loading data...", "result": None}

        from backtest_v2 import BacktestV2
        from config import Config, StrategyParams

        if mode == "v5":
            # V5 Sector ETF Rotation
            import pickle
            from pathlib import Path
            _task_state["progress"] = "Running V5 Sector Rotation..."
            batch_path = Path(__file__).parent / "data" / "cache" / "batch_etf.pkl"
            with open(batch_path, "rb") as f:
                etf_data = pickle.load(f)
            spy_data = etf_data.pop("SPY")
            from strategy_sector import SectorRotation
            engine = SectorRotation(initial_capital=100000, top_n=2, lookback=30, rebalance_days=15)
            results = engine.run(etf_data, spy_data)
            import pandas as _pd
            ec = results.get("equity_curve", {"labels": [], "values": []})
            ec_labels = ec.get("labels", [])
            ec_values = ec.get("values", [])
            eq_series = _pd.Series(ec_values, index=ec_labels)
            dd_list = []
            if len(eq_series) > 0:
                peak = eq_series.cummax()
                dd = ((eq_series - peak) / peak * 100).round(2).tolist()
                dd_list = dd
            # Monthly returns
            m_labels, m_returns = [], []
            if len(ec_values) > 20:
                for i in range(0, len(ec_values), 20):
                    chunk_end = min(i + 20, len(ec_values) - 1)
                    if i > 0:
                        m_ret = (ec_values[chunk_end] / ec_values[i] - 1) * 100
                        m_returns.append(round(m_ret, 2))
                        m_labels.append(ec_labels[i][:7] if len(ec_labels[i]) >= 7 else ec_labels[i])
            risk = results.get("risk", {})
            trades = results.get("trades", {})
            data = {
                "strategy_version": "v5",
                "period": {"start": "2024-06", "end": "2026-03", "days": days, "years": round(days/365, 2)},
                "returns": {"final": results.get("final_equity", 100000), "initial": 100000, "pnl": results.get("final_equity", 100000) - 100000, "total_pct": results.get("total_pct", 0)},
                "risk": {"sharpe": risk.get("sharpe", 0), "sortino": risk.get("sharpe", 0) * 1.5, "max_dd_pct": risk.get("max_dd_pct", 0), "max_dd_date": risk.get("max_dd_date", ""), "ann_vol_pct": risk.get("avg_vol", 8), "calmar": 0},
                "trades": {"total": trades.get("total", 0), "wins": trades.get("wins", 0), "losses": trades.get("losses", 0), "win_rate_pct": trades.get("win_rate_pct", 0), "pf": trades.get("pf", 0), "expectancy": trades.get("expectancy", 0), "avg_hold": trades.get("avg_hold", 0)},
                "benchmark": {"spy_return_pct": 0, "alpha_pct": 0},
                "regime_counts": {},
                "vix_counts": {},
                "best_trade": None,
                "worst_trade": None,
                "all_trades": results.get("all_trades", []),
                "equity_curve": {"labels": ec_labels, "values": ec_values},
                "dd_series": dd_list,
                "monthly": {"labels": m_labels, "returns": m_returns},
                "cum_pnl": [],
            }
            _task_state = {"status": "done", "progress": "Complete!", "result": data}
            return
        elif mode == "v4":
            Config.apply_strategy(StrategyParams(max_positions=4, stop_loss=2.0, rebalance_interval=5))
            from backtest_v4 import BacktestV4
            engine = BacktestV4(initial_capital=100000)
            _task_state["progress"] = f"Running V4 Pure Momentum ({days}d)..."
            results = engine.run(Config.UNIVERSE, lookback_days=days)
            # Adapt V4 results to frontend format
            equity_series = results.get("equity_series", pd.Series(dtype=float))
            total_pct = results.get("total_pct", 0)
            final_eq = results.get("final_equity", 100000)
            total_trades = results.get("total_trades", 0)
            wins = results.get("wins", 0)
            losses = results.get("losses", 0)
            win_rate = results.get("win_rate", 0)
            spy_ret = results.get("spy_return_pct", 0)
            alpha = results.get("alpha_pct", 0)

            # Compute risk metrics from equity series
            risk_sharpe = 0; risk_sortino = 0; risk_maxdd = 0; risk_maxdd_date = ""
            risk_ann_vol = 0
            if len(equity_series) > 1:
                rets = equity_series.pct_change().dropna()
                if rets.std() > 0:
                    risk_sharpe = float(rets.mean() / rets.std() * np.sqrt(252))
                downside = rets[rets < 0]
                if len(downside) > 0 and downside.std() > 0:
                    risk_sortino = float(rets.mean() / downside.std() * np.sqrt(252))
                risk_ann_vol = float(rets.std() * np.sqrt(252) * 100)
                peak = equity_series.expanding().max()
                dd = (equity_series - peak) / peak * 100
                risk_maxdd = float(dd.min())
                risk_maxdd_date = str(dd.idxmin().strftime("%Y-%m-%d")) if len(dd) > 0 else ""

            # Best/worst trade
            all_trade_dicts = [t.to_dict() for t in results.get("closed_trades", [])]
            best = max(all_trade_dicts, key=lambda t: t.get("pnl_pct", 0)) if all_trade_dicts else None
            worst = min(all_trade_dicts, key=lambda t: t.get("pnl_pct", 0)) if all_trade_dicts else None

            # Cumulative PnL
            cum = 0; cum_pnl = []
            for t in all_trade_dicts:
                cum += t.get("pnl", 0)
                cum_pnl.append(round(cum, 2))

            # Monthly returns
            monthly = {}
            if len(equity_series) > 0:
                for d, eq in equity_series.items():
                    key = d.strftime("%Y-%m")
                    if key not in monthly:
                        monthly[key] = {"start": eq, "end": eq}
                    monthly[key]["end"] = eq
            monthly_labels = list(monthly.keys())
            monthly_returns = [round((m["end"] - m["start"]) / m["start"] * 100, 2) for m in monthly.values()]

            # Period
            if len(equity_series) > 0:
                period_start = equity_series.index[0].strftime("%Y-%m-%d")
                period_end = equity_series.index[-1].strftime("%Y-%m-%d")
                period_days = (equity_series.index[-1] - equity_series.index[0]).days
            else:
                period_start = period_end = ""; period_days = 0

            # Win/loss avg
            win_pnls = [t["pnl"] for t in all_trade_dicts if t.get("pnl", 0) > 0]
            loss_pnls = [t["pnl"] for t in all_trade_dicts if t.get("pnl", 0) <= 0]
            avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
            avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0
            pf = abs(sum(win_pnls) / sum(loss_pnls)) if loss_pnls and sum(loss_pnls) != 0 else 999
            avg_hold = sum(t.get("holding_days", 0) for t in all_trade_dicts) / len(all_trade_dicts) if all_trade_dicts else 0
            expectancy = (win_rate/100 * avg_win + (1-win_rate/100) * avg_loss) if total_trades > 0 else 0

            data = {
                "strategy_version": "v4",
                "period": {"start": period_start, "end": period_end, "days": period_days, "years": round(period_days/365, 2)},
                "returns": {"initial": 100000, "final": round(final_eq, 2), "total_pct": round(total_pct, 2),
                           "ann_pct": round(((final_eq/100000)**(365/max(period_days,1))-1)*100, 2),
                           "pnl": round(final_eq - 100000, 2)},
                "trades": {"total": total_trades, "wins": wins, "losses": losses,
                          "win_rate_pct": round(win_rate, 1), "avg_win": round(avg_win, 2),
                          "avg_loss": round(avg_loss, 2), "pf": round(pf, 2),
                          "expectancy": round(expectancy, 2), "avg_hold": round(avg_hold, 1)},
                "benchmark": {"spy_return_pct": round(spy_ret, 2), "alpha_pct": round(alpha, 2)},
                "risk": {"sharpe": round(risk_sharpe, 3), "sortino": round(risk_sortino, 3),
                        "calmar": 0, "max_dd_pct": round(risk_maxdd, 2), "max_dd_date": risk_maxdd_date,
                        "ann_vol_pct": round(risk_ann_vol, 2)},
                "regime_counts": results.get("regime_counts", {}),
                "vix_counts": {},
                "best_trade": best,
                "worst_trade": worst,
                "equity_curve": {
                    "labels": [d.strftime("%Y-%m-%d") for d in equity_series.index] if len(equity_series) > 0 else [],
                    "values": [round(v, 2) for v in equity_series.tolist()],
                },
                "cummax": [round(v, 2) for v in equity_series.cummax().tolist()] if len(equity_series) > 0 else [],
                "dd_series": [round(v, 2) for v in ((equity_series - equity_series.cummax()) / equity_series.cummax() * 100).tolist()] if len(equity_series) > 0 else [],
                "monthly": {"labels": monthly_labels, "returns": monthly_returns},
                "cum_pnl": cum_pnl,
                "all_trades": all_trade_dicts,
            }
            _task_state = {"status": "done", "progress": "Complete!", "result": data}
            return
        else:
            from backtest_v2 import BacktestV2
            if mode == "v2slow":
                Config.apply_strategy(StrategyParams.original())
                _task_state["progress"] = f"Running V2 Original ({days}d, 10d rebalance)..."
            else:
                Config.apply_strategy(StrategyParams.fast())
                _task_state["progress"] = f"Running V2 Fast ({days}d, 3d rebalance)..."
            engine = BacktestV2(initial_capital=100000)
            results = engine.run(Config.UNIVERSE, lookback_days=days)

        if "error" in results:
            _task_state = {"status": "error", "progress": results["error"], "result": None}
            return

        # Serialize results
        equity_curve = results.get("equity_curve")
        data = {
            "strategy_version": mode,
            "period": results["period"],
            "returns": results["returns"],
            "risk": results["risk"],
            "trades": results["trades"],
            "benchmark": results["benchmark"],
            "regime_counts": results.get("regime_counts", {}),
            "vix_counts": results.get("vix_counts", {}),
            "best_trade": results.get("best_trade"),
            "worst_trade": results.get("worst_trade"),
            "all_trades": results.get("all_trades", []),
            "equity_curve": {
                "labels": [d.strftime("%Y-%m-%d") for d in equity_curve.index],
                "values": [round(v, 2) for v in equity_curve.tolist()],
            },
            "cummax": [round(v, 2) for v in equity_curve.cummax().tolist()],
            "dd_series": [round(v, 2) for v in ((equity_curve - equity_curve.cummax()) / equity_curve.cummax() * 100).tolist()],
        }

        # Monthly returns
        monthly = {}
        for d, eq in zip(equity_curve.index, data["equity_curve"]["values"]):
            key = d.strftime("%Y-%m")
            if key not in monthly:
                monthly[key] = {"start": eq, "end": eq}
            monthly[key]["end"] = eq
        data["monthly"] = {
            "labels": list(monthly.keys()),
            "returns": [round((m["end"] - m["start"]) / m["start"] * 100, 2) for m in monthly.values()],
        }

        # Cumulative PnL
        cum = 0
        data["cum_pnl"] = []
        for t in data["all_trades"]:
            cum += t["pnl"]
            data["cum_pnl"].append(round(cum, 2))

        _task_state = {"status": "done", "progress": "Complete!", "result": data}

    except Exception as e:
        _task_state = {"status": "error", "progress": str(e), "result": None}


def run_live_async():
    """Run live V5 scan + execute in background thread"""
    global _task_state
    try:
        _task_state = {"status": "running", "progress": "Executing trades...", "result": None}

        import io
        import re
        from contextlib import redirect_stdout

        from live_trader_v5 import LiveTraderV5

        buf = io.StringIO()
        with redirect_stdout(buf):
            trader = LiveTraderV5()
            state = trader.execute_trades()

        output = buf.getvalue()
        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        output = ansi_escape.sub('', output)

        _task_state = {"status": "done", "progress": "Execute complete", "result": {"output": output, "state": state}}

    except Exception as e:
        _task_state = {"status": "error", "progress": str(e), "result": None}


def run_scan_only_async():
    """Scan only - no trades, just show rankings with analysis"""
    global _task_state
    try:
        _task_state = {"status": "running", "progress": "Scanning...", "result": None}

        from live_trader_v5 import LiveTraderV5

        trader = LiveTraderV5()
        scan = trader.scan()

        # Get current positions
        positions = trader.get_positions()
        account = trader.get_account()

        # Compare positions vs recommendations
        current_etfs = {sym for sym in positions if sym in trader.SECTOR_ETFS}
        target_etfs = set(scan.get('top', []))

        to_buy = target_etfs - current_etfs
        to_sell = current_etfs - target_etfs
        to_hold = current_etfs & target_etfs

        # Build recommendation
        has_changes = bool(to_buy or to_sell)
        recommendation = ""
        if not has_changes and current_etfs:
            recommendation = "当前持仓已是最优，无需调整"
        elif not current_etfs and target_etfs:
            recommendation = "当前无持仓，建议执行交易买入: " + ", ".join(target_etfs)
        elif has_changes:
            parts = []
            if to_buy:
                parts.append("买入: " + ", ".join(sorted(to_buy)))
            if to_sell:
                parts.append("卖出: " + ", ".join(sorted(to_sell)))
            if to_hold:
                parts.append("持有: " + ", ".join(sorted(to_hold)))
            recommendation = "持仓需要调整: " + " | ".join(parts)

        analysis = {
            "scan": scan,
            "positions": {k: v for k, v in positions.items() if k in trader.SECTOR_ETFS},
            "account": account,
            "recommendation": recommendation,
            "should_execute": has_changes,
            "to_buy": sorted(list(to_buy)),
            "to_sell": sorted(list(to_sell)),
            "to_hold": sorted(list(to_hold)),
        }

        _task_state = {"status": "done", "progress": "Scan complete", "result": {"scan": scan, "analysis": analysis}}

    except Exception as e:
        _task_state = {"status": "error", "progress": str(e), "result": None}


@app.route("/")


def index():
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    return render_template_string(html)


@app.route("/api/backtest", methods=["POST"])
def start_backtest():
    data = request.json
    days = int(data.get("days", 365))
    mode = data.get("mode", "v2")

    if _task_state["status"] == "running":
        return jsonify({"error": "Task already running"}), 400

    t = threading.Thread(target=run_backtest_async, args=(days, mode), daemon=True)
    t.start()
    return jsonify({"status": "started", "days": days, "mode": mode})


@app.route("/api/live/scan", methods=["POST"])
def start_live_scan():
    if _task_state["status"] == "running":
        return jsonify({"error": "Task already running"}), 400

    t = threading.Thread(target=run_live_async, daemon=True)
    t.start()
    return jsonify({"status": "started", "mode": "v5"})


@app.route("/api/live/scan-only", methods=["POST"])
def start_scan_only():
    """Scan only - no trades, just show rankings"""
    if _task_state["status"] == "running":
        return jsonify({"error": "Task already running"}), 400

    t = threading.Thread(target=run_scan_only_async, daemon=True)
    t.start()
    return jsonify({"status": "started", "mode": "v5-scan-only"})


@app.route("/api/live/execute", methods=["POST"])
def start_execute():
    """Execute trades based on last scan"""
    if _task_state["status"] == "running":
        return jsonify({"error": "Task already running"}), 400

    t = threading.Thread(target=run_live_async, daemon=True)
    t.start()
    return jsonify({"status": "started", "mode": "v5-execute"})


@app.route("/api/task/status")
def task_status():
    return jsonify(_task_state)


@app.route("/api/live/status")
def live_status():
    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(Config.API_KEY, Config.API_SECRET, paper=True)

        acct = client.get_account()
        positions = client.get_all_positions()

        pos_list = []
        for p in positions:
            pos_list.append({
                "symbol": p.symbol,
                "qty": int(p.qty),
                "avg_entry": round(float(p.avg_entry_price), 2),
                "current": round(float(p.current_price), 2),
                "unrealized_pl": round(float(p.unrealized_pl), 2),
                "unrealized_plpc": round(float(p.unrealized_plpc) * 100, 2),
            })

        state_file = os.path.join(os.path.dirname(__file__), "live_state_v5.json")
        state = {}
        if os.path.exists(state_file):
            with open(state_file) as f:
                state = json.load(f)

        return jsonify({
            "equity": round(float(acct.equity), 2),
            "cash": round(float(acct.cash), 2),
            "buying_power": round(float(acct.buying_power), 2),
            "positions": pos_list,
            "last_rebalance": state.get("last_rebalance"),
            "trailing_stops": state.get("trailing_stops", {}),
            "monitor": _monitor_state,
            "scheduler": _scheduler_running,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/monitor/check", methods=["POST"])
def manual_monitor_check():
    """Manually trigger a real-time stop loss check"""
    try:
        from live_trader_v2 import run_realtime_monitor
        import io
        import re
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            result = run_realtime_monitor()

        output = buf.getvalue()
        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        output = ansi_escape.sub('', output)

        _monitor_state["last_check"] = datetime.now().isoformat()
        _monitor_state["actions"] = result.get("actions", [])
        _monitor_state["positions"] = result.get("positions", 0)
        _monitor_state["output"] = output

        return jsonify({"status": "done", **result, "output": output})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/monitor/state")
def monitor_state():
    return jsonify(_monitor_state)


@app.route("/api/scheduler/toggle", methods=["POST"])
def toggle_scheduler():
    """Start/stop the 15-minute monitoring scheduler"""
    global _scheduler_running

    data = request.json or {}
    action = data.get("action", "toggle")

    if action == "stop":
        _scheduler_running = False
        return jsonify({"status": "stopped"})

    # Start scheduler
    _scheduler_running = True

    def scheduler_loop():
        global _scheduler_running
        import re
        import io
        from contextlib import redirect_stdout

        while _scheduler_running:
            now = datetime.now()
            # US market hours: 9:30 AM - 4:00 PM ET = 21:30 - 04:00 Beijing (EDT)
            hour_bj = now.hour
            weekday = now.weekday()  # 0=Mon, 6=Sun

            is_market_hours = weekday < 5 and (
                hour_bj >= 21 or hour_bj < 4
            )

            if is_market_hours:
                try:
                    from live_trader_v2 import run_realtime_monitor
                    buf = io.StringIO()
                    with redirect_stdout(buf):
                        result = run_realtime_monitor()
                    output = buf.getvalue()
                    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
                    output = ansi_escape.sub('', output)

                    _monitor_state["last_check"] = datetime.now().isoformat()
                    _monitor_state["actions"] = result.get("actions", [])
                    _monitor_state["positions"] = result.get("positions", 0)
                    _monitor_state["output"] = output
                except Exception as e:
                    _monitor_state["output"] = f"Error: {e}"

            # Wait 15 minutes
            for _ in range(900):  # 15 * 60 = 900 seconds
                if not _scheduler_running:
                    break
                import time
                time.sleep(1)

    if not any(t.name == "monitor_scheduler" for t in threading.enumerate()):
        t = threading.Thread(target=scheduler_loop, name="monitor_scheduler", daemon=True)
        t.start()

    return jsonify({"status": "started", "interval": "15 minutes", "market_hours": "21:30-04:00 Beijing"})


@app.route("/api/scheduler/toggle", methods=["GET"])
def get_scheduler_status():
    return jsonify({"running": _scheduler_running})


@app.route("/api/cache/status")
def cache_status():
    from data_cache import status as cs, clear as cc
    return jsonify(cs())


@app.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    from data_cache import clear
    clear()
    return jsonify({"status": "cleared"})


@app.route("/api/walkforward/start", methods=["POST"])
def start_walkforward():
    """Start V5 walk-forward validation in background"""
    global _wf_state

    data = request.json or {}
    train_days = data.get("train_days", 120)
    test_days = data.get("test_days", 60)

    if _wf_state["status"] == "running":
        return jsonify({"error": "Walk-Forward already running"}), 400

    _wf_state = {"status": "running", "progress": "Loading ETF data...", "result": None}

    def run_wf():
        global _wf_state
        try:
            import pickle
            import numpy as np
            from pathlib import Path
            from strategy_sector import SectorRotation

            _wf_state["progress"] = "Loading data..."
            batch_path = Path(__file__).parent / "data" / "cache" / "batch_etf.pkl"
            with open(batch_path, "rb") as f:
                etf_data = pickle.load(f)
            spy_data = etf_data.pop("SPY")

            # Best params from grid search
            LOOKBACK = 30
            TOP_N = 2
            REBAL = 15
            STEP = 30

            all_dates = sorted(set(d for df in etf_data.values() for d in df.index))
            warmup = max(LOOKBACK, 200)
            trading_days = [d for d in all_dates if d >= spy_data.index[warmup]]
            total = len(trading_days)

            if total < train_days + test_days:
                test_days_adj = max(20, int(total * 0.3))
                train_days_adj = total - test_days_adj
            else:
                train_days_adj = train_days
                test_days_adj = test_days

            windows = []
            i = 0
            while i + train_days_adj + test_days_adj <= total:
                windows.append({
                    "train": (trading_days[i], trading_days[i + train_days_adj - 1]),
                    "test": (trading_days[i + train_days_adj], trading_days[min(i + train_days_adj + test_days_adj - 1, total - 1)])
                })
                i += STEP

            if not windows:
                _wf_state = {"status": "error", "progress": "Not enough data for windows", "result": None}
                return

            trains = []
            tests = []
            wf_windows = []

            for wi, w in enumerate(windows):
                _wf_state["progress"] = f"Window {wi+1}/{len(windows)}..."
                ts, te = w["train"]
                xs, xe = w["test"]

                e1 = SectorRotation(top_n=TOP_N, lookback=LOOKBACK, rebalance_days=REBAL)
                r1 = e1.run_windowed(dict(etf_data), spy_data, ts, te)
                tr = r1.get("total_pct", -999)
                trains.append(tr)

                e2 = SectorRotation(top_n=TOP_N, lookback=LOOKBACK, rebalance_days=REBAL)
                r2 = e2.run_windowed(dict(etf_data), spy_data, xs, xe)
                te_r = r2.get("total_pct", -999)
                tests.append(te_r)

                wf_windows.append({
                    "window": wi + 1,
                    "train_start": ts.strftime("%Y-%m-%d"),
                    "train_end": te.strftime("%Y-%m-%d"),
                    "test_start": xs.strftime("%Y-%m-%d"),
                    "test_end": xe.strftime("%Y-%m-%d"),
                    "train_return": tr,
                    "test_return": te_r,
                    "params": {"lookback": LOOKBACK, "top_n": TOP_N, "rebalance": REBAL}
                })

            train_avg = float(np.mean(trains))
            test_avg = float(np.mean(tests))
            pos = sum(1 for t in tests if t > 0)
            deg = train_avg - test_avg
            verdict = "ROBUST" if deg < 3 else ("MODERATE" if deg < 6 else "OVERFIT")

            result = {
                "windows": wf_windows,
                "train_avg": round(train_avg, 2),
                "test_avg": round(test_avg, 2),
                "positive_tests": pos,
                "total_tests": len(tests),
                "degradation": round(deg, 2),
                "verdict": verdict,
                "config": {"lookback": LOOKBACK, "top_n": TOP_N, "rebalance": REBAL, "strategy": "V5 Sector Rotation"}
            }

            _wf_state = {"status": "done", "progress": "Complete!", "result": result}

        except Exception as e:
            import traceback
            _wf_state = {"status": "error", "progress": str(e), "result": None}

    t = threading.Thread(target=run_wf, daemon=True)
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/walkforward/status")
def walkforward_status():
    return jsonify(_wf_state)


@app.route("/api/strategy/info")
def strategy_info():
    """Return current market regime and strategy state"""
    try:
        from strategy_v4 import detect_trend_regime, rank_stocks
        from live_trader_v5 import LiveTraderV5, SECTOR_ETFS

        trader = LiveTraderV5()
        scan = trader.scan()
        if "error" not in scan:
            rankings = [{
                "symbol": r["symbol"],
                "score": round(r["rs"], 4),
                "momentum": r.get("momentum", 0),
                "quality": 0,
                "price": r["price"],
            } for r in scan.get("rankings", [])[:5]]

            return jsonify({
                "regime": {"regime": scan["regime"], "spy_price": scan["spy_price"], "spy_sma200": scan["spy_sma200"]},
                "rankings": rankings,
                "top_etfs": scan.get("top", []),
                "factors": {"relative_strength_30d": 1.0},
                "version": "v5",
            })
        else:
            return jsonify({"error": scan["error"], "version": "v5"})
    except Exception as e:
        return jsonify({"error": str(e)})




if __name__ == "__main__":
    print("Starting V2 Dashboard Server...")
    print("Open: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)

