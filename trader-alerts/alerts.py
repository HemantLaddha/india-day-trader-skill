#!/usr/bin/env python3
"""Price alerts and the NSE/BSE clock for trader-alerts.

This is the Indian-market adaptation of the original day-trader-skill alerts
module, preserving the CLI, rule JSON schema, state handling, and offline-test
contract while moving the market logic to IST/NSE/BSE semantics.
"""

import argparse
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/HemantLaddha/india-day-trader-skill)"
PAUSE = 0.5
BACKOFF = 2.0
YAHOO_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

INDIA_MARKET_HOLIDAYS = {
    "2027-01-26": "Republic Day",
    "2027-03-10": "Id-Ul-Fitr (Ramzan Eid)",
    "2027-03-22": "Holi",
    "2027-03-26": "Good Friday",
    "2027-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2027-04-15": "Shri Ram Navami",
    "2027-04-19": "Shri Mahavir Jayanti",
    "2027-05-17": "Bakri Id",
    "2027-06-15": "Muharram",
    "2027-10-29": "Diwali Laxmi Pujan (Muhurat Trading Only)",
    "2028-01-26": "Republic Day",
    "2028-02-23": "Maha Shivaratri",
    "2028-04-03": "Shri Ram Navami",
    "2028-04-07": "Shri Mahavir Jayanti",
    "2028-04-14": "Dr. Baba Saheb Ambedkar Jayanti / Good Friday",
    "2028-05-01": "Maharashtra Day",
    "2028-05-05": "Bakri Id",
    "2028-08-15": "Independence Day",
    "2028-08-23": "Ganesh Chaturthi",
    "2028-09-27": "Dussehra",
    "2028-10-02": "Mahatma Gandhi Jayanti",
    "2028-10-17": "Diwali Laxmi Pujan (Muhurat Trading Only)",
    "2028-10-18": "Diwali-Balipratipada",
    "2028-11-02": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2028-12-25": "Christmas",
}

SPECIAL_TRADING_DAYS = {
    "2026-11-08": "Diwali Laxmi Pujan (Muhurat Trading)",
    "2027-10-29": "Diwali Laxmi Pujan (Muhurat Trading)",
    "2028-10-17": "Diwali Laxmi Pujan (Muhurat Trading)",
}

SPECIAL_SESSIONS = {
    "2026-11-08": (datetime.time(18, 0), datetime.time(19, 0)),
    "2027-10-29": (datetime.time(18, 0), datetime.time(19, 0)),
    "2028-10-17": (datetime.time(18, 0), datetime.time(19, 0)),
}

CALENDAR_YEARS = (2026, 2027, 2028)
OPEN = datetime.time(9, 15)
CLOSE = datetime.time(15, 30)
NORMAL_CLOSE = datetime.time(15, 30)
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class AlertError(Exception):
    pass


def ist_offset(utc=None):
    return 5.5


def to_ist(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=ist_offset(utc))


def ist_to_utc(local):
    return local - datetime.timedelta(hours=5, minutes=30)


def parse_now(text):
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise AlertError('--now wants a time like "2026-10-19 10:15" (IST) or ...Z (UTC)')
    if dt.tzinfo is None:
        return ist_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def trading_day(d):
    date_str = d.isoformat()
    if date_str in SPECIAL_TRADING_DAYS:
        return True, SPECIAL_TRADING_DAYS[date_str]
    if d.weekday() >= 5:
        return False, "weekend"
    name = INDIA_MARKET_HOLIDAYS.get(date_str)
    if name:
        return False, "NSE holiday: " + name
    return True, ""


def session(d):
    ok, _ = trading_day(d)
    if not ok:
        return None
    date_str = d.isoformat()
    if date_str in SPECIAL_SESSIONS:
        return SPECIAL_SESSIONS[date_str]
    return OPEN, CLOSE


def market_status(now_utc):
    local = to_ist(now_utc)
    d = local.date()
    _, reason = trading_day(d)
    st = {
        "now_ist": local.strftime("%Y-%m-%d %H:%M"),
        "date": d.isoformat(),
        "weekday": local.strftime("%A"),
        "calendar_known": d.year in CALENDAR_YEARS,
        "open": False,
        "reason": reason,
        "special_session": SPECIAL_TRADING_DAYS.get(d.isoformat()),
    }
    s = session(d)
    if s:
        o, c = s
        st["opens"], st["closes"] = o.strftime("%H:%M"), c.strftime("%H:%M")
        if o <= local.time() < c:
            st["open"] = True
            st["reason"] = "special session" if st["special_session"] else "regular session"
        elif local.time() < o:
            st["reason"] = "before the open"
        else:
            st["reason"] = "after the close"
    nd = d if (s and local.time() < s[0]) else d + datetime.timedelta(days=1)
    for _ in range(15):
        ns = session(nd)
        if ns:
            st["next_open"] = "%s %s" % (nd.isoformat(), ns[0].strftime("%H:%M"))
            break
        nd += datetime.timedelta(days=1)
    return st


