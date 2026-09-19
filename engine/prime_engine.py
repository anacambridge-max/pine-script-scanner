from __future__ import annotations

from dataclasses import asdict
from datetime import time
from typing import Any
import math
import numpy as np
import pandas as pd

from .config import PrimeConfig


class PrimeEngine:
    """Broker-neutral implementation of Prime Technical — Institutional V2.

    Input dataframe columns:
      timestamp, open, high, low, close, volume

    Timestamps should be timezone-aware. Naive timestamps are interpreted
    as Asia/Kolkata.
    """

    def __init__(self, config: PrimeConfig | None = None):
        self.cfg = config or PrimeConfig()

    @staticmethod
    def _ema(s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=n, adjust=False, min_periods=0).mean()

    @staticmethod
    def _sma(s: pd.Series, n: int) -> pd.Series:
        return s.rolling(n, min_periods=1).mean()

    @staticmethod
    def _rsi(s: pd.Series, n: int) -> pd.Series:
        d = s.diff()
        up = d.clip(lower=0)
        dn = -d.clip(upper=0)
        au = up.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
        ad = dn.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
        rs = au / ad.replace(0, np.nan)
        return 100 - 100 / (1 + rs)

    @staticmethod
    def _atr(df: pd.DataFrame, n: int) -> pd.Series:
        prev = df["close"].shift(1)
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - prev).abs(),
            (df["low"] - prev).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean()

    def _prepare(self, df: pd.DataFrame, timeframe_minutes: int) -> pd.DataFrame:
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing OHLCV columns: {sorted(missing)}")
        if not self.cfg.timeframe_allowed(timeframe_minutes):
            raise ValueError("Prime Technical only allows 1m/3m/5m timeframes")

        x = df.copy().sort_values("timestamp").reset_index(drop=True)
        ts = pd.to_datetime(x["timestamp"])
        if ts.dt.tz is None:
            ts = ts.dt.tz_localize(self.cfg.timezone)
        else:
            ts = ts.dt.tz_convert(self.cfg.timezone)
        x["timestamp"] = ts
        return x

    def _levels(self, x: pd.DataFrame, context: pd.DataFrame | None = None) -> dict[str, float]:
        ts = x["timestamp"].iloc[-1]
        day = ts.date()
        prev_day = day - pd.Timedelta(days=1)

        # These are derived from the supplied history. The broker layer should
        # seed enough historical data before the live scan begins.
        d = x[x.timestamp.dt.date < day]
        pdh = float(d.high[d.timestamp.dt.date == prev_day].max()) if not d.empty else math.nan
        pdl = float(d.low[d.timestamp.dt.date == prev_day].min()) if not d.empty else math.nan

        prior_week = x[x.timestamp.dt.to_period("W-SUN") < ts.to_period("W-SUN")]
        prior_month = x[x.timestamp.dt.to_period("M") < ts.to_period("M")]
        weekly_high = float(prior_week.high.max()) if not prior_week.empty else math.nan
        weekly_low = float(prior_week.low.min()) if not prior_week.empty else math.nan
        monthly_high = float(prior_month.high.max()) if not prior_month.empty else math.nan
        monthly_low = float(prior_month.low.min()) if not prior_month.empty else math.nan

        # Pine's weekly 52-period highest/lowest and daily 5000-bar extremes
        # are represented from the available pre-current-period history.
        weeks = prior_week.groupby(prior_week.timestamp.dt.to_period("W-SUN"))
        weekly_hi = weeks.high.max().tail(52).max() if len(weeks) else math.nan
        weekly_lo = weeks.low.min().tail(52).min() if len(weeks) else math.nan
        hist = d
        ath = float(hist.high.max()) if not hist.empty else math.nan
        atl = float(hist.low.min()) if not hist.empty else math.nan
        return {
            "pdh": pdh, "pdl": pdl,
            "weekly_high": weekly_high, "weekly_low": weekly_low,
            "monthly_high": monthly_high, "monthly_low": monthly_low,
            "year_high": float(weekly_hi) if pd.notna(weekly_hi) else math.nan,
            "year_low": float(weekly_lo) if pd.notna(weekly_lo) else math.nan,
            "ath": ath, "atl": atl,
        }

    @staticmethod
    def _cross_up(close: float, high: float, level: float, mode: str, buffer: float) -> bool:
        if pd.isna(level):
            return False
        return high >= level if mode == "Wick Touch" else close > level * (1 + buffer / 100)

    @staticmethod
    def _cross_down(close: float, low: float, level: float, mode: str, buffer: float) -> bool:
        if pd.isna(level):
            return False
        return low <= level if mode == "Wick Touch" else close < level * (1 - buffer / 100)

    def _structure_levels(self, x: pd.DataFrame) -> tuple[float, float]:
        """Simple recent structure levels used for risk only.

        SMC/BOS/sweep/FVG/order-block analysis is intentionally not part of
        this scanner. Risk can still use recent swing structure without SMC.
        """
        lookback = min(20, max(5, len(x) - 1))
        recent = x.iloc[-lookback-1:-1]
        if recent.empty:
            return math.nan, math.nan
        return float(recent["high"].max()), float(recent["low"].min())

    def evaluate(self, df: pd.DataFrame, timeframe_minutes: int, context: pd.DataFrame | None = None) -> dict[str, Any]:
        x = self._prepare(df, timeframe_minutes)
        if len(x) < max(30, self.cfg.volume_length):
            return {"state":"NO TRADE","direction":"NEUTRAL","reason":"WARMUP","timeframe":timeframe_minutes}

        row = x.iloc[-1]
        ts = row.timestamp
        tod = ts.timetz().replace(tzinfo=None)
        start = time.fromisoformat(self.cfg.scan_start)
        end = time.fromisoformat(self.cfg.scan_end)
        in_scan = start <= tod <= end
        is0915 = tod.hour == 9 and tod.minute == 15

        levels = self._levels(x, context)
        ema = self._ema(x.close, self.cfg.ema_length)
        ema_v = float(ema.iloc[-1])
        price_above = row.close > ema_v
        price_below = row.close < ema_v
        ema_dist = abs(row.close-ema_v)/ema_v*100 if ema_v else 0

        avg_vol = self._sma(x.volume, self.cfg.volume_length).iloc[-1]
        vol_mult = float(row.volume/avg_vol) if avg_vol else 0

        opens = x[x.timestamp.dt.hour.eq(9) & x.timestamp.dt.minute.eq(15)]
        prev_open_vols = opens.volume.iloc[:-1].tail(20)
        prev_0915_avg = prev_open_vols.mean() if len(prev_open_vols) else math.nan
        effective_vol = float(row.volume/prev_0915_avg) if is0915 and self.cfg.use_special_0915_rvol and pd.notna(prev_0915_avg) and prev_0915_avg > 0 else vol_mult
        extreme = effective_vol >= self.cfg.extreme_volume_multiple
        standard_vol_ok = vol_mult >= self.cfg.standard_volume_multiple

        candle_range = float(row.high-row.low)
        body = abs(float(row.close-row.open))
        body_ratio = body/candle_range if candle_range else 0
        bull = row.close > row.open
        bear = row.close < row.open
        bull_loc = (row.close-row.low)/candle_range if candle_range else .5
        bear_loc = (row.high-row.close)/candle_range if candle_range else .5
        strong_bull = bull and body_ratio >= self.cfg.minimum_body_ratio and bull_loc >= self.cfg.minimum_close_location
        strong_bear = bear and body_ratio >= self.cfg.minimum_body_ratio and bear_loc >= self.cfg.minimum_close_location

        avg_range = self._sma(x.high-x.low, self.cfg.range_average_length).iloc[-1]
        range_exp = candle_range/avg_range if avg_range else 1
        range_expanded = range_exp >= self.cfg.range_expansion_ratio
        prev_avg = self._sma((x.high-x.low).shift(1), self.cfg.compression_lookback).iloc[-1]
        prev_compressed = bool(pd.notna(prev_avg) and (x.high.iloc[-2]-x.low.iloc[-2]) < prev_avg*.80)
        compression_expansion = range_expanded and prev_compressed

        def up(v): return self._cross_up(row.close,row.high,v,self.cfg.break_trigger_mode,self.cfg.level_buffer_pct)
        def dn(v): return self._cross_down(row.close,row.low,v,self.cfg.break_trigger_mode,self.cfg.level_buffer_pct)

        buys = {
            "PDH": self.cfg.use_pd and up(levels["pdh"]),
            "WEEKLY HIGH": self.cfg.use_weekly and up(levels["weekly_high"]),
            "MONTHLY HIGH": self.cfg.use_monthly and up(levels["monthly_high"]),
            "52W HIGH": self.cfg.use_52_week and up(levels["year_high"]),
            "ATH": self.cfg.use_ath and up(levels["ath"]),
        }
        sells = {
            "PDL": self.cfg.use_pd and dn(levels["pdl"]),
            "WEEKLY LOW": self.cfg.use_weekly and dn(levels["weekly_low"]),
            "MONTHLY LOW": self.cfg.use_monthly and dn(levels["monthly_low"]),
            "52W LOW": self.cfg.use_52_week and dn(levels["year_low"]),
            "ATL": self.cfg.use_ath and dn(levels["atl"]),
        }
        buy_names = [k for k,v in buys.items() if v]
        sell_names = [k for k,v in sells.items() if v]
        any_buy, any_sell = bool(buy_names), bool(sell_names)
        buy_name = next((k for k in ["ATH","52W HIGH","MONTHLY HIGH","WEEKLY HIGH","PDH"] if buys.get(k)), "NONE")
        sell_name = next((k for k in ["ATL","52W LOW","MONTHLY LOW","WEEKLY LOW","PDL"] if sells.get(k)), "NONE")
        score_map = {"ATH":100,"52W HIGH":80,"MONTHLY HIGH":60,"WEEKLY HIGH":40,"PDH":20,
                     "ATL":100,"52W LOW":80,"MONTHLY LOW":60,"WEEKLY LOW":40,"PDL":20}

        prev_buy = any(bool(up(v)) for v in levels.values()) if False else None
        # Pine uses a fresh-break condition. Compute it from the previous candle.
        prev = x.iloc[-2]
        def up_prev(v):
            return self._cross_up(prev.close,prev.high,v,self.cfg.break_trigger_mode,self.cfg.level_buffer_pct)
        def dn_prev(v):
            return self._cross_down(prev.close,prev.low,v,self.cfg.break_trigger_mode,self.cfg.level_buffer_pct)
        prev_any_buy = any([self.cfg.use_pd and up_prev(levels["pdh"]), self.cfg.use_weekly and up_prev(levels["weekly_high"]), self.cfg.use_monthly and up_prev(levels["monthly_high"]), self.cfg.use_52_week and up_prev(levels["year_high"]), self.cfg.use_ath and up_prev(levels["ath"])])
        prev_any_sell = any([self.cfg.use_pd and dn_prev(levels["pdl"]), self.cfg.use_weekly and dn_prev(levels["weekly_low"]), self.cfg.use_monthly and dn_prev(levels["monthly_low"]), self.cfg.use_52_week and dn_prev(levels["year_low"]), self.cfg.use_ath and dn_prev(levels["atl"])])
        fresh_buy, fresh_sell = any_buy and not prev_any_buy, any_sell and not prev_any_sell

        opening_buy = self.cfg.use_opening_candle and is0915 and extreme and bull and any_buy
        opening_sell = self.cfg.use_opening_candle and is0915 and extreme and bear and any_sell
        master_avg = self._sma((x.high-x.low).shift(1), self.cfg.master_lookback).iloc[-1]
        large_range = pd.notna(master_avg) and candle_range >= master_avg*self.cfg.master_range_multiplier
        master_vol_ok = (not self.cfg.master_needs_extreme_volume) or extreme
        master = in_scan and large_range and master_vol_ok
        master_buy = self.cfg.use_master_candle and master and extreme and bull and any_buy
        master_sell = self.cfg.use_master_candle and master and extreme and bear and any_sell

        last_signal_exists = False
        signal_cooldown_ok = True
        standard_bull = in_scan and fresh_buy and standard_vol_ok and (not self.cfg.use_ema_filter or price_above) and signal_cooldown_ok
        standard_bear = in_scan and fresh_sell and standard_vol_ok and (not self.cfg.use_ema_filter or price_below) and signal_cooldown_ok
        if self.cfg.signal_mode == "QUALITY PRIME":
            standard_bull &= strong_bull and range_expanded
            standard_bear &= strong_bear and range_expanded
        active_buy_level = levels[buy_name] if buy_name != "NONE" else np.nan
        active_sell_level = levels[sell_name] if sell_name != "NONE" else np.nan
        bull_follow = bool(pd.notna(active_buy_level) and row.close > active_buy_level and row.close > x.close.iloc[-2] and bull)
        bear_follow = bool(pd.notna(active_sell_level) and row.close < active_sell_level and row.close < x.close.iloc[-2] and bear)
        standard_bull &= (not self.cfg.require_follow_through or bull_follow)
        standard_bear &= (not self.cfg.require_follow_through or bear_follow)
        bull_base = in_scan and (opening_buy or master_buy or standard_bull)
        bear_base = in_scan and (opening_sell or master_sell or standard_bear)

        vwap = x["close"].iloc[-1]  # replaced below by session VWAP
        session_date = ts.date()
        sess = x[x.timestamp.dt.date == session_date]
        vwap = float((sess["volume"] * ((sess.high+sess.low+sess.close)/3)).sum()/sess.volume.sum()) if sess.volume.sum() else float(row.close)
        vwap_bull = row.close > vwap
        vwap_bear = row.close < vwap
        rsi = float(self._rsi(x.close,self.cfg.rsi_length).iloc[-1])
        rsi_bull = 50 <= rsi <= self.cfg.rsi_overbought
        rsi_bear = self.cfg.rsi_oversold <= rsi <= 50
        htf_ema = self._ema(x.close,self.cfg.htf_ema_length).iloc[-1]
        htf_bull, htf_bear = row.close > htf_ema, row.close < htf_ema
        vt = self._sma(x.volume,self.cfg.volume_trend_lookback)
        vol_trend = bool(len(vt) > self.cfg.volume_trend_lookback and vt.iloc[-1] > vt.iloc[-1-self.cfg.volume_trend_lookback])
        atr = self._atr(x,self.cfg.atr_length)
        atr_exp = bool(pd.notna(atr.iloc[-1]) and pd.notna(atr.iloc[-2]) and atr.iloc[-1] > atr.iloc[-2])
        conf_bull = int(vwap_bull)+int(rsi_bull)+int(htf_bull)+int(vol_trend)+int(atr_exp)
        conf_bear = int(vwap_bear)+int(rsi_bear)+int(htf_bear)+int(vol_trend)+int(atr_exp)
        bull_gate = (not self.cfg.enable_extra_confirmation) or ((not self.cfg.use_vwap_filter or vwap_bull) and (not self.cfg.use_rsi_filter or rsi_bull) and (not self.cfg.use_htf_trend_filter or htf_bull) and (not self.cfg.use_volume_trend_filter or vol_trend) and (not self.cfg.use_atr_filter or atr_exp))
        bear_gate = (not self.cfg.enable_extra_confirmation) or ((not self.cfg.use_vwap_filter or vwap_bear) and (not self.cfg.use_rsi_filter or rsi_bear) and (not self.cfg.use_htf_trend_filter or htf_bear) and (not self.cfg.use_volume_trend_filter or vol_trend) and (not self.cfg.use_atr_filter or atr_exp))
        bull_confirm, bear_confirm = bull_base and bull_gate, bear_base and bear_gate

        bars_since_high = next((len(x)-1-i for i in range(len(x)-1,max(-1,len(x)-1-self.cfg.fake_lookback-1),-1) if x.high.iloc[i] > levels["pdh"]), None)
        bars_since_low = next((len(x)-1-i for i in range(len(x)-1,max(-1,len(x)-1-self.cfg.fake_lookback-1),-1) if x.low.iloc[i] < levels["pdl"]), None)
        fake_bull = self.cfg.enable_fake_breakout and in_scan and bars_since_high is not None and row.high > levels["pdh"] and row.close < levels["pdh"]
        fake_bear = self.cfg.enable_fake_breakout and in_scan and bars_since_low is not None and row.low < levels["pdl"] and row.close > levels["pdl"]

        dist_pdh = abs(row.close-levels["pdh"])/levels["pdh"]*100 if pd.notna(levels["pdh"]) and levels["pdh"] else 999
        dist_pdl = abs(row.close-levels["pdl"])/levels["pdl"]*100 if pd.notna(levels["pdl"]) and levels["pdl"] else 999
        near_pdh, near_pdl = dist_pdh <= 1, dist_pdl <= 1
        bull_setup, bear_setup = in_scan and near_pdh and row.close >= levels["pdh"], in_scan and near_pdl and row.close <= levels["pdl"]

        level_score = score_map[buy_name] if bull_confirm else score_map[sell_name] if bear_confirm else 0
        volume_score = 20 if effective_vol>=6.5 else 18 if effective_vol>=4 else 15 if effective_vol>=2 else 10 if effective_vol>=1.5 else 5 if effective_vol>=1.2 else 0
        lev_score = level_score/100*15
        body_score = min(15,max(0,body_ratio*15))
        close_score = (bull_loc if bull_confirm else bear_loc)*10
        ema_score = min(15,max(0,ema_dist/self.cfg.ema_full_separation_pct*15)) if self.cfg.ema_full_separation_pct>0 else 0
        range_score = 10 if range_exp>=2 else 9 if range_exp>=1.75 else 8 if range_exp>=1.5 else 6 if range_exp>=1.3 else 3 if range_exp>=1.1 else 0
        mins_from_open = tod.hour*60+tod.minute-555
        timing_score = 10 if mins_from_open<=5 else 9 if mins_from_open<=10 else 8 if mins_from_open<=15 else 6 if mins_from_open<=20 else 4 if mins_from_open<=30 else 2 if mins_from_open<=45 else 0
        compression_score = 5 if compression_expansion else 2 if range_expanded else 0
        prime_score = min(100,max(0,volume_score+lev_score+body_score+close_score+ema_score+range_score+timing_score+compression_score)) if (bull_confirm or bear_confirm) else None

        grade = "—" if prime_score is None else "PRIME A+" if prime_score>=90 else "PRIME A" if prime_score>=80 else "STRONG" if prime_score>=70 else "GOOD" if prime_score>=60 else "WATCH" if prime_score>=50 else "WEAK"
        state = "FAKE BREAKOUT" if fake_bull or fake_bear else "CONFIRMED" if bull_confirm or bear_confirm else "SETUP" if bull_setup or bear_setup else "WATCH" if near_pdh or near_pdl else "NO TRADE"
        direction = "BUY" if bull_confirm else "SELL" if bear_confirm else "FAKE BULL" if fake_bull else "FAKE BEAR" if fake_bear else "BULLISH" if bull_setup else "BEARISH" if bear_setup else "NEUTRAL"

        atr_v = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else candle_range
        last_swing_high, last_swing_low = self._structure_levels(x)
        sl = None
        if bull_confirm:
            sl = row.low if self.cfg.sl_mode=="SIGNAL CANDLE" else (last_swing_low if pd.notna(last_swing_low) else row.low)
            if self.cfg.sl_mode=="STRUCTURE + ATR": sl -= atr_v*self.cfg.atr_sl_multiplier
            if sl >= row.close: sl = row.low-atr_v*self.cfg.atr_sl_multiplier
        elif bear_confirm:
            sl = row.high if self.cfg.sl_mode=="SIGNAL CANDLE" else (last_swing_high if pd.notna(last_swing_high) else row.high)
            if self.cfg.sl_mode=="STRUCTURE + ATR": sl += atr_v*self.cfg.atr_sl_multiplier
            if sl <= row.close: sl = row.high+atr_v*self.cfg.atr_sl_multiplier
        risk_share = abs(row.close-sl) if sl is not None else None
        t1=t2=t3=None
        qty=None
        if risk_share and risk_share>0:
            if bull_confirm:
                t1=row.close+risk_share*self.cfg.target1_r; t2=row.close+risk_share*self.cfg.target2_r; t3=row.close+risk_share*self.cfg.target3_r
            elif bear_confirm:
                t1=row.close-risk_share*self.cfg.target1_r; t2=row.close-risk_share*self.cfg.target2_r; t3=row.close-risk_share*self.cfg.target3_r
            if self.cfg.use_risk_quantity: qty=math.floor((self.cfg.account_size*self.cfg.risk_percent/100)/risk_share)

        block=[]
        if bull_base and not bull_confirm:
            if self.cfg.use_vwap_filter and not vwap_bull: block.append("VWAP")
            if self.cfg.use_rsi_filter and not rsi_bull: block.append("RSI")
            if self.cfg.use_htf_trend_filter and not htf_bull: block.append("HTF")
            if self.cfg.use_volume_trend_filter and not vol_trend: block.append("VolTrend")
            if self.cfg.use_atr_filter and not atr_exp: block.append("ATR")
        if bear_base and not bear_confirm:
            if self.cfg.use_vwap_filter and not vwap_bear: block.append("VWAP")
            if self.cfg.use_rsi_filter and not rsi_bear: block.append("RSI")
            if self.cfg.use_htf_trend_filter and not htf_bear: block.append("HTF")
            if self.cfg.use_volume_trend_filter and not vol_trend: block.append("VolTrend")
            if self.cfg.use_atr_filter and not atr_exp: block.append("ATR")

        return {
            "timestamp": ts.isoformat(), "timeframe": timeframe_minutes,
            "state": state, "direction": direction,
            "trigger": "09:15 OPENING" if opening_buy or opening_sell else "MASTER CANDLE" if master_buy or master_sell else "STANDARD BREAK" if standard_bull or standard_bear else "NONE",
            "levels": levels, "buy_break": buy_name if any_buy else "NONE", "sell_break": sell_name if any_sell else "NONE",
            "ema": ema_v, "ema_status": "ABOVE" if price_above else "BELOW" if price_below else "AT EMA",
            "volume_multiple": effective_vol, "volume_tier": "EXTREME" if extreme else "PASS" if standard_vol_ok else "NORMAL",
            "body_ratio": body_ratio, "close_location": bull_loc if bull else bear_loc,
            "range_expansion": range_exp, "range_expanded": range_expanded, "compression_expansion": compression_expansion,
            "prime_score": prime_score, "grade": grade,
            "confluence": {"bull":conf_bull,"bear":conf_bear},
            "core_logic": "BUY" if bull_base else "SELL" if bear_base else "—",
            "blocked_by": " ".join(block) if block else "—",
            "risk": {"entry":float(row.close) if bull_confirm or bear_confirm else None,"stop_loss":float(sl) if sl is not None else None,"risk_per_share":float(risk_share) if risk_share is not None else None,"quantity":qty,"target1":t1,"target2":t2,"target3":t3},
            "flags": {"opening_buy":opening_buy,"opening_sell":opening_sell,"master_buy":master_buy,"master_sell":master_sell,"standard_buy":standard_bull,"standard_sell":standard_bear,"fake_bull":fake_bull,"fake_bear":fake_bear,"prime_quality":prime_score is not None and prime_score>=self.cfg.prime_threshold},
        }
