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
    PRODUCT_ID, LOT_SIZE_BTC, DEFAULT_LOTS, SYMBOL
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
    # FIX 6: Enforce minimum SL distance from current price to avoid 400 Bad Request.
    #         Delta India rejects SL orders where stop_price is too close to (or past)
    #         the last traded price. We fetch the ticker, push the SL away by at least
    #         MIN_SL_DISTANCE points, and retry once with a wider buffer if the first
    #         attempt still fails with a 400.
    MIN_SL_DISTANCE = 50.0   # minimum points between current price and SL stop_price

    def place_stop_loss(self, side, lots, stop_price):
        stop_price = round(float(stop_price), 1)           # FIX 1: ensure float

        # FIX 6a: Clamp SL away from current price by at least MIN_SL_DISTANCE
        try:
            ticker        = self.get_ticker()
            current_price = float(ticker["result"]["close"])
            if side == "sell":   # long position SL — must be BELOW current price
                min_sl = round(current_price - self.MIN_SL_DISTANCE, 1)
                if stop_price > min_sl:
                    logger.warning(
                        f"[SL] stop_price {stop_price} too close to market {current_price}. "
                        f"Clamping to {min_sl}"
                    )
                    stop_price = min_sl
            else:                # short position SL — must be ABOVE current price
                min_sl = round(current_price + self.MIN_SL_DISTANCE, 1)
                if stop_price < min_sl:
                    logger.warning(
                        f"[SL] stop_price {stop_price} too close to market {current_price}. "
                        f"Clamping to {min_sl}"
                    )
                    stop_price = min_sl
        except Exception as ticker_err:
            logger.warning(f"[SL] Could not fetch ticker for SL clamp check: {ticker_err}. Proceeding with original price.")

        def _build_and_send(sp):
            sp = round(float(sp), 1)
            if side == "sell":
                lp = round(sp * 0.9985, 1)
            else:
                lp = round(sp * 1.0015, 1)
            payload = {
                "product_id":          PRODUCT_ID,
                "size":                lots,
                "side":                side,
                "order_type":          "stop_limit_order",
                "stop_price":          sp,                  # FIX 1: float, not str
                "limit_price":         lp,                  # FIX 1: float, not str
                "stop_trigger_method": "last_traded_price", # FIX 2: required field
                "close_on_trigger":    True,                # FIX 7: Delta India v2 uses close_on_trigger not reduce_only for stop orders
            }
            logger.info(f"[SL] {side.upper()} {lots} lots | Stop={sp} | Limit={lp}")
            result = self._request("POST", "/v2/orders", data=payload)
            logger.info(f"[SL] Result: {result}")
            return result

        try:
            return _build_and_send(stop_price)
        except Exception as first_err:
            # FIX 6b: First attempt failed — widen SL by extra MIN_SL_DISTANCE and retry once
            logger.warning(f"[SL] First attempt failed ({first_err}). Retrying with wider SL buffer.")
            if side == "sell":
                wider_sl = round(stop_price - self.MIN_SL_DISTANCE, 1)
            else:
                wider_sl = round(stop_price + self.MIN_SL_DISTANCE, 1)
            return _build_and_send(wider_sl)

    # ─── STEP 3: TAKE PROFIT ───────────────────────────────────────────────
    def place_take_profit(self, side, lots, tp_price):
        tp_price = round(float(tp_price), 1)               # ensure float for consistency
        payload = {
            "product_id":  PRODUCT_ID,
            "size":        lots,
            "side":        side,
            "order_type":  "limit_order",
            "limit_price": tp_price,                       # float, not str
            "close_on_trigger": True,  # FIX 7: use close_on_trigger for reduce-only limit orders on Delta India v2
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