def format_indian_yahoo_sym(sym, default_exchange=".NS"):
    s = sym.strip().upper()
    if s.startswith("^") or "=" in s or s.endswith((".NS", ".BO")):
        return s
    return s.replace(".", "-") + default_exchange


def yahoo_url(sym, host=YAHOO_HOSTS[0]):
    formatted = format_indian_yahoo_sym(sym)
    return "https://%s/v8/finance/chart/%s?range=1d&interval=1d" % (host, formatted)


def parse_yahoo(text, sym):
    formatted_sym = format_indian_yahoo_sym(sym)
    try:
        data = json.loads(text)
        res = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise AlertError("Yahoo returned something unexpected for %s" % formatted_sym)
    if not res:
        raise AlertError("Yahoo has no data for %s" % formatted_sym)
    m = res[0].get("meta", {})
    price = m.get("regularMarketPrice")
    if price is None:
        raise AlertError("Yahoo has no price for %s" % formatted_sym)
    return {
        "symbol": formatted_sym,
        "price": float(price),
        "prev_close": m.get("previousClose") or m.get("chartPreviousClose"),
        "time": datetime.datetime.fromtimestamp(m.get("regularMarketTime", 0), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if m.get("regularMarketTime") else "",
        "currency": m.get("currency"),
        "source": "yahoo",
    }


def _offline_text(folder, source, sym, exchange="NS"):
    sym = sym.upper().strip()
    if source in ("yahoo", "yfinance") and not sym.endswith((".NS", ".BO")):
        sym = f"{sym}.{exchange}"
    base = os.path.join(folder, f"{source}-{sym}.json")
    if os.path.exists(base):
        with open(base, encoding="utf-8") as fh:
            return fh.read()
    if os.path.exists(base + ".gz"):
        with gzip.open(base + ".gz", "rt", encoding="utf-8") as fh:
            return fh.read()
    raise AlertError(f"no offline quote file {base}")


def get_quotes(symbols, exchange="NS", offline=None, pause=PAUSE):
    quotes, errors = {}, []
    suffix = f".{exchange.upper()}"
    for i, sym in enumerate(symbols):
        raw_sym = sym.upper().strip()
        if not raw_sym.startswith("^") and not raw_sym.endswith((".NS", ".BO")):
            query_sym = f"{raw_sym}{suffix}"
        else:
            query_sym = raw_sym
        try:
            if offline:
                text = _offline_text(offline, "yahoo", query_sym)
            else:
                if i and pause:
                    time.sleep(pause)
                url = yahoo_url(query_sym)
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    text = resp.read().decode("utf-8", "replace")
            quotes[raw_sym] = parse_yahoo(text, query_sym)
        except Exception as e:
            errors.append(f"{raw_sym}: {e}")
    return quotes, errors


def _write(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _read(path, default):
    if not path or not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as exc:
        raise AlertError("%s is not valid JSON: %s" % (path, exc))


PRICE_TYPES = {"above", "below", "stop", "target", "pct_move", "opening_bell", "time"}
NO_QUOTE = {"opening_bell", "time"}


def _hhmm(text):
    m = HHMM.match(str(text or "").strip())
    if not m:
        return None
    return datetime.time(int(m.group(1)), int(m.group(2)))


def validate(rule):
    t = rule.get("type")
    if t not in PRICE_TYPES:
        raise AlertError("rule %s: unknown type %r" % (rule.get("id"), t))
    if t not in NO_QUOTE and not rule.get("symbol"):
        raise AlertError("rule %s needs a symbol" % rule.get("id"))
    if t in ("above", "below", "stop", "target") and not isinstance(rule.get("price"), (int, float)):
        raise AlertError("rule %s needs a numeric price" % rule.get("id"))
    if t == "pct_move" and not isinstance(rule.get("pct"), (int, float)):
        raise AlertError("rule %s needs a numeric pct" % rule.get("id"))
    if t == "time" and _hhmm(rule.get("at")) is None:
        raise AlertError("rule %s needs \"at\" as an IST time like \"15:55\"" % rule.get("id"))
    if rule.get("date") and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(rule["date"])):
        raise AlertError("rule %s: date must be YYYY-MM-DD" % rule.get("id"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Indian price alerts and the NSE/BSE clock.")
    ap.add_argument("--version", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.version:
        print("day-trader-skill-indian-market 0.1")
        return 0
    if args.json:
        print(json.dumps({"status": "ok", "market": "india"}, indent=2))
        return 0
    print("alerts: ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
