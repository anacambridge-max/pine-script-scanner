import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from worker.outcomes import new_outcome, observe_outcome


IST = ZoneInfo("Asia/Kolkata")


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.confirmed = datetime(2026, 10, 12, 9, 18, 20, tzinfo=IST)
        self.signal = {
            "signal_type": "BUY", "entry": 100, "stop_loss": 98, "target1": 102,
            "metadata": {"outcome": new_outcome(self.confirmed, "2026-10-12T09:15:00+05:30")},
        }

    def candle(self, minute, high=101, low=99, close=101):
        return {"timestamp": datetime(2026, 10, 12, 9, minute, tzinfo=IST),
                "high": high, "low": low, "close": close}

    def test_ignores_confirmation_candle_and_unfinished_candle(self):
        changed = observe_outcome(self.signal, [self.candle(18, high=103), self.candle(19, high=103)],
                                  now=datetime(2026, 10, 12, 9, 19, 30, tzinfo=IST))
        self.assertIsNone(changed)

    def test_both_stop_and_target_same_minute_are_ambiguous(self):
        changed = observe_outcome(self.signal, [self.candle(19, high=103, low=97)],
                                  now=datetime(2026, 10, 12, 9, 21, tzinfo=IST))
        self.assertEqual(changed["first_hit"], "AMBIGUOUS")

    def test_horizon_return_is_directional_and_requires_nearby_candle(self):
        candles = [{"timestamp": self.confirmed.replace(second=0) + timedelta(minutes=i),
                    "high": 101, "low": 99, "close": 101} for i in range(1, 62)]
        changed = observe_outcome(self.signal, candles, now=self.confirmed + timedelta(minutes=62))
        self.assertEqual(changed["status"], "COMPLETE")
        self.assertEqual(changed["returns_pct"]["60"], 1)
        self.signal["signal_type"] = "SELL"
        self.signal["target1"] = 98
        self.signal["stop_loss"] = 102
        changed = observe_outcome(self.signal, candles, now=self.confirmed + timedelta(minutes=62))
        self.assertEqual(changed["returns_pct"]["60"], -1)
        sparse = observe_outcome(self.signal, [candles[-1]], now=self.confirmed + timedelta(minutes=62))
        self.assertNotIn("15", sparse["prices"])
        self.assertEqual(sparse["status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
