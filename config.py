import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Indodax
    INDODAX_API_KEY: str      = os.getenv("INDODAX_API_KEY", "")
    INDODAX_API_SECRET: str   = os.getenv("INDODAX_API_SECRET", "")
    INDODAX_DEMO: bool        = os.getenv("INDODAX_DEMO", "true").lower() == "true"

    # Anthropic
    ANTHROPIC_API_KEY: str    = os.getenv("ANTHROPIC_API_KEY", "")

    # Trading
    TRADING_PAIR: str             = os.getenv("TRADING_PAIR", "btc_idr").lower()
    TRADE_INTERVAL_SECONDS: int   = int(os.getenv("TRADE_INTERVAL_SECONDS", "300"))   # 5 min default
    MAX_POSITION_IDR: float       = float(os.getenv("MAX_POSITION_IDR", "100000"))
    RISK_PER_TRADE_PERCENT: float = float(os.getenv("RISK_PER_TRADE_PERCENT", "2.0"))
    MAX_DAILY_LOSS_IDR: float     = float(os.getenv("MAX_DAILY_LOSS_IDR", "50000"))

    # Safety
    DRY_RUN: bool              = os.getenv("DRY_RUN", "true").lower() == "true"
    MIN_AI_CONFIDENCE: int     = int(os.getenv("MIN_AI_CONFIDENCE", "70"))   # raised to 70
    STOP_LOSS_PERCENT: float   = float(os.getenv("STOP_LOSS_PERCENT", "1.5"))
    TAKE_PROFIT_PERCENT: float = float(os.getenv("TAKE_PROFIT_PERCENT", "2.5"))

    # Position review
    POSITION_REVIEW_SECONDS: int = int(os.getenv("POSITION_REVIEW_SECONDS", "300"))   # 5 min

    # Profit targeting — minimum 2% per trade
    USE_PROFIT_TARGET: bool        = os.getenv("USE_PROFIT_TARGET", "true").lower() == "true"
    MIN_PROFIT_PERCENT: float      = float(os.getenv("MIN_PROFIT_PERCENT", "2.0"))    # minimum 2%
    TARGET_PROFIT_MIN_IDR: float   = float(os.getenv("TARGET_PROFIT_MIN_IDR", "1000"))
    TARGET_PROFIT_MAX_IDR: float   = float(os.getenv("TARGET_PROFIT_MAX_IDR", "5000"))

    # Trailing stop-loss — locks in profit as price rises
    USE_TRAILING_STOP: bool        = os.getenv("USE_TRAILING_STOP", "true").lower() == "true"
    TRAILING_STOP_PERCENT: float   = float(os.getenv("TRAILING_STOP_PERCENT", "1.0"))  # trail 1% below peak

    # Entry filters — extra confirmation before buying
    MIN_VOLUME_RATIO: float        = float(os.getenv("MIN_VOLUME_RATIO", "1.2"))  # volume must be 1.2x avg
    MIN_MOMENTUM_SCORE: int        = int(os.getenv("MIN_MOMENTUM_SCORE", "3"))    # at least 3/5 signals aligned
    MAX_RSI_ENTRY: float           = float(os.getenv("MAX_RSI_ENTRY", "68.0"))    # don't buy overbought
    MIN_RSI_ENTRY: float           = float(os.getenv("MIN_RSI_ENTRY", "35.0"))    # don't buy in freefall

    # Indicator settings
    RSI_PERIOD: int     = 14
    EMA_FAST: int       = 12
    EMA_SLOW: int       = 26
    MACD_SIGNAL: int    = 9
    BB_PERIOD: int      = 20
    BB_STD: float       = 2.0
    KLINE_LIMIT: int    = 100
    KLINE_INTERVAL: str = "1"

    @property
    def base_currency(self) -> str:
        return self.TRADING_PAIR.split("_")[0]

    @property
    def api_base(self) -> str:
        host = "demo-indodax.com" if self.INDODAX_DEMO else "indodax.com"
        return f"https://{host}"

    @property
    def public_base(self) -> str:
        return "https://indodax.com"

    def validate(self):
        errors = []
        if not self.INDODAX_API_KEY:
            errors.append("INDODAX_API_KEY is not set")
        if not self.INDODAX_API_SECRET:
            errors.append("INDODAX_API_SECRET is not set")
        if not self.ANTHROPIC_API_KEY:
            errors.append("ANTHROPIC_API_KEY is not set")
        if self.MAX_POSITION_IDR < 10000:
            errors.append("MAX_POSITION_IDR must be at least 10000")
        if errors:
            raise ValueError("Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))


cfg = Config()
