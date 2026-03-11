"""
Delta India Exchange API Wrapper
No bracket orders — Entry + SL + TP as 3 separate orders.
"""

import time
import hmac
import hashlib
import requests
import json
import logging
from settings import (
    DELTA_API_KEY, DELTA_API_SECRET, DELTA_BASE_URL,
    PRODUCT_ID, LOT_SIZE_BTC, DEFAULT_LOTS
)

logger = logging.getLogger("DeltaExchange")


class DeltaIndiaClient:
    def __init__(self):
        self.api_key    = DELTA_API_KEY
        self.api_secret = DELTA_API_SECRET
        self.base_url   = DELTA_BASE_URL
        self.session    = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _sign(self, method, path, query, body, timestamp):
        # Signing message: method + timestamp + path (no query) + body
        # Query params are NOT included in the signature — matches Delta India API spec
        message = method + timestamp + path + body
        return hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

    def _headers(self, method, path, query="", body=""):
        timestamp = str(int(time.time()))
        sig = self._sign(method, path, query, body, timestamp)
        return {
            "api-key":      self.api_key,
            "timestamp":    timestamp,
            "signature":    sig,
            "Content-Type": "application/json",
        }

    def _request(self, method, path, params=None, data=None):
        url       = self.base_url + path
        query_str = ""
        body_str  = ""
        if params:
            query_str = "&".join(f"{k}={v}" for k, v in params.items())
            url += "?" + query_str
        if data:
            body_str = json.dumps(data)
        headers = self._headers(method.upper(), path, query_str, body_str)
        try:
            resp = self.session.request(
                method, url, headers=headers,
                data=body_str if body_str else None,
                timeout=10
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Delta API error: {e}")
            raise

    # ─── MARKET DATA ───────────────────────────────────────────────────────
    def get_ticker(self, symbol=None):
        sym = symbol or SYMBOL
        return self._request("GET", f"/v2/tickers/{sym}")

    def get_positions(self):
        return self._request("GET", "/v2/positions/margined")

    def get_open_orders(self, product_id=PRODUCT_ID):
        return self._request("GET", "/v2/orders",
                             params={"product_id": product_id, "state": "open"})

    @staticmethod
    def lots_to_btc(lots):
        return lots * LOT_SIZE_BTC

    # ─── STEP 1: MARKET ENTRY ──────────────────────────────────────────────
    def place_entry(self, side, lots):
        payload = {
            "product_id": PRODUCT_ID,
            "size":       lots,
            "side":       side,
            "order_type": "market_order",
        }
        logger.info(f"[ENTRY] {side.upper()} {lots} lots ({self.lots_to_btc(lots):.3f} BTC)")
        result = self._request("POST", "/v2/orders", data=payload)
        logger.info(f"[ENTRY] Result: {result}")
        return result

    # ─── STEP 2: STOP LOSS ─────────────────────────────────────────────────
    # FIX 1: stop_price and limit_price must be float, NOT str — str caused 400 errors
    # FIX 2: stop_trigger_method is required for stop_limit_order on Delta India v2 API
    def place_stop_loss(self, side, lots, stop_price):
        stop_price  = round(float(stop_price), 1)          # FIX 1: ensure float
        if side == "sell":
            limit_price = round(stop_price * 0.9985, 1)
        else:
            limit_price = round(stop_price * 1.0015, 1)
        payload = {
            "product_id":          PRODUCT_ID,
            "size":                lots,
            "side":                side,
            "order_type":          "stop_limit_order",
            "stop_price":          stop_price,             # FIX 1: float, not str
            "limit_price":         limit_price,            # FIX 1: float, not str
            "stop_trigger_method": "last_traded_price",    # FIX 2: required field
            "reduce_only":         True,
        }
        logger.info(f"[SL] {side.upper()} {lots} lots | Stop={stop_price} | Limit={limit_price}")
        result = self._request("POST", "/v2/orders", data=payload)
        logger.info(f"[SL] Result: {result}")
        return result

    # ─── STEP 3: TAKE PROFIT ───────────────────────────────────────────────
    def place_take_profit(self, side, lots, tp_price):
        tp_price = round(float(tp_price), 1)               # ensure float for consistency
        payload = {
            "product_id":  PRODUCT_ID,
            "size":        lots,
            "side":        side,
            "order_type":  "limit_order",
            "limit_price": tp_price,                       # float, not str
            "reduce_only": True,
        }
        logger.info(f"[TP] {side.upper()} {lots} lots | TP={tp_price}")
        result = self._request("POST", "/v2/orders", data=payload)
        logger.info(f"[TP] Result: {result}")
        return result

    # ─── STEP 4: AMEND SL (TRAIL) ──────────────────────────────────────────
    # FIX 3: was sending str() — Delta India API requires numeric types
    def amend_stop_loss(self, sl_order_id, new_stop, sl_side):
        new_stop  = round(float(new_stop), 1)              # FIX 3: ensure float
        if sl_side == "sell":
            new_limit = round(new_stop * 0.9985, 1)
        else:
            new_limit = round(new_stop * 1.0015, 1)
        payload = {
            "id":          sl_order_id,
            "stop_price":  new_stop,                       # FIX 3: float, not str
            "limit_price": new_limit,                      # FIX 3: float, not str
        }
        logger.info(f"[TRAIL] Amend SL → {new_stop} | Limit={new_limit}")
        return self._request("PUT", "/v2/orders", data=payload)

    # ─── STEP 5: CANCEL ORPHAN ─────────────────────────────────────────────
    def cancel_all_orders(self, product_id=PRODUCT_ID):
        logger.info(f"[CANCEL] All orders for product {product_id}")
        return self._request("DELETE", "/v2/orders", data={"product_id": product_id})

    # ─── EMERGENCY CLOSE ───────────────────────────────────────────────────
    def close_position(self, product_id=PRODUCT_ID):
        positions = self.get_positions()
        for pos in positions.get("result", []):
            if pos["product_id"] == product_id and float(pos.get("size", 0)) != 0:
                size = abs(int(pos["size"]))
                side = "sell" if float(pos["size"]) > 0 else "buy"
                logger.warning(f"[CLOSE] Emergency: {side.upper()} {size} lots")
                return self.place_entry(side=side, lots=size)
        logger.warning("[CLOSE] No open position found.")
        return {}

    def get_position_size(self, product_id=PRODUCT_ID):
        try:
            positions = self.get_positions()
            for pos in positions.get("result", []):
                if pos["product_id"] == product_id:
                    return float(pos.get("size", 0))
        except Exception as e:
            logger.error(f"get_position_size failed: {e}")
        return 0.0
