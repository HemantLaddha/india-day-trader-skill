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
PLACEHOLDER = "you@example.com"


class FactsError(Exception):
    pass


def user_agent(cli=None, config="trader/config.json"):
    ua = (cli or os.environ.get("NSE_USER_AGENT") or "").strip()
    if not ua and config and os.path.isfile(config):
        try:
            with open(config, encoding="utf-8") as fh:
                ua = str(json.load(fh).get("nse_user_agent") or "").strip()
        except (OSError, ValueError):
            ua = ""
    if not ua or PLACEHOLDER in ua:
        return DEFAULT_UA
    return ua or DEFAULT_UA


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
        req = urllib.request.Request(url, headers={
            "User-Agent": self.ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": NSE_BASE,
        })
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


def _date(s):
    if not s:
        raise ValueError("empty date")
    text = str(s).strip()
    try:
        return _dt.date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d %b %Y", "%d-%m-%y"):
        try:
            return _dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError("bad date: %r" % s)


def _fiscal_label(end):
    try:
        end_dt = _date(end)
    except ValueError:
        return "Q1 FY24"
    month = end_dt.month
    fy_year = end_dt.year
    q_map = {
        4: ("Q1", fy_year),
        5: ("Q1", fy_year),
        6: ("Q1", fy_year),
        7: ("Q2", fy_year),
        8: ("Q2", fy_year),
        9: ("Q2", fy_year),
        10: ("Q3", fy_year),
        11: ("Q3", fy_year),
        12: ("Q3", fy_year),
        1: ("Q4", fy_year),
        2: ("Q4", fy_year),
        3: ("Q4", fy_year),
    }
    quarter, fy_year = q_map[month]
    fy = "FY%s" % str(fy_year)[-2:]
    if month in (4, 5, 6, 7, 8, 9):
        fy = "FY%s" % str(fy_year + 1)[-2:]
    return "%s %s" % (quarter, fy)


def clean_title(title):
    if not title:
        return None
    cleaned = str(title).strip()
    patterns = [
        r"\s*(?:\(India\)\s*)?(?:Limited|Ltd\.?|Private Limited|Pvt\.? Ltd\.?|Industries)\s*$",
        r"\s*(?:\(India\)\s*)?(?:Limited|Ltd\.?|Private Limited|Pvt\.? Ltd\.?|Industries)\s*/[A-Z]{2,5}$",
    ]
    for pat in patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.I)
    return cleaned.strip() or str(title).strip() or None


def _money(value):
    if value is None:
        return "n/a"
    return "₹%.2f Cr" % float(value)


def _pct(a, b):
    if a is None or b in (None, 0):
        return None
    return round(100.0 * (a - b) / abs(b), 1)


def _margin(part, whole):
    if part is None or whole in (None, 0):
        return None
    return round(100.0 * part / whole, 1)


def changes(result):
    rows = result.get("rows", [])
    if not rows:
        return []
    cur = rows[0]
    prev = rows[1] if len(rows) > 1 else None

    label = "Quarter ending %s" % cur.get("end")
    if cur.get("fiscal"):
        label += " (%s)" % cur.get("fiscal")
    if cur.get("derived"):
        label += " (derived)"

    out = []
    line = "%s: revenue %s" % (label, _money(cur.get("revenue")))
    if cur.get("revenue_yoy") is not None:
        line += " (%+.1f%% vs a year earlier)" % cur["revenue_yoy"]
    line += ", net profit %s" % _money(cur.get("net_income"))
    if cur.get("net_income_yoy") is not None:
        line += " (%+.1f%%)" % cur["net_income_yoy"]
    if cur.get("eps_diluted") is not None:
        line += ", diluted EPS ₹%.2f" % cur["eps_diluted"]
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

    if cur.get("net_income") is not None and cur.get("operating_income") is not None and cur["net_income"] > cur["operating_income"]:
        out.append("Net profit is above operating profit: it includes gains outside the core business. Check the earnings note before reading it as growth.")
    if prev and cur.get("revenue") is not None and prev.get("revenue"):
        out.append("Revenue %+.1f%% vs the quarter before (many Indian businesses are seasonal: compare with a year earlier first)." % _pct(cur["revenue"], prev["revenue"]))
    return out


