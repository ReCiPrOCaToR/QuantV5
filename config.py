"""
config.py - 配置管理
"""
import os
from dotenv import load_dotenv

load_dotenv()


class StrategyParams:
    """Strategy parameters — create instances for different variants"""
    def __init__(self, **kwargs):
        self.MAX_POSITIONS = kwargs.get("max_positions", 3)
        self.RISK_PER_TRADE = kwargs.get("risk_per_trade", 0.02)
        self.MAX_PORTFOLIO_RISK = kwargs.get("max_portfolio_risk", 0.10)
        self.MAX_SINGLE_POSITION_PCT = kwargs.get("max_single_pct", 0.20)
        self.STOP_LOSS_ATR_MULT = kwargs.get("stop_loss", 1.8)
        self.TAKE_PROFIT_ATR_MULT = kwargs.get("take_profit", 3.0)
        self.TRAILING_STOP_ATR_MULT = kwargs.get("trail_stop", 1.5)
        self.TRAIL_ACTIVATION_PCT = kwargs.get("trail_activation", 0.05)
        self.REBALANCE_INTERVAL = kwargs.get("rebalance_interval", 3)

    @classmethod
    def fast(cls):
        return cls(max_positions=3, stop_loss=1.8, take_profit=3.0,
                   trail_stop=1.5, trail_activation=0.05, rebalance_interval=3)

    @classmethod
    def original(cls):
        return cls(max_positions=4, risk_per_trade=0.025, stop_loss=2.5,
                   take_profit=5.0, trail_stop=2.0, trail_activation=0.08,
                   rebalance_interval=10, max_single_pct=0.25)


class Config:
    # Alpaca API
    API_KEY = os.getenv("APCA_API_KEY_ID", "")
    API_SECRET = os.getenv("APCA_API_SECRET_KEY", "")
    BASE_URL = os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets")

    # 交易标的 — 多行业大盘股 + 对冲ETF
    UNIVERSE = os.getenv(
        "UNIVERSE",
        "AAPL,MSFT,GOOGL,AMZN,NVDA,META,TSLA,AMD,COST,NKE,JPM,GS,JNJ,UNH,V,MA,XOM,CVX,SH"
    ).split(",")

    # Default strategy params (fast variant)
    _strategy = StrategyParams.fast()
    MAX_POSITIONS = _strategy.MAX_POSITIONS
    RISK_PER_TRADE = _strategy.RISK_PER_TRADE
    MAX_PORTFOLIO_RISK = _strategy.MAX_PORTFOLIO_RISK
    MAX_SINGLE_POSITION_PCT = _strategy.MAX_SINGLE_POSITION_PCT
    STOP_LOSS_ATR_MULT = _strategy.STOP_LOSS_ATR_MULT
    TAKE_PROFIT_ATR_MULT = _strategy.TAKE_PROFIT_ATR_MULT
    TRAILING_STOP_ATR_MULT = _strategy.TRAILING_STOP_ATR_MULT
    TRAIL_ACTIVATION_PCT = _strategy.TRAIL_ACTIVATION_PCT
    REBALANCE_INTERVAL = _strategy.REBALANCE_INTERVAL

    # Capital curve protection (meta-strategy layer)
    MAX_CONSECUTIVE_LOSSES = 3        # Pause after N consecutive losing trades
    MAX_DRAWDOWN_PAUSE = 0.05         # Pause if drawdown exceeds 5%
    PAUSE_COOLDOWN_DAYS = 10          # Wait N days before resuming after pause

    @classmethod
    def apply_strategy(cls, params: StrategyParams):
        """Apply a StrategyParams to this Config (use before backtest/live run)"""
        cls.MAX_POSITIONS = params.MAX_POSITIONS
        cls.RISK_PER_TRADE = params.RISK_PER_TRADE
        cls.MAX_PORTFOLIO_RISK = params.MAX_PORTFOLIO_RISK
        cls.MAX_SINGLE_POSITION_PCT = params.MAX_SINGLE_POSITION_PCT
        cls.STOP_LOSS_ATR_MULT = params.STOP_LOSS_ATR_MULT
        cls.TAKE_PROFIT_ATR_MULT = params.TAKE_PROFIT_ATR_MULT
        cls.TRAILING_STOP_ATR_MULT = params.TRAILING_STOP_ATR_MULT
        cls.TRAIL_ACTIVATION_PCT = params.TRAIL_ACTIVATION_PCT
        cls.REBALANCE_INTERVAL = params.REBALANCE_INTERVAL

    # 回测/运行
    INTERVAL_MINUTES = int(os.getenv("INTERVAL_MINUTES", "15"))
    LOOKBACK_DAYS = 100                    # 获取历史数据天数
    DATA_TIMEFRAME = "1Day"                # 日线级别
    MONITOR_INTERVAL = 15                  # 实盘止损监控间隔（分钟）
    INTRADAY_TIMEFRAME = "1Hour"           # 盘中分析用1小时线

    # Signal weight distribution (6 factors)
    WEIGHTS = {
        "trend": 0.20,
        "momentum": 0.25,
        "volatility": 0.10,
        "volume": 0.15,
        "mean_reversion": 0.10,
        "sentiment_price_action": 0.20,
    }

    # Signal thresholds
    BUY_THRESHOLD = 0.58   # Balanced entry
    SELL_THRESHOLD = 0.35

    # 日志
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
