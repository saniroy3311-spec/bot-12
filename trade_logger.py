"""
Google Sheets Trade Logger
Reads credentials from GOOGLE_CREDENTIALS_JSON environment variable
(no json file needed on disk)
"""

import logging
import os
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from settings import (
    GOOGLE_SHEET_ID, SHEET_TRADE_TAB, SHEET_SUMMARY_TAB
)

logger = logging.getLogger("SheetsLogger")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "Date", "Time (IST)", "Signal Type", "Side", "Timeframe",
    "Entry Price", "Stop Loss", "Take Profit", "Lots", "BTC Size",
    "ATR", "ADX", "RSI", "Regime", "Trail Stage at Exit",
    "Exit Price", "Exit Reason", "PnL (USDT)", "PnL (R)", "Status"
]


class SheetsLogger:
    def __init__(self):
        self.client = None
        self.sheet  = None
        self._connect()

    def _connect(self):
        try:
            # Read credentials from environment variable (set in Render)
            creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
            if not creds_json:
                logger.warning("GOOGLE_CREDENTIALS_JSON env var not set. Sheets disabled.")
                return

            creds_dict = json.loads(creds_json)
            creds      = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            self.client = gspread.authorize(creds)
            self.sheet  = self.client.open_by_key(GOOGLE_SHEET_ID)
            self._ensure_tabs()
            logger.info("Google Sheets connected.")
        except Exception as e:
            logger.error(f"Google Sheets connection failed: {e}")
            self.sheet = None

    def _ensure_tabs(self):
        existing = [ws.title for ws in self.sheet.worksheets()]
        if SHEET_TRADE_TAB not in existing:
            ws = self.sheet.add_worksheet(title=SHEET_TRADE_TAB, rows=5000, cols=25)
            ws.insert_row(HEADERS, 1)
            logger.info(f"Created tab: {SHEET_TRADE_TAB}")
        if SHEET_SUMMARY_TAB not in existing:
            ws = self.sheet.add_worksheet(title=SHEET_SUMMARY_TAB, rows=50, cols=10)
            summary_headers = [
                ["Metric", "Value"],
                ["Total Trades", "=COUNTA('Trade History'!A:A)-1"],
                ["Win Rate", "=COUNTIF('Trade History'!T:T,\"WIN\")/COUNTA('Trade History'!A:A)-1"],
                ["Total PnL (USDT)", "=SUM('Trade History'!R:R)"],
                ["Avg PnL per Trade", "=AVERAGE('Trade History'!R:R)"],
                ["Best Trade (USDT)", "=MAX('Trade History'!R:R)"],
                ["Worst Trade (USDT)", "=MIN('Trade History'!R:R)"],
                ["Total Lots Traded", "=SUM('Trade History'!I:I)"],
                ["Trend Trades", "=COUNTIF('Trade History'!C:C,\"trend*\")"],
                ["Range Trades", "=COUNTIF('Trade History'!C:C,\"range*\")"],
            ]
            ws.update("A1:B10", summary_headers)
            logger.info(f"Created tab: {SHEET_SUMMARY_TAB}")

    def log_entry(self, trade):
        if not self.sheet:
            logger.warning("Sheets not connected. Trade not logged.")
            return False
        try:
            ws  = self.sheet.worksheet(SHEET_TRADE_TAB)
            now = datetime.now()
            row = [
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                trade.get("signal_type", ""),
                trade.get("side", "").upper(),
                trade.get("timeframe", ""),
                trade.get("entry_price", ""),
                trade.get("sl", ""),
                trade.get("tp", ""),
                trade.get("lots", ""),
                round(trade.get("lots", 0) * 0.001, 3),
                trade.get("atr", ""),
                trade.get("adx", ""),
                trade.get("rsi", ""),
                trade.get("regime", ""),
                "", "", "", "", "", "OPEN"
            ]
            ws.append_row(row, value_input_option="USER_ENTERED")
            logger.info(f"Trade logged: {trade.get('signal_type')} @ {trade.get('entry_price')}")
            return True
        except Exception as e:
            logger.error(f"log_entry failed: {e}")
            return False

    def update_exit(self, entry_price, exit_price, exit_reason,
                    trail_stage, side, lots, stop_dist):
        if not self.sheet:
            return False
        try:
            ws   = self.sheet.worksheet(SHEET_TRADE_TAB)
            data = ws.get_all_values()
            for i in range(len(data) - 1, 0, -1):
                if data[i][19] == "OPEN" and str(data[i][5]) == str(entry_price):
                    row_num = i + 1
                    if side.lower() == "buy":
                        pnl_usdt = (exit_price - entry_price) * lots * 0.001
                    else:
                        pnl_usdt = (entry_price - exit_price) * lots * 0.001
                    pnl_r  = round(pnl_usdt / (stop_dist * lots * 0.001), 2) if stop_dist else 0
                    status = "WIN" if pnl_usdt > 0 else ("LOSS" if pnl_usdt < 0 else "BE")
                    ws.update(f"O{row_num}:T{row_num}", [[
                        trail_stage, exit_price, exit_reason,
                        round(pnl_usdt, 2), pnl_r, status
                    ]])
                    logger.info(f"Exit logged: {exit_reason} @ {exit_price} | PnL: {pnl_usdt:.2f}")
                    return True
            logger.warning("No matching OPEN trade found.")
            return False
        except Exception as e:
            logger.error(f"update_exit failed: {e}")
            return False

    def log_error(self, message):
        if not self.sheet:
            return
        try:
            ws  = self.sheet.worksheet(SHEET_TRADE_TAB)
            now = datetime.now()
            ws.append_row([
                now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
                "ERROR", "", "", "", "", "", "", "", "", "",
                "", "", "", "", message, "", "", "ERROR"
            ])
        except Exception as e:
            logger.error(f"log_error failed: {e}")
