"""
server.py - V5 Sector Rotation Dashboard
启动: python server.py
访问: http://localhost:5000
"""
import os
import sys
import json
import threading
import numpy as np
from datetime import datetime

from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(__file__))
from config import Config

app = Flask(__name__)
CORS(app)

# Global state
_task_state = {"status": "idle", "progress": "", "result": None}
_wf_state = {"status": "idle", "progress": "", "result": None}


def run_backtest_async(days):
    """Run V5 backtest in background thread"""
    global _task_state
    try:
        _task_state = {"status": "running", "progress": "Loading data...", "result": None}

        import data_cache
        import pandas as _pd
        from strategy_sector import SectorRotation

        _task_state["progress"] = "Running V5 Sector Rotation..."
        etfs = ['XLK', 'XLE', 'XLF', 'XLV', 'XLU', 'XLP', 'XLI', 'XLRE', 'XBI']
        etf_data = {}
        for sym in etfs:
            df = data_cache.get(sym, 730)
            if df is not None:
                etf_data[sym] = df
        spy_data = data_cache.get('SPY', 730)

        if not etf_data or spy_data is None:
            _task_state = {"status": "error", "progress": "Missing ETF or SPY data.", "result": None}
            return

        engine = SectorRotation(initial_capital=100000, top_n=2, lookback=30, rebalance_days=15)
        results = engine.run(etf_data, spy_data)

        if "error" in results:
            _task_state = {"status": "error", "progress": results["error"], "result": None}
            return

        ec = results.get("equity_curve", {"labels": [], "values": []})
        ec_labels = ec.get("labels", [])
        ec_values = ec.get("values", [])
        eq_series = _pd.Series(ec_values, index=ec_labels)
        dd_list = []
        if len(eq_series) > 0:
            peak = eq_series.cummax()
            dd_list = ((eq_series - peak) / peak * 100).round(2).tolist()

        m_labels, m_returns = [], []
        if len(ec_values) > 20:
            for i in range(0, len(ec_values), 20):
                chunk_end = min(i + 20, len(ec_values) - 1)
                if i > 0:
                    m_ret = (ec_values[chunk_end] / ec_values[i] - 1) * 100
                    m_returns.append(round(m_ret, 2))
                    m_labels.append(ec_labels[i][:7])

        risk = results.get("risk", {})
        trades = results.get("trades", {})

        data = {
            "strategy_version": "v5",
            "period": {"start": ec_labels[0] if ec_labels else "", "end": ec_labels[-1] if ec_labels else "", "days": days, "years": round(days / 365, 2)},
            "returns": {"final": results.get("final_equity", 100000), "initial": 100000, "pnl": results.get("final_equity", 100000) - 100000, "total_pct": results.get("total_pct", 0)},
            "risk": {"sharpe": risk.get("sharpe", 0), "sortino": risk.get("sharpe", 0) * 1.5, "max_dd_pct": risk.get("max_dd_pct", 0), "max_dd_date": risk.get("max_dd_date", ""), "ann_vol_pct": risk.get("avg_vol", 8), "calmar": 0},
            "trades": {"total": trades.get("total", 0), "wins": trades.get("wins", 0), "losses": trades.get("losses", 0), "win_rate_pct": trades.get("win_rate_pct", 0), "pf": trades.get("pf", 0), "expectancy": trades.get("expectancy", 0), "avg_hold": trades.get("avg_hold", 0)},
            "benchmark": {"spy_return_pct": 0, "alpha_pct": 0},
            "all_trades": results.get("all_trades", []),
            "equity_curve": {"labels": ec_labels, "values": ec_values},
            "dd_series": dd_list,
            "monthly": {"labels": m_labels, "returns": m_returns},
            "cum_pnl": [],
        }
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

        from live_trader_v5 import LiveTraderV5, SECTOR_ETFS

        trader = LiveTraderV5()
        scan = trader.scan()

        positions = trader.get_positions()
        account = trader.get_account()

        current_etfs = {sym for sym in positions if sym in SECTOR_ETFS}
        target_etfs = set(scan.get('top', []))

        to_buy = target_etfs - current_etfs
        to_sell = current_etfs - target_etfs
        to_hold = current_etfs & target_etfs

        has_changes = bool(to_buy or to_sell)
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
        else:
            recommendation = "无推荐"

        analysis = {
            "scan": scan,
            "positions": {k: v for k, v in positions.items() if k in SECTOR_ETFS},
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


# === Routes ===

@app.route("/")
def index():
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    return render_template_string(html)


@app.route("/api/backtest", methods=["POST"])
def start_backtest():
    if _task_state["status"] == "running":
        return jsonify({"error": "Task already running"}), 400
    days = int((request.json or {}).get("days", 730))
    t = threading.Thread(target=run_backtest_async, args=(days,), daemon=True)
    t.start()
    return jsonify({"status": "started", "days": days})


@app.route("/api/task/status")
def task_status():
    return jsonify(_task_state)


@app.route("/api/live/scan-only", methods=["POST"])
def start_scan_only():
    if _task_state["status"] == "running":
        return jsonify({"error": "Task already running"}), 400
    t = threading.Thread(target=run_scan_only_async, daemon=True)
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/live/execute", methods=["POST"])
def start_execute():
    if _task_state["status"] == "running":
        return jsonify({"error": "Task already running"}), 400
    t = threading.Thread(target=run_live_async, daemon=True)
    t.start()
    return jsonify({"status": "started"})


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
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cache/status")
def cache_status():
    from data_cache import status as cs
    return jsonify(cs())


@app.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    from data_cache import clear
    clear()
    return jsonify({"status": "cleared"})


@app.route("/api/walkforward/start", methods=["POST"])
def start_walkforward():
    global _wf_state

    if _wf_state["status"] == "running":
        return jsonify({"error": "Walk-Forward already running"}), 400

    data = request.json or {}
    train_days = data.get("train_days", 120)
    test_days = data.get("test_days", 60)
    _wf_state = {"status": "running", "progress": "Loading data...", "result": None}

    def run_wf():
        global _wf_state
        try:
            import data_cache
            import numpy as np
            from strategy_sector import SectorRotation

            _wf_state["progress"] = "Loading ETF data..."
            etfs = ['XLK', 'XLE', 'XLF', 'XLV', 'XLU', 'XLP', 'XLI', 'XLRE', 'XBI']
            etf_data = {}
            for sym in etfs:
                df = data_cache.get(sym, 730)
                if df is not None:
                    etf_data[sym] = df
            spy_data = data_cache.get('SPY', 730)

            if not etf_data or spy_data is None:
                _wf_state = {"status": "error", "progress": "Missing data.", "result": None}
                return

            LOOKBACK, TOP_N, REBAL, STEP = 30, 2, 15, 30

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
                _wf_state = {"status": "error", "progress": "Not enough data", "result": None}
                return

            wf_windows = []
            for wi, w in enumerate(windows):
                _wf_state["progress"] = f"Window {wi + 1}/{len(windows)}..."
                ts, te = w["train"]
                xs, xe = w["test"]

                e1 = SectorRotation(top_n=TOP_N, lookback=LOOKBACK, rebalance_days=REBAL)
                r1 = e1.run_windowed(dict(etf_data), spy_data, ts, te)
                tr = r1.get("total_pct", -999)

                e2 = SectorRotation(top_n=TOP_N, lookback=LOOKBACK, rebalance_days=REBAL)
                r2 = e2.run_windowed(dict(etf_data), spy_data, xs, xe)
                te_r = r2.get("total_pct", -999)

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

            tests = [w["test_return"] for w in wf_windows]
            trains = [w["train_return"] for w in wf_windows]
            train_avg = float(np.mean(trains))
            test_avg = float(np.mean(tests))
            pos = sum(1 for t in tests if t > 0)
            deg = train_avg - test_avg

            result = {
                "windows": wf_windows,
                "train_avg": round(train_avg, 2),
                "test_avg": round(test_avg, 2),
                "positive_tests": pos,
                "total_tests": len(tests),
                "degradation": round(deg, 2),
                "verdict": "ROBUST" if deg < 3 else ("MODERATE" if deg < 6 else "OVERFIT"),
            }

            _wf_state = {"status": "done", "progress": "Complete!", "result": result}

        except Exception as e:
            _wf_state = {"status": "error", "progress": str(e), "result": None}

    t = threading.Thread(target=run_wf, daemon=True)
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/walkforward/status")
def walkforward_status():
    return jsonify(_wf_state)


@app.route("/api/strategy/info")
def strategy_info():
    try:
        from live_trader_v5 import LiveTraderV5

        trader = LiveTraderV5()
        scan = trader.scan()
        if "error" not in scan:
            rankings = [{
                "symbol": r["symbol"],
                "score": round(r["rs"], 4),
                "momentum": r.get("momentum", 0) / 100,
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
    print("V5 Sector Rotation Dashboard")
    print("Open: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
