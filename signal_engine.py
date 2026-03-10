"""
BTCUSDT Sniper v6 — Signal Engine
1:1 Pine Script replica. EMA Trend=130, EMA Fast=161
"""

import numpy as np
import pandas as pd
import logging
from settings import *

logger = logging.getLogger("SignalEngine")


def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def atr(high, low, close, length):
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=length, adjust=False).mean()

def rsi(close, length):
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(span=length, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(span=length, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def dmi(high, low, close, di_len, adx_smooth):
    up   = high.diff()
    down = -low.diff()
    plus_dm  = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr_vals  = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    tr_smooth    = pd.Series(tr_vals).ewm(span=di_len, adjust=False).mean()
    plus_smooth  = pd.Series(plus_dm).ewm(span=di_len, adjust=False).mean()
    minus_smooth = pd.Series(minus_dm).ewm(span=di_len, adjust=False).mean()
    dip     = 100 * plus_smooth  / tr_smooth.replace(0, np.nan)
    dim     = 100 * minus_smooth / tr_smooth.replace(0, np.nan)
    dx      = 100 * (dip - dim).abs() / (dip + dim).replace(0, np.nan)
    adx_raw = dx.ewm(span=adx_smooth, adjust=False).mean()
    return dip, dim, adx_raw


class SignalEngine:
    def __init__(self, lots=DEFAULT_LOTS, timeframe=DEFAULT_TIMEFRAME):
        self.lots        = lots
        self.timeframe   = timeframe
        self.trail_stage = 0
        self.entry_price = None
        self.be_done     = False
        self.position    = 0
        self.entry_id    = None

    def compute(self, df):
        if len(df) < max(EMA_TREND_LEN, ATR_LEN * 2, 50) + 10:
            return {"signal": "none", "reason": "insufficient_bars"}

        c = df["close"]
        h = df["high"]
        l = df["low"]
        o = df["open"]
        v = df["volume"]

        ema_trend         = ema(c, EMA_TREND_LEN)
        ema_fast          = ema(c, EMA_FAST_LEN)
        atr_val           = atr(h, l, c, ATR_LEN)
        rsi_val           = rsi(c, RSI_LEN)
        dip, dim, adx_raw = dmi(h, l, c, DI_LEN, ADX_SMOOTH)
        adx_val           = ema(adx_raw, ADX_EMA)

        i = -2  # last confirmed bar (barstate.isconfirmed)

        atr_i   = atr_val.iloc[i]
        adx_i   = adx_val.iloc[i]
        rsi_i   = rsi_val.iloc[i]
        dip_i   = dip.iloc[i]
        dim_i   = dim.iloc[i]
        close_i = c.iloc[i]
        open_i  = o.iloc[i]
        high_i  = h.iloc[i]
        low_i   = l.iloc[i]
        vol_i   = v.iloc[i]
        ema_t_i = ema_trend.iloc[i]
        ema_f_i = ema_fast.iloc[i]

        trend_regime = adx_i > ADX_TREND_TH
        range_regime = adx_i < ADX_RANGE_TH

        atr_sma50 = atr_val.rolling(50).mean().iloc[i]
        vol_sma20 = v.rolling(20).mean().iloc[i]
        body      = abs(close_i - open_i)
        filters   = (
            atr_i < atr_sma50 * FILTER_ATR_MUL and
            vol_i > vol_sma20 and
            body  > atr_i * FILTER_BODY
        )

        prev_high = h.iloc[i - 1]
        prev_low  = l.iloc[i - 1]

        trend_long  = trend_regime and ema_f_i > ema_t_i and dip_i > dim_i and close_i > prev_high and filters
        trend_short = trend_regime and ema_f_i < ema_t_i and dim_i > dip_i and close_i < prev_low  and filters
        range_long  = range_regime and rsi_i < RSI_OS and filters
        range_short = range_regime and rsi_i > RSI_OB and filters

        if self.position == 0:
            if trend_long:
                signal_type = "trend_long"
            elif trend_short:
                signal_type = "trend_short"
            elif range_long:
                signal_type = "range_long"
            elif range_short:
                signal_type = "range_short"
            else:
                signal_type = "none"
        else:
            signal_type = "none"

        is_trend  = "trend" in signal_type if signal_type != "none" else False
        rr        = TREND_RR if is_trend else RANGE_RR
        atr_mult  = TREND_ATR_MUL if is_trend else RANGE_ATR_MUL
        stop_dist = min(atr_i * atr_mult, MAX_SL_POINTS)
        entry_price = close_i

        if "long" in signal_type:
            sl   = round(entry_price - stop_dist, 1)
            tp   = round(entry_price + stop_dist * rr, 1)
            side = "buy"
        elif "short" in signal_type:
            sl   = round(entry_price + stop_dist, 1)
            tp   = round(entry_price - stop_dist * rr, 1)
            side = "sell"
        else:
            sl = tp = side = None

        return {
            "signal":      signal_type,
            "side":        side,
            "entry_price": round(entry_price, 1),
            "sl":          sl,
            "tp":          tp,
            "atr":         round(atr_i, 2),
            "adx":         round(adx_i, 2),
            "rsi":         round(rsi_i, 2),
            "stop_dist":   round(stop_dist, 1),
            "lots":        self.lots,
            "timeframe":   self.timeframe,
            "regime":      "trend" if trend_regime else ("range" if range_regime else "neutral"),
        }

    def update_trail_stage(self, current_price, atr_val):
        if self.entry_price is None or self.position == 0:
            return 0
        profit_dist = (current_price - self.entry_price) if self.position > 0 else (self.entry_price - current_price)
        for stage in [5, 4, 3, 2, 1]:
            trigger = atr_val * TRAIL_STAGES[stage]["trigger"]
            if profit_dist >= trigger and self.trail_stage < stage:
                self.trail_stage = stage
                logger.info(f"Trail Stage → {stage} | Profit: {profit_dist:.1f} pts")
                break
        return self.trail_stage

    def get_trail_params(self, atr_val):
        stage = max(self.trail_stage, 1)
        return {
            "stage":  stage,
            "points": round(atr_val * TRAIL_STAGES[stage]["pts"], 1),
            "offset": round(atr_val * TRAIL_STAGES[stage]["off"], 1),
        }

    def check_breakeven(self, current_price, atr_val):
        if self.be_done or self.entry_price is None:
            return False
        be_trigger = atr_val * BE_MULT
        if self.position > 0 and current_price - self.entry_price > be_trigger:
            return True
        if self.position < 0 and self.entry_price - current_price > be_trigger:
            return True
        return False

    def check_max_sl(self, current_price, atr_val):
        if self.entry_price is None:
            return False
        max_dist = min(atr_val * MAX_SL_MULT, MAX_SL_POINTS)
        if self.position > 0 and current_price <= self.entry_price - max_dist:
            return True
        if self.position < 0 and current_price >= self.entry_price + max_dist:
            return True
        return False

    def on_entry(self, entry_price, side, signal_type):
        self.entry_price = entry_price
        self.position    = 1 if side == "buy" else -1
        self.trail_stage = 0
        self.be_done     = False
        self.entry_id    = signal_type
        logger.info(f"Position opened: {side.upper()} @ {entry_price} | {signal_type}")

    def on_exit(self):
        self.entry_price = None
        self.position    = 0
        self.trail_stage = 0
        self.be_done     = False
        self.entry_id    = None
        logger.info("Position closed. State reset.")
