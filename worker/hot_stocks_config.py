"""Tunable rules for the pre-market Hot Stocks module only."""
from datetime import time
IST = "Asia/Kolkata"
TOP_N = 5
MIN_TECH_SCORE = 55
MAX_NEWS_AGE_HOURS = 24
PREOPEN_CUTOFF = time(9, 0)
PREVIOUS_SESSION_CLOSE = time(15, 30)
RECENCY_WEIGHTS = ((6, 1.0), (12, 0.8), (24, 0.6))
TITLE_MATCH_FACTOR = 1.0
BODY_MATCH_FACTOR = 0.5
NEWS_SCORE_MAX = 30
NEWS_TIER_POINTS = {"MATERIAL EVENT": 28, "STRONG CATALYST": 21, "GENERAL MENTION": 7}
TECHNICAL_WEIGHTS = {"volume": 0.25, "body": 0.20, "range": 0.15, "compression": 0.15, "proximity": 0.15, "move": 0.10}
# Update using the official NSE holiday calendar each year. ISO date strings.
NSE_HOLIDAYS = {
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26",
    "2026-03-31", "2026-04-03", "2026-04-14", "2026-05-01",
    "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02",
    "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
}
SEEN_NEWS_RETENTION_DAYS = 10
MIN_AVG_DAILY_VOLUME = 0
EXCLUDE_RESULTS_DAY = False
EXCLUDE_FO_BAN = False
EXCLUDE_LOW_LIQUIDITY = False
POSITIVE_KEYWORDS = ("order win", "order worth", "new order", "contract win", "approval", "approved", "acquisition", "upgrade", "profit jumps", "मिला ऑर्डर", "ऑर्डर मिला", "मंजूरी", "मुनाफा बढ़ा", "अधिग्रहण", "अपग्रेड")
NEGATIVE_KEYWORDS = ("downgrade", "penalty", "show cause", "fraud", "default", "profit falls", "earnings risk", "commission cap", "investigation", "probe", "stake sale", "जुर्माना", "जांच", "गिरावट", "मुनाफा घटा", "नियामकीय कार्रवाई")
MATERIAL_KEYWORDS = ("results", "quarterly results", "merger", "demerger", "block deal", "bulk deal", "promoter stake", "stake sale", "sebi", "irdai", "regulatory action", "large order", "major contract", "guidance", "dividend", "capacity expansion", "नतीजे", "तिमाही नतीजे", "ब्लॉक डील", "बल्क डील", "सेबी", "इरडाई", "बड़ा ऑर्डर", "प्रमोटर हिस्सेदारी", "विलय", "लाभांश")
STRONG_KEYWORDS = ("upgrade", "downgrade", "target price", "guidance", "contract", "order win", "brokerage", "rating", "large deal", "रेटिंग", "टारगेट प्राइस")
