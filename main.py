"""
BTCUSDT Sniper v6 — Autonomous Bot
Exchange : Delta India
Orders   : Entry + SL + TP (3 separate orders)

To change lot size or timeframe — edit settings.py:
  DEFAULT_LOTS      = 100    ← change this
  DEFAULT_TIMEFRAME = "5"    ← change this
"""

import argparse
import logging
import sys
import time
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from order_manager import OrderManager
from live_loop import LiveLoop
from settings import DEFAULT_LOTS, DEFAULT_TIMEFRAME

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)-14s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("Main")

BANNER = """
╔══════════════════════════════════════════════╗
║      BTCUSDT SNIPER v6 — DELTA INDIA         ║
║   Entry + SL + TP Orders | 1:1 Pine Replica  ║
╚══════════════════════════════════════════════╝
"""

TF_MAP = {
    "1":"1m","3":"3m","5":"5m","15":"15m",
    "30":"30m","60":"1h","240":"4h","1440":"1D"
}


# ─── HEALTH SERVER (keeps Render free web service alive) ─────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running OK")
    def log_message(self, format, *args):
        pass  # suppress noisy access logs

def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health server running on port {port}")


# ─── ARGS ────────────────────────────────────────────────────────────────
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--lots", type=int, default=None)
    p.add_argument("--tf",   type=str, default=None, choices=list(TF_MAP.keys()))
    p.add_argument("--mode", type=str, default="live", choices=["live", "test"])
    return p.parse_args()


# ─── TEST MODE ───────────────────────────────────────────────────────────
def run_test_mode(lots, tf):
    logger.info("TEST MODE — No orders will be placed.")
    om     = OrderManager(lots=lots, timeframe=tf)
    df     = om._fetch_ohlcv(tf)
    result = om.engine.compute(df)

    print("\n" + "─" * 44)
    print("  SIGNAL RESULT")
    print("─" * 44)
    for k, v in result.items():
        print(f"  {k:<22}: {v}")
    print("─" * 44)
    if result["signal"] == "none":
        print("  → No signal on current bar.")
    else:
        print(f"  → SIGNAL : {result['signal'].upper()}")
        print(f"  → Entry  : {result['entry_price']}")
        print(f"  → SL     : {result['sl']}")
        print(f"  → TP     : {result['tp']}")
    print("─" * 44 + "\n")


# ─── LIVE MODE ───────────────────────────────────────────────────────────
def run_live_mode(lots, tf):
    # Start health server FIRST so Render sees the port immediately
    start_health_server()

    om   = OrderManager(lots=lots, timeframe=tf)
    loop = LiveLoop(order_manager=om, timeframe=tf)
    loop.start()

    logger.info(BANNER)
    logger.info(f"  Lots={lots} ({lots*0.001:.3f} BTC) | TF={TF_MAP[tf]} | LIVE")
    logger.info("Bot running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(5)
            if int(time.time()) % 600 < 5:
                pos     = om.engine.position
                pos_str = "LONG" if pos > 0 else ("SHORT" if pos < 0 else "FLAT")
                logger.info(
                    f"Heartbeat | {pos_str} | "
                    f"Stage={om.engine.trail_stage} | "
                    f"SL={om.open_sl} | Bar#{loop.bar_count}"
                )
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        loop.stop()
        if om.engine.position != 0:
            logger.warning("Open position — closing...")
            om.delta.cancel_all_orders()
            om._close_position(reason="Bot Shutdown")
        logger.info("Bot stopped.")


# ─── MAIN ────────────────────────────────────────────────────────────────
def main():
    args = parse_args()
    lots = args.lots if args.lots is not None else DEFAULT_LOTS
    tf   = args.tf   if args.tf   is not None else DEFAULT_TIMEFRAME

    if args.mode == "test":
        run_test_mode(lots, tf)
    else:
        run_live_mode(lots, tf)


if __name__ == "__main__":
    main()
