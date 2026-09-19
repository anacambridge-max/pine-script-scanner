from dataclasses import dataclass

@dataclass(frozen=True)
class PrimeConfig:
    allow_1m: bool = True
    allow_3m: bool = True
    allow_5m: bool = True
    timezone: str = "Asia/Kolkata"
    scan_start: str = "09:15"
    scan_end: str = "09:55"
    signal_mode: str = "FAST PRIME"

    volume_length: int = 20
    standard_volume_multiple: float = 1.5
    extreme_volume_multiple: float = 2.5
    use_special_0915_rvol: bool = True

    minimum_body_ratio: float = 0.50
    minimum_close_location: float = 0.60
    range_expansion_ratio: float = 1.30
    range_average_length: int = 10
    compression_lookback: int = 3

    use_pd: bool = True
    use_weekly: bool = True
    use_monthly: bool = True
    use_52_week: bool = True
    use_ath: bool = True
    break_trigger_mode: str = "Close Confirmed"
    level_buffer_pct: float = 0.0
    require_follow_through: bool = False

    use_opening_candle: bool = True
    use_master_candle: bool = True
    master_lookback: int = 5
    master_range_multiplier: float = 1.50
    master_needs_extreme_volume: bool = True

    use_ema_filter: bool = True
    ema_length: int = 20
    ema_full_separation_pct: float = 1.0

    enable_fake_breakout: bool = True
    fake_lookback: int = 3

    sl_mode: str = "STRUCTURE + ATR"
    atr_sl_multiplier: float = 0.25
    target1_r: float = 1.0
    target2_r: float = 2.0
    target3_r: float = 3.0

    prime_threshold: float = 70.0
    account_size: float = 500000.0
    risk_percent: float = 0.5
    use_risk_quantity: bool = True

    enable_extra_confirmation: bool = False
    use_vwap_filter: bool = True
    use_rsi_filter: bool = True
    rsi_length: int = 14
    rsi_overbought: float = 80.0
    rsi_oversold: float = 20.0
    use_htf_trend_filter: bool = True
    htf_ema_length: int = 20
    use_volume_trend_filter: bool = True
    volume_trend_lookback: int = 3
    use_atr_filter: bool = True
    atr_length: int = 14

    def timeframe_allowed(self, minutes: int) -> bool:
        return (
            (minutes == 1 and self.allow_1m)
            or (minutes == 3 and self.allow_3m)
            or (minutes == 5 and self.allow_5m)
        )
