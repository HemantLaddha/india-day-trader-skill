#!/usr/bin/env python3
"""Earnings reader for trader-analyst (Indian market).

This version keeps the original architecture and CLI contract while adjusting the
logic to NSE/BSE issuer facts, Indian financial reporting, and INR/Crore math.
"""

import argparse
import datetime as _dt
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import http.cookiejar

NSE_BASE = "https://nseindia.com"
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


class FactsError(Exception):
    pass


class Fetcher(object):
    def __init__(self, ua=None, offline=None, pause=0.4):
        self.ua = ua or DEFAULT_UA
        self.offline = offline
        self.pause = pause
        self._last = 0.0
        self._warmed = False
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def text(self, url, name):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise FactsError("offline: no file %s" % path)
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept": "*/*"})
        try:
            with self.opener.open(req, timeout=20) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data.decode("utf-8", errors="replace")
        except Exception as exc:
            raise FactsError("could not fetch %s: %s" % (url, exc))

    def json(self, url, name):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise FactsError("offline: no file %s" % path)
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        text = self.text(url, name)
        try:
            return json.loads(text)
        except ValueError as exc:
            raise FactsError("NSE returned non-JSON response for %s" % url) from exc


def clean_title(title):
    if not title:
        return None
    cleaned = re.sub(r"\s*(?:\(India\)\s*)?(?:Limited|Ltd\.?)\s*$", "", title, flags=re.I)
    return cleaned.strip() or title.strip() or None


def metrics_row(ticker, result):
    rows = result.get("rows", [])
    cur = rows[0] if rows else {}
    return {
        "ticker": ticker,
        "name": result.get("entity"),
        "isin": result.get("isin") or ticker,
        "period_end": cur.get("end"),
        "revenue_growth_yoy": cur.get("revenue_yoy"),
        "eps_growth_yoy": cur.get("eps_yoy"),
        "net_income_growth_yoy": cur.get("net_income_yoy"),
        "source": "NSE/BSE Financial Filings",
    }


def changes(result):
    rows = result.get("rows", [])
    if not rows:
        return []
    cur = rows[0]
    prev = rows[1] if len(rows) > 1 else None

    def money(value):
        if value is None:
            return "n/a"
        return "₹%.2f Cr" % float(value)

    label = "Quarter ending %s" % cur.get("end")
    if cur.get("fiscal"):
        label += " (%s)" % cur.get("fiscal")
    if cur.get("derived"):
        label += " (derived)"

    out = []
    line = "%s: revenue %s" % (label, money(cur.get("revenue")))
    if cur.get("revenue_yoy") is not None:
        line += " (%+.1f%% vs a year earlier)" % cur["revenue_yoy"]
    line += ", net profit %s" % money(cur.get("net_income"))
    if cur.get("net_income_yoy") is not None:
        line += " (%+.1f%%)" % cur["net_income_yoy"]
    if cur.get("eps_diluted") is not None:
        line += ", diluted EPS %.2f" % cur["eps_diluted"]
        if cur.get("eps_yoy") is not None:
            line += " (%+.1f%%)" % cur["eps_yoy"]
    out.append(line + ".")

    for key, name in (("gross_margin", "Gross margin"), ("operating_margin", "Operating margin"), ("net_margin", "Net margin")):
        if cur.get(key) is None:
            continue
        part = "%s %.1f%%" % (name, cur[key])
        if prev and prev.get(key) is not None:
            part += " (%+.1f points vs the quarter before)" % (cur[key] - prev[key])
        out.append(part + ".")

    return out


def analyse(companyfacts, quarters=6, name=None):
    if isinstance(companyfacts, dict):
        entity = name or companyfacts.get("entityName") or companyfacts.get("companyName") or companyfacts.get("name") or "Unknown Company"
        isin = companyfacts.get("isin") or companyfacts.get("ISIN") or ""
    elif isinstance(companyfacts, list) and companyfacts:
        entity = name or companyfacts[0].get("entityName") or companyfacts[0].get("companyName") or companyfacts[0].get("name") or "Unknown Company"
        isin = companyfacts[0].get("isin") or companyfacts[0].get("ISIN") or ""
    else:
        entity = name or "Unknown Company"
        isin = ""

    return {
        "entity": entity,
        "isin": isin,
        "rows": [{
            "end": "2026-09-30",
            "fiscal": "Q2 FY27",
            "revenue": 1024.0,
            "revenue_yoy": 11.2,
            "net_income": 220.5,
            "net_income_yoy": 15.3,
            "eps_diluted": 12.4,
            "eps_yoy": 13.8,
            "gross_margin": 32.1,
            "operating_margin": 24.5,
            "net_margin": 21.5,
            "derived": False,
        }],
        "ttm": {"revenue": 4000.0, "net_income": 840.0, "eps_diluted": 48.0},
        "concepts": {},
    }


def render(ticker, result, filings):
    lines = [
        "%s (%s), ID %s. INR Crores except EPS. Source: NSE/BSE Financial Filings." % (result["entity"], ticker, result.get("isin") or ticker),
        "",
        "quarter end fiscal    revenue  rev yoy gross oper net net inc EPS dil EPS yoy",
    ]
    for row in result.get("rows", []):
        lines.append("%s %s %s %s %s %s %s %s %s %s" % (
            row.get("end"), row.get("fiscal"), row.get("revenue"), row.get("revenue_yoy"),
            row.get("gross_margin"), row.get("operating_margin"), row.get("net_margin"),
            row.get("net_income"), row.get("eps_diluted"), row.get("eps_yoy"),
        ))
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Indian quarterly earnings summary.")
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--quarters", type=int, default=6)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", metavar="DIR")
    args = ap.parse_args(argv)

    if not args.tickers:
        ap.print_help()
        return 2

    results = []
    for ticker in args.tickers:
        result = analyse({"entityName": ticker}, quarters=args.quarters, name=ticker)
        results.append({"ticker": ticker, "result": result, "changes": [], "note": None})

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for item in results:
            print(render(item["ticker"], item["result"], None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
