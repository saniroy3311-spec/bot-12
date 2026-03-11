"""
Order Manager — flat imports, no subfolders
Data source: Delta India (not Binance)
"""

import logging
import time
import requests
import pandas as pd
from settings import SYMBOL, DEFAULT_LOTS, DEFAULT_TIMEFRAME, DELTA_BASE_URL, PRODUCT_ID

# Delta India resolution map: integer minutes → API string
_TF_MAP = {
    "1":    "1m",
    "3":    "3m",
    "5":    "5m",
    "15":   "15m",
    "30":   "30m",
    "60":   "1h",
    "120":  "2h",
    "240":  "4h",
    "360":  "6h",
    "1440": "1d",
}
from signal_engine import SignalEngine
from delta_india import DeltaIndiaClient
from trade_logger import SheetsLogger

logger = logging.getLogger("OrderManager")


class OrderManager:
    def __init__(self, lots=DEFAULT_LOTS, timeframe=DEFAULT_TIMEFRAME):
        self.lots      = lots
        self.timeframe = timeframe
        self.engine    = SignalEngine(lots=lots, timeframe=timeframe)
        self.delta     = DeltaIndiaClient()
        self.sheets    = SheetsLogger()

        self.sl_order_id = None
        self.tp_order_id = None
        self.sl_side     = None
        self.tp_side     = None
        self.open_sl     = None
        self.open_tp     = None
        self.stop_dist   = None

        logger.info(f"OrderManager ready | lots={lots} | tf={timeframe}m")

    def handle_signal(self, signal, price, timeframe, lots, comment=""):
        active_lots = lots if lots else self.lots
        if signal in ("trend_long", "range_long"):
            return self._open_long(signal, price, active_lots, timeframe)
        elif signal in ("trend_short", "range_short"):
            return self._open_short(signal, price, active_lots, timeframe)
        elif signal == "close":
            return self._close_position(reason="Manual Close")
        else:
            return {"status": "ignored", "signal": signal}

    def _open_long(self, signal_type, price, lots, timeframe):
        if self.engine.position != 0:
            return {"status": "skip", "reason": "already_in_trade"}
        df   = self._fetch_ohlcv(timeframe)
        info = self.engine.compute(df)
        sl        = info["sl"] or round(price - info["stop_dist"], 1)
        tp        = info["tp"] or round(price + info["stop_dist"] * 4.0, 1)
        stop_dist = info["stop_dist"]
        try:
            entry_order      = self.delta.place_entry(side="buy", lots=lots)
            entry_price      = float(entry_order.get("result", {}).get("average_fill_price", price))
            sl_result        = self.delta.place_stop_loss(side="sell", lots=lots, stop_price=sl)
            self.sl_order_id = sl_result.get("result", {}).get("id")
            self.sl_side     = "sell"
            tp_result        = self.delta.place_take_profit(side="sell", lots=lots, tp_price=tp)
            self.tp_order_id = tp_result.get("result", {}).get("id")
            self.tp_side     = "sell"
            self.engine.on_entry(entry_price, "buy", signal_type)
            self.open_sl   = sl
            self.open_tp   = tp
            self.stop_dist = stop_dist
            self.sheets.log_entry({
                "signal_type": signal_type, "side": "buy",
                "timeframe": timeframe, "entry_price": entry_price,
                "sl": sl, "tp": tp, "lots": lots,
                "atr": info["atr"], "adx": info["adx"],
                "rsi": info["rsi"], "regime": info["regime"],
            })
            logger.info(f"LONG OPEN @ {entry_price} | SL={sl} | TP={tp}")
            return {"status": "executed", "side": "buy", "entry": entry_price, "sl": sl, "tp": tp}
        except Exception as e:
            logger.error(f"Open long failed: {e}")
            self.sheets.log_error(f"Open long failed: {e}")
            return {"status": "error", "msg": str(e)}

    def _open_short(self, signal_type, price, lots, timeframe):
        if self.engine.position != 0:
            return {"status": "skip", "reason": "already_in_trade"}
        df   = self._fetch_ohlcv(timeframe)
        info = self.engine.compute(df)
        sl        = info["sl"] or round(price + info["stop_dist"], 1)
        tp        = info["tp"] or round(price - info["stop_dist"] * 4.0, 1)
        stop_dist = info["stop_dist"]
        try:
            entry_order      = self.delta.place_entry(side="sell", lots=lots)
            entry_price      = float(entry_order.get("result", {}).get("average_fill_price", price))
            sl_result        = self.delta.place_stop_loss(side="buy", lots=lots, stop_price=sl)
            self.sl_order_id = sl_result.get("result", {}).get("id")
            self.sl_side     = "buy"
            tp_result        = self.delta.place_take_profit(side="buy", lots=lots, tp_price=tp)
            self.tp_order_id = tp_result.get("result", {}).get("id")
            self.tp_side     = "buy"
            self.engine.on_entry(entry_price, "sell", signal_type)
            self.open_sl   = sl
            self.open_tp   = tp
            self.stop_dist = stop_dist
            self.sheets.log_entry({
                "signal_type": signal_type, "side": "sell",
                "timeframe": timeframe, "entry_price": entry_price,
                "sl": sl, "tp": tp, "lots": lots,
                "atr": info["atr"], "adx": info["adx"],
                "rsi": info["rsi"], "regime": info["regime"],
            })
            logger.info(f"SHORT OPEN @ {entry_price} | SL={sl} | TP={tp}")
            return {"status": "executed", "side": "sell", "entry": entry_price, "sl": sl, "tp": tp}
        except Exception as e:
            logger.error(f"Open short failed: {e}")
            self.sheets.log_error(f"Open short failed: {e}")
            return {"status": "error", "msg": str(e)}

    def _close_position(self, reason="Signal", exit_price=None):
        if self.engine.position == 0:
            return {"status": "skip", "reason": "no_position"}
        try:
            self.delta.cancel_all_orders()
            self.delta.close_position()
            price = exit_price or self._get_last_price()
            self.sheets.update_exit(
                entry_price = self.engine.entry_price,
                exit_price  = price,
                exit_reason = reason,
                trail_stage = self.engine.trail_stage,
                side        = "buy" if self.engine.position > 0 else "sell",
                lots        = self.lots,
                stop_dist   = self.stop_dist or 0,
            )
            self.engine.on_exit()
            self._reset_order_state()
            logger.info(f"Position closed. Reason: {reason} @ {price}")
            return {"status": "closed", "reason": reason, "exit_price": price}
        except Exception as e:
            logger.error(f"Close position failed: {e}")
            return {"status": "error", "msg": str(e)}

    def _check_trail(self, current_price):
        if self.engine.position == 0:
            logger.info("Position flat — cancelling orphan orders.")
            self.delta.cancel_all_orders()
            price = self._get_last_price()
            self.sheets.update_exit(
                entry_price = self.engine.entry_price,
                exit_price  = price,
                exit_reason = "SL or TP Hit",
                trail_stage = self.engine.trail_stage,
                side        = "buy" if self.engine.position > 0 else "sell",
                lots        = self.lots,
                stop_dist   = self.stop_dist or 0,
            )
            self.engine.on_exit()
            self._reset_order_state()
            return {"status": "exited", "reason": "SL or TP Hit"}

        df      = self._fetch_ohlcv(self.timeframe)
        atr_val = self.engine.compute(df).get("atr", 0)
        if not atr_val:
            return {"status": "skip", "reason": "no_atr"}

        stage        = self.engine.update_trail_stage(current_price, atr_val)
        trail_params = self.engine.get_trail_params(atr_val)
        trail_pts    = trail_params["points"]
        trail_off    = trail_params["offset"]

        if self.engine.position > 0:
            new_sl = round(current_price - trail_pts - trail_off, 1)
            if new_sl > self.open_sl:
                self._amend_sl(new_sl)
        else:
            new_sl = round(current_price + trail_pts + trail_off, 1)
            if new_sl < self.open_sl:
                self._amend_sl(new_sl)

        if self.engine.check_breakeven(current_price, atr_val) and not self.engine.be_done:
            be_price = self.engine.entry_price
            logger.info(f"Breakeven → SL moved to {be_price}")
            if self.engine.position > 0 and be_price > self.open_sl:
                self._amend_sl(be_price)
            elif self.engine.position < 0 and be_price < self.open_sl:
                self._amend_sl(be_price)
            self.engine.be_done = True

        if self.engine.check_max_sl(current_price, atr_val):
            logger.warning("Max SL hit — closing.")
            return self._close_position(reason="Max SL Hit", exit_price=current_price)

        return {"status": "ok", "trail_stage": stage, "sl": self.open_sl}

    def _amend_sl(self, new_sl):
        if not self.sl_order_id:
            return
        try:
            self.delta.amend_stop_loss(self.sl_order_id, new_sl, self.sl_side)
            self.open_sl = new_sl
            logger.info(f"SL amended → {new_sl}")
        except Exception as e:
            logger.error(f"SL amend failed: {e}")

    def _reset_order_state(self):
        self.sl_order_id = None
        self.tp_order_id = None
        self.sl_side     = None
        self.tp_side     = None
        self.open_sl     = None
        self.open_tp     = None
        self.stop_dist   = None

    # ═══════════════════════════════════════════════════════════════════════
    # OHLCV FROM DELTA INDIA (no Binance!)
    # Delta India endpoint: GET /v2/history/candles
    # resolution: 1, 3, 5, 15, 30, 60, 240, 1440 (minutes)
    # ═══════════════════════════════════════════════════════════════════════
    def _fetch_ohlcv(self, timeframe=None):
        tf_key = str(timeframe or self.timeframe)
        # Map integer-minute string to Delta India resolution format (e.g. "5" → "5m")
        resolution = _TF_MAP.get(tf_key, tf_key + "m")
        try:
            # Delta India candles API requires start/end Unix timestamps, not limit
            end_ts   = int(time.time())
            # Fetch ~500 candles worth of history
            start_ts = end_ts - (500 * int(tf_key) * 60)
            url    = f"{DELTA_BASE_URL}/v2/history/candles"
            params = {
                "resolution": resolution,
                "symbol":     SYMBOL,
                "start":      start_ts,
                "end":        end_ts,
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            candles = data.get("result", [])
            if not candles:
                raise ValueError(f"No candles returned from Delta India for {SYMBOL} resolution={resolution}")

            df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume"])
            df = df.rename(columns={"time": "timestamp"})
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
            df = df.sort_values("timestamp").reset_index(drop=True)

            # Cast to float
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)

            logger.info(f"Fetched {len(df)} candles from Delta India | resolution={resolution}")
            return df

        except Exception as e:
            logger.error(f"Delta India OHLCV fetch failed: {e}")
            raise

    def _get_last_price(self):
        try:
            ticker = self.delta.get_ticker(SYMBOL)
            return float(ticker["result"]["close"])
        except Exception:
            return 0.0
