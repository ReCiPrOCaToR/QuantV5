"""
indicators.py - 技术指标计算
使用 ta 库 + pandas 计算全套技术指标
"""
import pandas as pd
import numpy as np
from ta.trend import SMAIndicator, EMAIndicator, ADXIndicator, MACD, IchimokuIndicator
from ta.momentum import RSIIndicator, StochasticOscillator, WilliamsRIndicator
from ta.volatility import BollingerBands, AverageTrueRange, DonchianChannel
from ta.volume import OnBalanceVolumeIndicator, VolumeWeightedAveragePrice, MFIIndicator
from ta.others import DailyLogReturnIndicator


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    给定 OHLCV DataFrame，计算全套技术指标。
    要求列名: open, high, low, close, volume (小写)
    """
    df = df.copy()

    # === 趋势指标 ===
    df["sma_20"] = SMAIndicator(close=df["close"], window=20).sma_indicator()
    df["sma_50"] = SMAIndicator(close=df["close"], window=50).sma_indicator()
    df["sma_200"] = SMAIndicator(close=df["close"], window=200).sma_indicator()
    df["ema_12"] = EMAIndicator(close=df["close"], window=12).ema_indicator()
    df["ema_26"] = EMAIndicator(close=df["close"], window=26).ema_indicator()

    # ADX — 趋势强度
    adx = ADXIndicator(high=df["high"], low=df["low"], close=df["close"], window=14)
    df["adx"] = adx.adx()
    df["adx_pos"] = adx.adx_pos()  # +DI
    df["adx_neg"] = adx.adx_neg()  # -DI

    # MACD
    macd = MACD(close=df["close"], window_slow=26, window_fast=12, window_sign=9)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    # 一目均衡表 (简化)
    try:
        ichi = IchimokuIndicator(high=df["high"], low=df["low"])
        df["ichimoku_a"] = ichi.ichimoku_a()
        df["ichimoku_b"] = ichi.ichimoku_b()
        df["ichimoku_base"] = ichi.ichimoku_base_line()
    except Exception:
        df["ichimoku_a"] = np.nan
        df["ichimoku_b"] = np.nan
        df["ichimoku_base"] = np.nan

    # === 动量指标 ===
    df["rsi"] = RSIIndicator(close=df["close"], window=14).rsi()

    stoch = StochasticOscillator(
        high=df["high"], low=df["low"], close=df["close"],
        window=14, smooth_window=3
    )
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    df["williams_r"] = WilliamsRIndicator(
        high=df["high"], low=df["low"], close=df["close"], lbp=14
    ).williams_r()

    # === 波动率指标 ===
    bb = BollingerBands(close=df["close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
    df["bb_pct"] = bb.bollinger_pband()  # 价格在布林带中的位置 (0-1)

    df["atr"] = AverageTrueRange(
        high=df["high"], low=df["low"], close=df["close"], window=14
    ).average_true_range()

    # 唐奇安通道
    dc = DonchianChannel(high=df["high"], low=df["low"], close=df["close"], window=20)
    df["dc_upper"] = dc.donchian_channel_hband()
    df["dc_lower"] = dc.donchian_channel_lband()

    # === 成交量指标 ===
    df["obv"] = OnBalanceVolumeIndicator(close=df["close"], volume=df["volume"]).on_balance_volume()
    df["mfi"] = MFIIndicator(
        high=df["high"], low=df["low"], close=df["close"], volume=df["volume"], window=14
    ).money_flow_index()

    # 成交量相对均值的比率
    df["vol_sma_20"] = SMAIndicator(close=df["volume"], window=20).sma_indicator()
    df["vol_ratio"] = df["volume"] / df["vol_sma_20"].replace(0, np.nan)

    # === 收益率 ===
    df["daily_return"] = DailyLogReturnIndicator(close=df["close"]).daily_log_return()
    df["return_5d"] = df["close"].pct_change(5)
    df["return_20d"] = df["close"].pct_change(20)

    return df


def get_latest_signals(df: pd.DataFrame) -> dict:
    """
    从最新的指标行提取信号快照，返回字典。
    """
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    signals = {
        # 趋势
        "price_above_sma20": float(latest["close"] > latest["sma_20"]),
        "price_above_sma50": float(latest["close"] > latest["sma_50"]),
        "sma20_above_sma50": float(latest["sma_20"] > latest["sma_50"]),
        "golden_cross": float(
            prev["sma_20"] <= prev["sma_50"] and latest["sma_20"] > latest["sma_50"]
        ),
        "death_cross": float(
            prev["sma_20"] >= prev["sma_50"] and latest["sma_20"] < latest["sma_50"]
        ),
        "adx_strong_trend": float(latest["adx"] > 25),
        "adx_uptrend": float(latest["adx_pos"] > latest["adx_neg"]),
        "macd_bullish": float(latest["macd"] > latest["macd_signal"]),
        "macd_hist_rising": float(latest["macd_hist"] > prev["macd_hist"]),

        # 动量
        "rsi_oversold": float(latest["rsi"] < 30),
        "rsi_overbought": float(latest["rsi"] > 70),
        "rsi_neutral": float(40 < latest["rsi"] < 60),
        "rsi_rising": float(latest["rsi"] > prev["rsi"]),
        "stoch_oversold": float(latest["stoch_k"] < 20),
        "stoch_overbought": float(latest["stoch_k"] > 80),
        "stoch_k_above_d": float(latest["stoch_k"] > latest["stoch_d"]),

        # 波动率
        "bb_squeeze": float(latest["bb_width"] < df["bb_width"].rolling(60).mean().iloc[-1] * 0.5)
        if not np.isnan(latest["bb_width"]) else 0.0,
        "price_near_bb_lower": float(latest["bb_pct"] < 0.2) if not np.isnan(latest["bb_pct"]) else 0.5,
        "price_near_bb_upper": float(latest["bb_pct"] > 0.8) if not np.isnan(latest["bb_pct"]) else 0.5,

        # 成交量
        "volume_spike": float(latest["vol_ratio"] > 1.5) if not np.isnan(latest["vol_ratio"]) else 0.0,
        "obv_rising": float(latest["obv"] > prev["obv"]),
        "mfi_oversold": float(latest["mfi"] < 20) if not np.isnan(latest["mfi"]) else 0.0,
        "mfi_overbought": float(latest["mfi"] > 80) if not np.isnan(latest["mfi"]) else 0.0,

        # 价格行为
        "positive_momentum_5d": float(latest["return_5d"] > 0) if not np.isnan(latest["return_5d"]) else 0.5,
        "positive_momentum_20d": float(latest["return_20d"] > 0) if not np.isnan(latest["return_20d"]) else 0.5,
        "price_near_ath": 0.0,  # 需要额外计算
    }

    # 价格相对 252 日最高价的位置
    if "high" in df.columns and len(df) >= 252:
        ath = df["high"].iloc[-252:].max()
        signals["price_near_ath"] = float(latest["close"] > ath * 0.95)

    return signals
