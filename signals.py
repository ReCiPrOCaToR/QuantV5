"""
signals.py - 多因子信号评分系统
综合 6 大维度给每只股票打分 (0~1)，>0.6 买入，<0.35 卖出
"""
from config import Config


def score_trend(signals: dict) -> float:
    """
    趋势因子 (25%)
    - 价格在 SMA20/50 之上
    - 均线多头排列
    - 金叉/死叉
    - ADX 趋势强度
    - MACD 方向
    """
    score = 0.0
    weight_sum = 0.0

    items = [
        (signals.get("price_above_sma20", 0.5), 0.15),
        (signals.get("price_above_sma50", 0.5), 0.15),
        (signals.get("sma20_above_sma50", 0.5), 0.10),
        (signals.get("golden_cross", 0.0), 0.20),     # 金叉权重高
        (1.0 - signals.get("death_cross", 0.0), 0.15), # 死叉反向
        (signals.get("adx_strong_trend", 0.0), 0.10),
        (signals.get("adx_uptrend", 0.5), 0.10),
        (signals.get("macd_bullish", 0.5), 0.15),
        (signals.get("macd_hist_rising", 0.5), 0.10),
    ]

    for val, w in items:
        score += val * w
        weight_sum += w

    return score / weight_sum if weight_sum > 0 else 0.5


def score_momentum(signals: dict) -> float:
    """
    动量因子 (25%)
    - RSI 位置 (超卖反弹机会 vs 超买风险)
    - 随机指标
    - 动量方向
    """
    rsi = signals.get("rsi_oversold", 0.0)
    rsi_ob = signals.get("rsi_overbought", 0.0)
    rsi_neutral = signals.get("rsi_neutral", 0.0)
    rsi_rising = signals.get("rsi_rising", 0.5)

    # RSI 超卖反弹 = 好机会；RSI 超买 = 风险
    rsi_score = 0.5
    if rsi and not rsi_ob:
        rsi_score = 0.75  # 超卖，潜在反弹
    elif rsi_ob:
        rsi_score = 0.25  # 超买，风险
    elif rsi_neutral and rsi_rising:
        rsi_score = 0.65  # 中性且上升
    elif rsi_rising:
        rsi_score = 0.60

    stoch_os = signals.get("stoch_oversold", 0.0)
    stoch_ob = signals.get("stoch_overbought", 0.0)
    stoch_kd = signals.get("stoch_k_above_d", 0.5)

    stoch_score = 0.5
    if stoch_os and stoch_kd:
        stoch_score = 0.80  # 超卖 + K>D = 强买入
    elif stoch_os:
        stoch_score = 0.65
    elif stoch_ob and not stoch_kd:
        stoch_score = 0.20
    elif stoch_kd:
        stoch_score = 0.60
    else:
        stoch_score = 0.40

    pos_5d = signals.get("positive_momentum_5d", 0.5)
    pos_20d = signals.get("positive_momentum_20d", 0.5)

    momentum_score = pos_5d * 0.4 + pos_20d * 0.3 + (1.0 if pos_5d and pos_20d else 0.0) * 0.3

    return rsi_score * 0.35 + stoch_score * 0.35 + momentum_score * 0.30


def score_volatility(signals: dict) -> float:
    """
    波动率因子 (15%)
    - 布林带位置 — 价格接近下轨是买入机会
    - 布林带挤压 — 预示大行情
    - ATR 归入风险管理
    """
    bb_pct = 1.0 - signals.get("price_near_bb_lower", 0.5)  # 接近下轨 → 高分
    bb_upper = signals.get("price_near_bb_upper", 0.0)
    squeeze = signals.get("bb_squeeze", 0.0)

    score = 0.5
    if bb_pct > 0.7 and not bb_upper:
        score = 0.70  # 价格在布林带下半区
    elif bb_upper:
        score = 0.30  # 价格在上轨附近，追高风险
    elif squeeze:
        score = 0.60  # 挤压 = 可能有大行情
    else:
        score = bb_pct * 0.5 + 0.25

    return score


def score_volume(signals: dict) -> float:
    """
    成交量因子 (15%)
    - 量能放大 + 价格上涨 = 确认信号
    - OBV 方向
    - MFI 资金流向
    """
    vol_spike = signals.get("volume_spike", 0.0)
    obv_rising = signals.get("obv_rising", 0.5)
    mfi_os = signals.get("mfi_oversold", 0.0)
    mfi_ob = signals.get("mfi_overbought", 0.0)

    # 放量 + OBV上升 = 强确认
    vol_confirm = vol_spike * 0.5 + obv_rising * 0.5

    mfi_score = 0.5
    if mfi_os:
        mfi_score = 0.70  # 资金超卖
    elif mfi_ob:
        mfi_score = 0.30

    return vol_confirm * 0.5 + mfi_score * 0.5


def score_mean_reversion(signals: dict) -> float:
    """
    均值回归因子 (10%)
    - 价格偏离均线过远时有回归倾向
    - 配合 RSI 超卖效果更佳
    """
    rsi_os = signals.get("rsi_oversold", 0.0)
    bb_lower = signals.get("price_near_bb_lower", 0.0)

    # 双重超卖 = 均值回归机会
    if rsi_os and bb_lower:
        return 0.80
    elif rsi_os or bb_lower:
        return 0.65
    else:
        return 0.50


def score_price_action(signals: dict) -> float:
    """
    Price action / momentum confirmation factor (10%)
    - Near ATH = strong
    - Multi-period momentum alignment
    """
    near_ath = signals.get("price_near_ath", 0.0)
    pos_5d = signals.get("positive_momentum_5d", 0.5)
    pos_20d = signals.get("positive_momentum_20d", 0.5)

    # Multi-period resonance
    resonance = 0.5
    if pos_5d and pos_20d and near_ath:
        resonance = 0.85  # Strong with aligned momentum
    elif pos_5d and pos_20d:
        resonance = 0.70
    elif pos_5d or pos_20d:
        resonance = 0.55
    else:
        resonance = 0.30

    return resonance


def compute_composite_score(signals: dict) -> dict:
    """
    计算综合评分，返回各因子得分和总分。
    """
    weights = Config.WEIGHTS

    scores = {
        "trend": score_trend(signals),
        "momentum": score_momentum(signals),
        "volatility": score_volatility(signals),
        "volume": score_volume(signals),
        "mean_reversion": score_mean_reversion(signals),
        "sentiment_price_action": score_price_action(signals),
    }

    composite = sum(scores[k] * weights[k] for k in scores)

    return {
        "scores": scores,
        "composite": round(composite, 4),
        "action": (
            "BUY" if composite > Config.BUY_THRESHOLD
            else "SELL" if composite < Config.SELL_THRESHOLD
            else "HOLD"
        ),
    }
