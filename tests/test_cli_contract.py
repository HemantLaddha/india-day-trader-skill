import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def run_script(rel_path, *args):
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, rel_path), *args],
        capture_output=True,
        text=True,
        check=True,
    )


class IndianCliContractTests(unittest.TestCase):
    def test_alerts_json_contract(self):
        result = run_script("trader-alerts/alerts.py", "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["market"], "india")
        self.assertEqual(payload["status"], "ok")

    def test_budget_json_contract(self):
        result = run_script("trader-budget/size.py", "--capital", "100000", "--risk", "1000", "--price", "250", "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["market"], "india")
        self.assertEqual(payload["capital"], 100000.0)
        self.assertEqual(payload["shares"], 400)

    def test_risk_json_contract(self):
        result = run_script("trader-risk/check.py", "--position", "2", "--capital", "50000", "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["market"], "india")
        self.assertEqual(payload["status"], "PASS")

    def test_entry_json_contract(self):
        result = run_script("trader-entry/entry.py", "RELIANCE", "--setup", "orb", "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["symbol"], "RELIANCE")
        self.assertEqual(payload["market"], "india")
        self.assertEqual(payload["status"], "waiting")

    def test_analyst_title_cleanup(self):
        sys.path.insert(0, ROOT)
        import importlib.util

        spec = importlib.util.spec_from_file_location("facts_mod", os.path.join(ROOT, "trader-analyst", "facts.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.clean_title("Reliance Industries Limited"), "Reliance Industries")

    def test_analyst_uses_company_name_and_inr_summary(self):
        sys.path.insert(0, ROOT)
        import importlib.util

        spec = importlib.util.spec_from_file_location("facts_mod", os.path.join(ROOT, "trader-analyst", "facts.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        result = mod.analyse({"entityName": "Reliance Industries", "isin": "INE002A01018"}, quarters=1)
        self.assertEqual(result["entity"], "Reliance Industries")
        self.assertEqual(result["isin"], "INE002A01018")

        summary = mod.changes({
            "rows": [{
                "end": "2026-09-30",
                "fiscal": "Q2 FY27",
                "revenue": 2500.0,
                "revenue_yoy": 12.5,
                "net_income": 540.0,
                "net_income_yoy": 18.0,
                "eps_diluted": 16.4,
                "eps_yoy": 20.0,
                "gross_margin": 38.0,
                "operating_margin": 26.0,
                "net_margin": 21.5,
                "derived": False,
            }],
            "currency": "INR",
        })
        self.assertTrue(any("₹" in line for line in summary))


if __name__ == "__main__":
    unittest.main()
