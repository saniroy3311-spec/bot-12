"""
Live Bot Loop — flat imports, no subfolders
"""

import logging
import time
import threading
from datetime import datetime, timezone

logger = logging.getLogger("LiveLoop")

TF_SECONDS = {
    "1":    60,    "3":   180,   "5":   300,
    "15":   900,   "30":  1800,  "60":  3600,
    "240":  14400, "1440":86400,
}


def seconds_until_next_bar(tf_str):
    bar_secs  = TF_SECONDS.get(str(tf_str), 300)
    now_ts    = datetime.now(timezone.utc).timestamp()
    elapsed   = now_ts % bar_secs
    remaining = bar_secs - elapsed
    return remaining + 2.0


class LiveLoop:
    def __init__(self, order_manager, timeframe="5"):
        self.om          = order_manager
        self.timeframe   = str(timeframe)
        self._running    = False
        self._thread     = None
        self.bar_count   = 0
        self.last_signal = "none"

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info(f"LiveLoop started | timeframe={self.timeframe}m")

    def stop(self):
        self._running = False
        logger.info("LiveLoop stopped.")

    def _loop(self):
        while self._running:
            wait = seconds_until_next_bar(self.timeframe)
            logger.info(f"Next bar in {wait:.1f}s ...")
            time.sleep(wait)
            if not self._running:
                break
            self._on_bar_close()

    def _on_bar_close(self):
        self.bar_count += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[Bar #{self.bar_count}] {now} — Computing signal...")

        try:
            df     = self.om._fetch_ohlcv(self.timeframe)
            info   = self.om.engine.compute(df)
            signal = info.get("signal", "none")

            logger.info(
                f"Signal={signal} | ADX={info.get('adx')} | "
                f"RSI={info.get('rsi')} | ATR={info.get('atr')} | "
                f"Regime={info.get('regime')}"
            )

            if signal != "none" and self.om.engine.position == 0:
                logger.info(f">>> SIGNAL FIRED: {signal.upper()} <<<")
                self.om.handle_signal(
                    signal    = signal,
                    price     = info["entry_price"],
                    timeframe = self.timeframe,
                    lots      = self.om.lots,
                )
                self.last_signal = signal

            elif self.om.engine.position != 0:
                current_price = self.om._get_last_price()
                self.om._check_trail(current_price)

            elif self.om.engine.position == 0 and self.om.sl_order_id is not None:
                logger.info("Orphan order detected — cancelling.")
                self.om.delta.cancel_all_orders()
                self.om._reset_order_state()

        except Exception as e:
            logger.error(f"Bar close error: {e}", exc_info=True)