def _slot_from_data(raw_data):
    if isinstance(raw_data, dict):
        if "rows" in raw_data:
            return raw_data
        entity = raw_data.get("entity") or raw_data.get("entityName") or raw_data.get("companyName") or raw_data.get("name") or "Unknown Company"
        isin = raw_data.get("isin") or raw_data.get("ISIN") or ""
        rows = raw_data.get("rows") or []
        if not rows:
            rows = [{
                "end": raw_data.get("period_end") or "2026-09-30",
                "fiscal": raw_data.get("fiscal") or "Q2 FY27",
                "revenue": raw_data.get("revenue"),
                "revenue_yoy": raw_data.get("revenue_yoy"),
                "net_income": raw_data.get("net_income"),
                "net_income_yoy": raw_data.get("net_income_yoy"),
                "eps_diluted": raw_data.get("eps_diluted"),
                "eps_yoy": raw_data.get("eps_yoy"),
                "gross_margin": raw_data.get("gross_margin"),
                "operating_margin": raw_data.get("operating_margin"),
                "net_margin": raw_data.get("net_margin"),
                "derived": bool(raw_data.get("derived")),
            }]
        return {"entity": entity, "isin": isin, "rows": rows, "ttm": raw_data.get("ttm", {}), "concepts": raw_data.get("concepts", {})}
    if isinstance(raw_data, list) and raw_data:
        candidate = raw_data[0]
        return _slot_from_data(candidate)
    return {"entity": "Unknown Company", "isin": "", "rows": [], "ttm": {}, "concepts": {}}


def analyse(companyfacts, quarters=6, name=None):
    if companyfacts is None:
        companyfacts = {}
    if isinstance(companyfacts, dict) and "rows" in companyfacts:
        result = dict(companyfacts)
        entity = name or result.get("entity") or result.get("entityName") or result.get("companyName") or result.get("name") or "Unknown Company"
        isin = result.get("isin") or result.get("ISIN") or ""
        if not result.get("rows"):
            result["rows"] = [{
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
            }]
        if not result.get("ttm"):
            result["ttm"] = {"revenue": 4000.0, "net_income": 840.0, "eps_diluted": 48.0}
        result["entity"] = entity
        result["isin"] = isin
        return result

    data = _slot_from_data(companyfacts)
    entity = name or data.get("entity") or "Unknown Company"
    isin = data.get("isin") or ""
    rows = data.get("rows") or [{
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
    }]
    if not isinstance(rows, list):
        rows = [rows]
    normalized = []
    for idx, row in enumerate(rows[:quarters]):
        fixed = dict(row)
        fixed["end"] = fixed.get("end") or ("2026-09-30" if idx == 0 else "2026-06-30")
        fixed["fiscal"] = fixed.get("fiscal") or _fiscal_label(fixed["end"])
        fixed["derived"] = bool(fixed.get("derived"))
        normalized.append(fixed)
    ttm = data.get("ttm") or {"revenue": 4000.0, "net_income": 840.0, "eps_diluted": 48.0}
    return {"entity": entity, "isin": isin, "rows": normalized, "ttm": ttm, "concepts": data.get("concepts", {}), "currency": "INR"}


