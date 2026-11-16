import datetime
import importlib.util
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SPEC = importlib.util.spec_from_file_location("alerts_mod", os.path.join(ROOT, "trader-alerts", "alerts.py"))
alerts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(alerts)


class IndianMarketClockTests(unittest.TestCase):
    def test_parse_now_uses_ist_inputs(self):
        value = alerts.parse_now("2026-10-13 10:00")
        self.assertEqual(value, datetime.datetime(2026, 10, 13, 4, 30))

    def test_market_status_regular_session(self):
        status = alerts.market_status(alerts.parse_now("2026-10-13 10:00"))
        self.assertTrue(status["open"])
        self.assertEqual(status["opens"], "09:15")
        self.assertEqual(status["closes"], "15:30")
        self.assertEqual(status["reason"], "regular session")

    def test_market_status_before_open_and_next_open(self):
        status = alerts.market_status(alerts.parse_now("2026-10-13 09:00"))
        self.assertFalse(status["open"])
        self.assertEqual(status["reason"], "before the open")
        self.assertEqual(status["next_open"], "2026-10-13 09:15")

    def test_market_status_special_muhurat_session(self):
        status = alerts.market_status(alerts.parse_now("2026-11-08 18:30"))
        self.assertTrue(status["open"])
        self.assertEqual(status["special_session"], "Diwali Laxmi Pujan (Muhurat Trading)")
        self.assertEqual(status["opens"], "18:00")
        self.assertEqual(status["closes"], "19:00")

    def test_format_indian_yahoo_sym_adds_ns_suffix(self):
        self.assertEqual(alerts.format_indian_yahoo_sym("RELIANCE"), "RELIANCE.NS")
        self.assertEqual(alerts.format_indian_yahoo_sym("TCS.NS"), "TCS.NS")


if __name__ == "__main__":
    unittest.main()
