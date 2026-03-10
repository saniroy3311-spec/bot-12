# ==============================================
# BTCUSDT SNIPER v6 BOT — CONFIG
# ==============================================

# ─── DELTA INDIA API ───────────────────────────
DELTA_API_KEY    = "YOUR_DELTA_API_KEY"
DELTA_API_SECRET = "YOUR_DELTA_API_SECRET"
DELTA_BASE_URL   = "https://api.india.delta.exchange"

# ─── PRODUCT CONFIG ────────────────────────────
SYMBOL           = "BTCUSDT"
PRODUCT_ID       = 27
LOT_SIZE_BTC     = 0.001

# ══════════════════════════════════════════════
#   CHANGE THESE 2 TO SET LOT SIZE & TIMEFRAME
# ══════════════════════════════════════════════
DEFAULT_LOTS      = 100         # 100 lots = 0.1 BTC
DEFAULT_TIMEFRAME = "5"         # "1","3","5","15","30","60","240","1440"
# ══════════════════════════════════════════════

# ─── EMA (match your TradingView inputs) ───────
EMA_TREND_LEN    = 130
EMA_FAST_LEN     = 161

# ─── INDICATORS ────────────────────────────────
ATR_LEN          = 14
DI_LEN           = 14
ADX_SMOOTH       = 14
ADX_EMA          = 5
RSI_LEN          = 14

# ─── SIGNAL THRESHOLDS ─────────────────────────
ADX_TREND_TH     = 22
ADX_RANGE_TH     = 18
RSI_OB           = 70
RSI_OS           = 30

# ─── ENTRY FILTERS ─────────────────────────────
FILTER_ATR_MUL   = 1.4
FILTER_BODY      = 0.5

# ─── SL / TP ───────────────────────────────────
TREND_RR         = 4.0
RANGE_RR         = 2.5
TREND_ATR_MUL    = 0.6
RANGE_ATR_MUL    = 0.5

# ─── 5-STAGE TRAIL ─────────────────────────────
TRAIL_STAGES = {
    1: {"trigger": 0.8,  "pts": 0.5,  "off": 0.4},
    2: {"trigger": 1.5,  "pts": 0.4,  "off": 0.3},
    3: {"trigger": 2.5,  "pts": 0.3,  "off": 0.25},
    4: {"trigger": 4.0,  "pts": 0.2,  "off": 0.15},
    5: {"trigger": 6.0,  "pts": 0.15, "off": 0.1},
}

# ─── RISK MANAGEMENT ───────────────────────────
BE_MULT          = 0.6
MAX_SL_MULT      = 1.5
MAX_SL_POINTS    = 500.0

# ─── GOOGLE SHEETS ─────────────────────────────
GOOGLE_SHEET_ID           = "YOUR_GOOGLE_SHEET_ID"
GOOGLE_CREDENTIALS_FILE   = "google_credentials.json"
SHEET_TRADE_TAB           = "Trade History"
SHEET_SUMMARY_TAB         = "Summary"