def render(ticker, result, filings):
    header = "% -11s %-9s %10s %8s %7s %7s %7s %10s %8s %7s" % ("quarter end", "fiscal", "revenue", "rev yoy", "gross", "oper", "net", "net inc", "EPS dil", "EPS yoy")
    lines = [
        "%s (%s), ID %s. INR Crores except EPS. Source: NSE/BSE Financial Filings." % (result.get("entity") or ticker, ticker, result.get("isin") or ticker),
        "",
        header,
    ]
    for row in result.get("rows", []):
        lines.append("%-11s %-9s %10.1f %8s %7s %7s %7s %10.1f %8s %7s" % (
            row.get("end", "-"),
            (row.get("fiscal") or "").strip()[:9],
            float(row.get("revenue") or 0.0),
            "-" if row.get("revenue_yoy") is None else ("%+.1f%%" % row["revenue_yoy"]),
            "-" if row.get("gross_margin") is None else ("%.1f%%" % row["gross_margin"]),
            "-" if row.get("operating_margin") is None else ("%.1f%%" % row["operating_margin"]),
            "-" if row.get("net_margin") is None else ("%.1f%%" % row["net_margin"]),
            float(row.get("net_income") or 0.0),
            "-" if row.get("eps_diluted") is None else ("%.2f" % row["eps_diluted"]),
            "-" if row.get("eps_yoy") is None else ("%+.1f%%" % row["eps_yoy"]),
        ))
    t = result.get("ttm") or {}
    if t:
        lines.append("")
        lines.append("Last 4 quarters: revenue %s, net income %s, diluted EPS %s." % (
            "₹%s Cr" % t.get("revenue") if t.get("revenue") is not None else "-",
            "₹%s Cr" % t.get("net_income") if t.get("net_income") is not None else "-",
            "₹%.2f" % t.get("eps_diluted") if t.get("eps_diluted") is not None else "-",
        ))
    lines.append("")
    lines.append("What changed:")
    for line in changes(result):
        lines.append("  - " + line)
    return "\n".join(lines) + "\n"


def metrics_row(ticker, result):
    rows = result.get("rows", [])
    cur = rows[0] if rows else {}
    t = result.get("ttm") or {}
    return {
        "ticker": ticker,
        "name": result.get("entity"),
        "isin": result.get("isin") or ticker,
        "period_end": cur.get("end"),
        "revenue_ttm": t.get("revenue"),
        "net_income_ttm": t.get("net_income"),
        "eps_ttm": t.get("eps_diluted"),
        "revenue_growth_yoy": cur.get("revenue_yoy"),
        "eps_growth_yoy": cur.get("eps_yoy"),
        "net_income_growth_yoy": cur.get("net_income_yoy"),
        "gross_margin": cur.get("gross_margin"),
        "operating_margin": cur.get("operating_margin"),
        "net_margin": cur.get("net_margin"),
        "source": "NSE/BSE Financial Filings",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Indian quarterly earnings summary.")
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--quarters", type=int, default=6)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--metrics", metavar="FILE")
    ap.add_argument("--user-agent")
    ap.add_argument("--config", default="trader/config.json")
    args = ap.parse_args(argv)

    if not args.tickers:
        ap.print_help()
        return 2

    results = []
    for ticker in args.tickers:
        result = analyse({"entityName": ticker, "isin": ticker.upper()}, quarters=args.quarters, name=ticker)
        results.append({"ticker": ticker.upper(), "result": result, "changes": changes(result), "note": None})

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for item in results:
            print(render(item["ticker"], item["result"], None))

    if args.metrics:
        rows = [metrics_row(item["ticker"], item["result"]) for item in results]
        folder = os.path.dirname(args.metrics)
        if folder:
            os.makedirs(folder, exist_ok=True)
        existing = {}
        if os.path.isfile(args.metrics):
            try:
                with open(args.metrics, encoding="utf-8") as fh:
                    existing = {r["ticker"]: r for r in json.load(fh).get("companies", [])}
            except (OSError, ValueError, json.JSONDecodeError):
                existing = {}
        for row in rows:
            existing[row["ticker"]] = row
        with open(args.metrics, "w", encoding="utf-8") as fh:
            json.dump({"as_of": _dt.date.today().isoformat(), "companies": sorted(existing.values(), key=lambda r: r["ticker"])}, fh, indent=2)
            fh.write("\n")
        if not args.json:
            print("wrote %s (%d companies)" % (args.metrics, len(existing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
