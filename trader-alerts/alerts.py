#!/usr/bin/env python3
"""Price alerts and the NSE/BSE clock for trader-alerts. Standard library only.

    python3 alerts.py clock                          # is the NSE/BSE open? next open / close
    python3 alerts.py quote RELIANCE --write         # quotes -> trader/prices.json
    python3 alerts.py quote --holdings --write       # every ticker in your portfolio and plan
    python3 alerts.py add --from-plan                # stop, target and flat-by-close from trader/plan.json
    python3 alerts.py add --symbol RELIANCE --stop 1285.50
    python3 alerts.py add --symbol RELIANCE --target 1340.00
    python3 alerts.py add --at 15:15 --label "flat by close" --before-close
    python3 alerts.py add --symbol TCS --pct 3
    python3 alerts.py add --opening-bell
    python3 alerts.py check                          # rings what hit, once; exit 1 if nothing rang
    python3 alerts.py check --now "2026-10-19 15:15" --offline tests/fixtures/trader-alerts
    python3 alerts.py list
    python3 alerts.py reset reliance-ns-plan-stop

Rule types:
  above / target  the price is at or above "price"
  below / stop    the price is at or below "price"
  pct_move        the price moved "pct" percent or more from the previous close
                  (or from "ref" if you give one); "direction": "up" or "down"
  opening_bell    the NSE/BSE opened today (rings once per trading day at 09:15 IST)
  time            the IST clock passed "at" (HH:MM) on a trading day
                  (rings once per trading day); "before_close": true shifts the
                  alert dynamically if a special session closes at a non-standard
                  time instead of the regular 15:30 IST close

A rule with "date" is only watched on that IST date (rules from a plan
are for the plan's day only). An above / below alert rings ONCE and then stays
quiet until you reset it, unless the rule has "rearm": true (it re-arms when
the price crosses back). A pct_move alert rings at most once per day.

Quotes (free, delayed, unofficial; for alerts only, never for timing an order):
  yahoo   https://yahoo.com (falls
          back to query1 on a 429 or a 5xx; one retry with a pause on a 429; one
          request per ticker, half a second apart; automatically appends .NS if
          no exchange suffix is provided)
  --offline DIR reads DIR/yahoo-<TICKER>.json (or .json.gz) instead.

NSE/BSE calendar: the 2026 official holidays and 2027-2028 projected holidays
based on https://nseindia.com
and https://bseindia.com (regular hours
09:15-15:30 IST, plus special Diwali Muhurat Trading sessions). Outside those
years the clock says the holiday list is unknown.
"""










# Reading guide for this file:
# - This module handles market-clock checks, stock price lookups, and alert rules.
# - The code below stores a list of alert conditions such as "price above X",
#   "time reached 15:55", or "market opening bell".
# - It fetches quotes from Yahoo or Stooq and compares them against the rules.
# - The CLI at the end turns these helpers into commands such as "alerts check".

import argparse
import csv
import datetime
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/HemantLaddha/india-day-trader-skill)"
PAUSE = 0.5    # seconds between requests: be polite to free endpoints
BACKOFF = 2.0  # seconds to wait before the one retry after a 429
YAHOO_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
# we can use these host for indian market as well >> this is the example :  https://query2.finance.yahoo.com/v8/finance/chart/reliance.ns?range=1d&interval=1d
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
# this is for matching time in 24 hours timing zone with minutes


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
    # 2028 Projected NSE & BSE Weekday Trading Holidays
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
    "2028-12-25": "Christmas"
}

# some days US market early closes its market , but indian market never follows anything like so we dont need it.
# Instead of early close what we have is mahurat trading on some days as below in indian market which we need to add...
# Special weekend sessions (e.g., Diwali Muhurat Trading)
SPECIAL_TRADING_DAYS = {
    "2026-11-08": "Diwali Laxmi Pujan (Muhurat Trading)",
    "2027-10-29": "Diwali Laxmi Pujan (Muhurat Trading)",
    "2028-10-17": "Diwali Laxmi Pujan (Muhurat Trading)",
}
# they also follow some special timing on these mahurat days as below
# Note: Exact timings are announced by NSE/BSE a few days before Diwali
SPECIAL_SESSIONS = {
    "2026-11-08": (datetime.time(18, 0), datetime.time(19, 0)),
    "2027-10-29": (datetime.time(18, 0), datetime.time(19, 0)),
    "2028-10-17": (datetime.time(18, 0), datetime.time(19, 0)),
}

# we need to change it as below 2027 , 2028
CALENDAR_YEARS = (2026 ,2028, 2027)

# the above 2 are the market open & closing time for US market we need to change them as below
OPEN = datetime.time(9, 15)   # 09:15 AM IST
CLOSE = datetime.time(15, 30) # 03:30 PM IST
NORMAL_CLOSE = datetime.time(15, 30)
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

EARLY = datetime.time(13, 0)
# there is no early closing in the Indian market so no need this.

class AlertError(Exception):
    pass


# ---------------------------------------------------------------- time

def ist_offset(utc=None):
    """Hours from UTC for India (IST): always +5.5 (UTC+05:30).
    India does not observe Daylight Saving Time."""
    return 5.5

def to_ist(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=ist_offset(utc))

def ist_to_utc(local):
    return local - datetime.timedelta(hours=5, minutes=30)


def parse_now(text):
    """ISO time -> naive UTC. A time without an offset is taken as IST (India) time."""
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


def trading_day(d: datetime.date):
  """(is_trading_day, reason). Weekends, special sessions, and NSE holiday list."""
  date_str = d.isoformat()
  # Check if a weekend has a special trading session (like Muhurat Trading)
  if date_str in SPECIAL_TRADING_DAYS:
    return True, SPECIAL_TRADING_DAYS[date_str]
  # Standard Saturday (5) and Sunday (6) weekend check
  if d.weekday() >= 5:
    return False, "weekend"
  # Check NSE/BSE weekday holidays
  name = INDIA_MARKET_HOLIDAYS.get(date_str)
  if name:
    return False, "NSE holiday: " + name
  return True, ""


def session(d):
    """(open_time, close_time) in IST, or None if closed all day."""
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
    ok, reason = trading_day(d)
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
    # next open
    nd = d if (s and local.time() < s[0]) else d + datetime.timedelta(days=1)
    for _ in range(15):
        ns = session(nd)
        if ns:
            st["next_open"] = "%s %s" % (nd.isoformat(), ns[0].strftime("%H:%M"))
            break
        nd += datetime.timedelta(days=1)
    return st





# ---------------------------------------------------------------- quotes

def format_indian_yahoo_sym(sym, default_exchange=".NS"):
    """Normalize ticker for Yahoo Finance India (e.g., 'reliance' -> 'RELIANCE.NS')."""
    s = sym.strip().upper()
    # Keep indices (^NSEI, ^BSESN), forex (USDINR=X), or tickers that already have .NS / .BO
    if s.startswith("^") or "=" in s or s.endswith((".NS", ".BO")):
        return s
    # Replace internal dots in share classes if any, then append .NS (or .BO)
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
        err = (data.get("chart") or {}).get("error") or {}
        raise AlertError("Yahoo has no data for %s: %s" % (formatted_sym, err.get("description", "unknown ticker")))
    m = res[0].get("meta", {})
    price = m.get("regularMarketPrice")
    if price is None:
        raise AlertError("Yahoo has no price for %s" % formatted_sym)
    t = m.get("regularMarketTime")
    when = (datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if t else "")
    q = (res[0].get("indicators", {}).get("quote") or [{}])[0]
    opens = [x for x in (q.get("open") or []) if x is not None]
    return {
        "symbol": formatted_sym,
        "price": float(price),
        "open": opens[0] if opens else None,
        "high": m.get("regularMarketDayHigh"),
        "low": m.get("regularMarketDayLow"),
        "prev_close": m.get("previousClose") or m.get("chartPreviousClose"),
        "time": when,
        "currency": m.get("currency"),  # Automatically returns "INR" for .NS / .BO tickers
        "source": "yahoo"
    }

_urlopen = urllib.request.urlopen   # tests swap these two
_sleep = time.sleep


def _get(url, timeout=20):
    """(HTTP status, body). A network failure is an AlertError."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with _urlopen(req, timeout=timeout) as r:
            return 200, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        finally:
            try:
                e.close()
            except Exception:
                pass
        return e.code, body
    except urllib.error.URLError as e:
        raise AlertError("could not reach %s: %s" % (url.split("/")[2], e.reason))


def fetch(url, timeout=20):
    code, text = _get(url, timeout)
    if code != 200:
        raise AlertError("%s answered HTTP %d" % (url.split("?")[0], code))
    return text



def fetch_yahoo(sym, timeout=20):
    """query2 first. A 429 waits BACKOFF seconds and tries once more; a 429 or a 5xx
    after that moves on to query1. A 404 comes back as Yahoo's own error JSON."""
    last = None
    for host in YAHOO_HOSTS:
        url = yahoo_url(sym, host)
        code, text = _get(url, timeout)
        if code == 429:
            _sleep(BACKOFF)
            code, text = _get(url, timeout)
        if code == 200:
            return text
        if code == 404 and text.strip().startswith("{"):
            return text
        last = (url, code)
        if code != 429 and code < 500:
            break
    raise AlertError("%s answered HTTP %d" % (last[0].split("?")[0], last[1]))



def _offline_text(folder, source, sym, exchange="NS"):
  # 1. Normalize symbol for Indian exchanges (e.g., RELIANCE -> RELIANCE.NS)
  sym = sym.upper().strip()
  if source in ("yahoo", "yfinance") and not sym.endswith((".NS", ".BO")):
    sym = f"{sym}.{exchange}"

  # 2. Map Indian data sources to their standard file extensions
  csv_sources = {"stooq", "nse", "bse", "bhavcopy", "jugaad"}
  ext = "csv" if source.lower() in csv_sources else "json"

  # 3. Build file path (e.g., folder/nse-RELIANCE.csv or folder/yahoo-RELIANCE.NS.json)
  base = os.path.join(folder, f"{source}-{sym}.{ext}")

  if os.path.exists(base):
    with open(base, encoding="utf-8") as fh:
      return fh.read()
  if os.path.exists(base + ".gz"):
    with gzip.open(base + ".gz", "rt", encoding="utf-8") as fh:
      return fh.read()

  raise AlertError(f"no offline quote file {base}")



def get_quotes(symbols, exchange="NS", offline=None, pause=PAUSE):
    """{SYM: quote} and [errors] for Indian market (NSE/BSE). Uses Yahoo Finance."""
    quotes, errors = {}, []
    suffix = f".{exchange.upper()}"
    
    for i, sym in enumerate(symbols):
        raw_sym = sym.upper().strip()
        
        # Add .NS or .BO unless it is an index (^) or already has a suffix
        if not raw_sym.startswith("^") and not raw_sym.endswith((".NS", ".BO")):
            query_sym = f"{raw_sym}{suffix}"
        else:
            query_sym = raw_sym
            
        try:
            if offline:
                text = _offline_text(offline, "yahoo", query_sym)
            else:
                if i and pause:
                    _sleep(pause)
                text = fetch_yahoo(query_sym)
            
            # Store result under the clean input symbol
            quotes[raw_sym] = parse_yahoo(text, query_sym)
        except AlertError as e:
            errors.append(f"{raw_sym}: {e}")
            
    return quotes, errors



def write_prices(path, quotes, now_utc, source="yahoo"):
    old = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh)
        except (ValueError, OSError):
            old = {}
    prices = dict(old.get("prices", {}))
    detail = dict(old.get("detail", {}))
    stamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    for s, q in quotes.items():
        prices[s] = q["price"]
        detail[s] = {
            "prev_close": q.get("prev_close"),
            "time": q.get("time"),
            "currency": q.get("currency", "INR"),
            "source": q.get("source"),
            "fetched": stamp
        }
    doc = {
        "as_of": stamp,
        "source": source,
        "note": (
            "Delayed NSE/BSE quotes for alerts and sizing checks. Your broker's price is the one that fills. "
            "detail.fetched is when each price was read."
        ),
        "prices": prices,
        "detail": detail
    }
    _write(path, doc)
    return doc



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
    except ValueError as e:
        raise AlertError("%s is not valid JSON: %s" % (path, e))



# ---------------------------------------------------------------- rules

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
        raise AlertError("rule %s needs \"at\" as a New York time like \"15:55\"" % rule.get("id"))
    if rule.get("date") and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(rule["date"])):
        raise AlertError("rule %s: date must be YYYY-MM-DD" % rule.get("id"))



def active(rule, today):
    """A rule with a "date" is watched on that IST date only."""
    return not rule.get("date") or str(rule["date"]) == today


def _rang_today(stamp, today):
    """Did a rule that rang at this UTC stamp ring on this IST date?"""
    if not stamp:
        return False
    try:
        utc = datetime.datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return stamp[:10] == today
    return to_ist(utc).date().isoformat() == today


def ring_time(rule, status):
    """
    Returns the time a rule rings today in IST.
    Adjusts dynamically if the market has a modified close time (e.g., special sessions)
    and the rule is marked 'before_close'.
    """
    at = _hhmm(rule.get("at"))
    
    # Check if today has a non-standard close time passed in status (e.g., "13:30" or "19:15")
    actual_close_str = status.get("close_time")
    
    if rule.get("before_close") and actual_close_str:
        actual_close = _hhmm(actual_close_str)
        
        if actual_close != NORMAL_CLOSE:
            base_date = datetime.date(2000, 1, 1)
            dt_normal = datetime.datetime.combine(base_date, NORMAL_CLOSE)
            dt_actual = datetime.datetime.combine(base_date, actual_close)
            
            # Calculate the exact time difference (positive or negative)
            shift = dt_actual - dt_normal
            at = (datetime.datetime.combine(base_date, at) + shift).time()
            
    return at


def evaluate(rules, quotes, status, state, now_utc):
    """Pure function for Indian Markets (NSE/BSE). Returns (rings, new_state)."""
    state = json.loads(json.dumps(state or {}))
    rung = state.setdefault("rung", {})
    today = status["date"]
    local = to_ist(now_utc)
    stamp = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    rings = []
    
    for r in rules:
        validate(r)
        rid = r.get("id") or "%s-%s" % (r.get("symbol", "market"), r["type"])
        if not active(r, today):
            continue
            
        typ = {"stop": "below", "target": "above"}.get(r["type"], r["type"])
        
        # 1. Opening Bell (9:15 AM IST for NSE/BSE)
        if typ == "opening_bell":
            if status["open"] and not _rang_today(rung.get(rid), today):
                special_note = (", special session today: " + status["special_session"]) if status.get("special_session") else ""
                rings.append({
                    "id": rid, 
                    "symbol": "", 
                    "message": "Opening bell: the NSE is open (%s IST)%s." % (status["now_ist"], special_note)
                })
                rung[rid] = stamp
            continue
            
        # 2. Time-based Alerts (e.g., Intraday square-off before 3:15 PM / 3:30 PM)
        if typ == "time":
            at = ring_time(r, status)
            if status.get("opens") and local.time() >= at and not _rang_today(rung.get(rid), today):
                label = r.get("label") or "time alert"
                msg = "%s%s: it is %s IST (set for %s)" % (
                    label[:1].upper(), label[1:], local.strftime("%H:%M"), at.strftime("%H:%M")
                )
                msg += (", the market closes at %s IST." % status["closes"]) if status["open"] else ", the market has closed."
                
                sym = str(r.get("symbol") or "").upper()
                if sym:
                    msg += (" If %s is still open, square it off: trader-broker flatten --symbol %s builds the sell "
                            "ticket, then trader-risk and your yes." % (sym, sym))
                rings.append({"id": rid, "symbol": sym, "message": msg})
                rung[rid] = stamp
            continue
            
        # 3. Price & Percentage Move Alerts
        sym = r["symbol"].upper()
        q = quotes.get(sym)
        if not q:
            continue
        p = q["price"]
        
        if typ in ("above", "below"):
            hit = p >= r["price"] if typ == "above" else p <= r["price"]
            if hit and rid not in rung:
                word = "at or above" if typ == "above" else "at or below"
                label = {"stop": "stop", "target": "target"}.get(r["type"], "alert level")
                note = (" (" + r["note"] + ")") if r.get("note") else ""
                rings.append({
                    "id": rid, 
                    "symbol": sym, 
                    "message": "%s %s ₹%.2f: %s your %s ₹%s%s." % (
                        sym, "is" if status["open"] else "last", p, word, label, _n(r["price"]), note
                    )
                })
                rung[rid] = stamp
            elif not hit and rid in rung and r.get("rearm"):
                del rung[rid]
                
        elif typ == "pct_move":
            ref = r.get("ref") or q.get("prev_close") or q.get("open")
            if not ref:
                continue
            move = 100.0 * (p / float(ref) - 1)
            want = r.get("direction")
            hit = abs(move) >= r["pct"] and (not want or (want == "up") == (move > 0))
            if hit and not _rang_today(rung.get(rid), today):
                rings.append({
                    "id": rid, 
                    "symbol": sym, 
                    "message": "%s moved %+.2f%% to ₹%.2f (from ₹%.2f)." % (sym, move, p, float(ref))
                })
                rung[rid] = stamp
                
    state["last_check"] = stamp
    return rings, state


def _n(x):
    x = float(x)
    return str(int(x)) if x == int(x) else "%.2f" % x


def rules_from_plan(plan, cfg_flat_by=None):
    """trader/plan.json -> a stop alert, a target alert and a flat-by-close time alert, for the Indian market."""
    if not isinstance(plan, dict) or not plan.get("symbol"):
        raise AlertError("the plan has no symbol (run trader-exit first)")
    
    # Keep original symbol for broker/feed matching, create a clean slug for IDs
    sym = str(plan["symbol"]).upper().strip()
    sym_id = sym.lower().replace(":", "-").replace(".", "-")
    
    out = []
    for key, typ, word in (("stop", "stop", "plan stop"), ("target", "target", "plan target")):
        v = plan.get(key)
        if not isinstance(v, (int, float)) or v <= 0:
            raise AlertError("the plan has no %s (run trader-exit)" % key)
        label = plan.get("%s_label" % key)
        out.append({
            "id": "%s-plan-%s" % (sym_id, key),
            "symbol": sym,
            "type": typ,
            "price": round(float(v), 2),  # Indian equities trade in 0.05 tick increments; 2 decimals is standard
            "note": word + (": " + label if label else "")
        })
    
    # NSE/BSE closes at 15:30 IST; broker MIS auto-square-off usually starts at 15:15 - 15:20
    flat = plan.get("flat_by") or cfg_flat_by or "15:15"
    if _hhmm(flat) is None:
        raise AlertError("the plan's flat_by %r is not a time like 15:15" % flat)
    
    out.append({
        "id": "%s-flat-by" % sym_id,
        "symbol": sym,
        "type": "time",
        "at": flat,
        "label": "flat by close",
        "before_close": True
    })
    
    if plan.get("date"):
        for r in out:
            r["date"] = str(plan["date"])
            
    return out


# ---------------------------------------------------------------- commands


def _norm_indian_sym(raw):
    s = str(raw or "").strip().upper()
    if s.startswith("NSE:"):
        return s[4:] + ".NS"
    if s.startswith("BSE:"):
        return s[4:] + ".BO"
    return s


def holdings(a):
    syms = []
    pf = _read(a.portfolio, {})
    for p in pf.get("positions", []) if isinstance(pf, dict) else []:
        syms.append(_norm_indian_sym(p.get("ticker") or p.get("symbol")))
    plan = _read(a.plan, {})
    if isinstance(plan, dict) and plan.get("symbol"):
        syms.append(_norm_indian_sym(plan["symbol"]))
    return [s for s in syms if s]




def _dedupe(items):
    out = []
    for s in items:
        if s and s not in out:
            out.append(s)
    return out

def cmd_clock(a):
    st = market_status(parse_now(a.now))
    if a.json:
        print(json.dumps(st, indent=2))
    else:
        print("IST %s (%s): NSE %s, %s." % (
            st["now_ist"],
            st["weekday"],
            "OPEN" if st["open"] else "closed",
            st["reason"],
        ))
        if st.get("opens"):
            special = (" (special session: %s)" % st["special_session"]) if st.get("special_session") else ""
            print("Today's session: %s to %s IST%s." % (st["opens"], st["closes"], special))
        if not st["open"] and st.get("next_open"):
            print("Next open: %s IST." % st["next_open"])
        if not st["calendar_known"]:
            years_str = ", ".join(map(str, sorted(CALENDAR_YEARS)))
            print("Holiday list covers %s only: check nseindia.com for this date." % years_str)
    return 0 if st["open"] else 1


def cmd_quote(a):
    syms = _dedupe([_norm_indian_sym(s) for s in a.symbols] + (holdings(a) if a.holdings else []))
    if not syms:
        raise AlertError("which tickers? alerts.py quote RELIANCE TCS, or --holdings")
    now = parse_now(a.now)
    quotes, errors = get_quotes(syms, offline=a.offline)
    if a.write and quotes:
        write_prices(a.write, quotes, now, "yahoo")
    if a.json:
        print(json.dumps({"quotes": quotes, "errors": errors}, indent=2))
    else:
        for s in syms:
            # Match key regardless of whether user passed 'RELIANCE' or 'RELIANCE.NS'
            q = quotes.get(s) or quotes.get(format_indian_yahoo_sym(s))
            if q:
                chg = ""
                if q.get("prev_close"):
                    chg = " (%+.2f%% vs prev close ₹%.2f)" % (
                        100.0 * (q["price"] / q["prev_close"] - 1),
                        q["prev_close"],
                    )
                print("%-14s ₹%.2f%s  %s  [%s]" % (q["symbol"], q["price"], chg, q.get("time", ""), q["source"]))
        for e in errors:
            print("error: " + e)
        if a.write and quotes:
            print("Wrote %d price(s) to %s." % (len(quotes), a.write))
        print("Quotes are free, delayed and unofficial: for alerts only. Your broker's price is the one that fills.")
    return 0 if quotes else 1



def cmd_check(a):
    doc = _read(a.rules, None)
    if not doc or not doc.get("rules"):
        raise AlertError("no rules in %s: add some with alerts.py add --from-plan" % a.rules)
    rules = doc["rules"]
    now = parse_now(a.now)
    status = market_status(now)
    watched = [r for r in rules if active(r, status["date"])]
    syms = _dedupe([_norm_indian_sym(r.get("symbol", "")) for r in watched if r.get("type") not in NO_QUOTE])
    quotes, errors = (get_quotes(syms, offline=a.offline) if syms else ({}, []))
    state = _read(a.state, {})
    rings, state = evaluate(rules, quotes, status, state, now)
    if not a.no_write:
        _write(a.state, state)
        if quotes:
            write_prices(a.prices_out, quotes, now, "yahoo")
    if a.json:
        print(json.dumps({
            "market": status,
            "rings": rings,
            "errors": errors,
            "quotes": {s: q["price"] for s, q in quotes.items()},
        }, indent=2))
    else:
        print("NSE %s (%s IST, %s)." % (
            "OPEN" if status["open"] else "closed",
            status["now_ist"],
            status["reason"],
        ))
        for r in rings:
            print("ALERT " + r["message"])
        if not rings:
            price_list = (
                ", " + ", ".join("%s ₹%.2f" % (s, quotes[s]["price"]) for s in syms if s in quotes)
            ) if quotes else ""
            print("Nothing hit. %d rule(s) watched today%s." % (len(watched), price_list))
        for e in errors:
            print("error: " + e)
        if rings:
            print(
                "An alert is information, not an order. A bracket's stop-loss and take-profit already sit at "
                "the broker: check get_open_position and record any fill (ticket.py fill). To close a "
                "position yourself: ticket.py flatten, then trader-risk and your yes."
            )
    return 0 if rings else 1


def cmd_add(a):
    doc = _read(a.rules, {"rules": []})
    doc.setdefault("rules", [])
    if a.from_plan:
        plan = _read(a.plan, None)
        if plan is None:
            raise AlertError("no plan at %s (run trader-exit first)" % a.plan)
        cfg = _read(a.config, {}) if a.config else {}
        new = rules_from_plan(plan, (cfg or {}).get("flat_by"))
        ids = {r["id"] for r in new}
        doc["rules"] = [r for r in doc["rules"] if r.get("id") not in ids] + new
        state = _read(a.state, {})
        if state.get("rung"):
            for i in ids:
                state["rung"].pop(i, None)
            _write(a.state, state)
        _write(a.rules, doc)
        for r in new:
            print("Added %s: %s" % (r["id"], json.dumps(r)))
        print(
            "Run alerts.py check every few minutes while the trade is open (a scheduled task or /loop). "
            "Free quotes are delayed; the broker's bracket orders are what actually stop you out."
        )
        return 0
    if a.opening_bell:
        rule = {"id": a.id or "opening-bell", "type": "opening_bell"}
    elif a.at:
        if _hhmm(a.at) is None:
            raise AlertError("--at wants an IST time like 15:15")
        rule = {
            "id": a.id or ("time-%s" % a.at.replace(":", "")),
            "type": "time",
            "at": a.at,
            "label": a.label or "time alert",
        }
        if a.symbol:
            rule["symbol"] = _norm_indian_sym(a.symbol)
        if a.before_close:
            rule["before_close"] = True
    else:
        if not a.symbol:
            raise AlertError("--symbol is required (or --from-plan, --at, --opening-bell)")
        sym = _norm_indian_sym(a.symbol)
        sym_id = sym.lower().replace(":", "-").replace(".", "-")
        if a.above is not None:
            rule = {"type": "above", "price": a.above}
        elif a.below is not None:
            rule = {"type": "below", "price": a.below}
        elif a.stop is not None:
            rule = {"type": "stop", "price": a.stop}
        elif a.target is not None:
            rule = {"type": "target", "price": a.target}
        elif a.pct is not None:
            rule = {"type": "pct_move", "pct": a.pct}
            if a.direction:
                rule["direction"] = a.direction
        else:
            raise AlertError("give one of --above, --below, --stop, --target or --pct")
        val = rule.get("price", rule.get("pct"))
        rule = dict({"id": a.id or ("%s-%s-%s" % (sym_id, rule["type"], _n(val)))}, symbol=sym, **rule)
        if a.rearm:
            rule["rearm"] = True
        if a.note:
            rule["note"] = a.note
    if a.date:
        rule["date"] = a.date
    validate(rule)
    if any(r.get("id") == rule["id"] for r in doc["rules"]):
        raise AlertError("a rule with id %s already exists" % rule["id"])
    doc["rules"].append(rule)
    _write(a.rules, doc)
    print("Added %s: %s" % (rule["id"], json.dumps(rule)))
    return 0



def cmd_list(a):
    doc = _read(a.rules, {"rules": []})
    state = _read(a.state, {})
    if not doc.get("rules"):
        print("No rules yet.")
        return 1
    for r in doc["rules"]:
        rid = r.get("id")
        rung = state.get("rung", {}).get(rid)
        
        # Format timestamp to IST if rung is stored as a Unix epoch number
        if isinstance(rung, (int, float)):
            rung_str = datetime.fromtimestamp(rung, tz=IST).strftime("%d-%b-%Y %I:%M %p IST")
        else:
            rung_str = rung

        details = json.dumps({k: v for k, v in r.items() if k != "id"})
        status = f"  (rang {rung_str})" if rung_str else ""
        print(f"{rid:<24} {details}{status}")
    return 0

def cmd_reset(a):
    state = _read(a.state, {})
    if a.id not in state.get("rung", {}):
        print("%s has not rung (nothing to reset)." % a.id)
        return 1
    del state["rung"][a.id]
    _write(a.state, state)
    print("Re-armed %s." % a.id)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Price alerts and the NSE/BSE clock (trader-alerts).")
    sub = ap.add_subparsers(dest="cmd")

    def net(p):
        p.add_argument("--source", default="yahoo", choices=["yahoo"])
        p.add_argument("--offline", metavar="DIR", help="read yahoo-<TICKER>.json files, no network")
        p.add_argument("--now", help="pretend it is this time (no offset = IST)")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("clock", help="is the NSE/BSE open?")
    p.add_argument("--now")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("quote", help="latest delayed NSE/BSE quotes")
    net(p)
    p.add_argument("symbols", nargs="*")
    p.add_argument("--holdings", action="store_true", help="add tickers from your portfolio and plan")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--write", nargs="?", const="trader/prices.json", metavar="PATH",
                   help="save to prices.json (default trader/prices.json)")
    p = sub.add_parser("check", help="check every rule, ring what hit")
    net(p)
    p.add_argument("--rules", default="trader/alerts.json")
    p.add_argument("--state", default="trader/state/alerts.json")
    p.add_argument("--prices-out", default="trader/prices.json")
    p.add_argument("--no-write", action="store_true")
    p = sub.add_parser("add", help="add a rule")
    p.add_argument("--rules", default="trader/alerts.json")
    p.add_argument("--state", default="trader/state/alerts.json")
    p.add_argument("--symbol")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--above", type=float)
    g.add_argument("--below", type=float)
    g.add_argument("--stop", type=float)
    g.add_argument("--target", type=float)
    g.add_argument("--pct", type=float)
    g.add_argument("--opening-bell", action="store_true")
    g.add_argument("--at", metavar="HH:MM", help="a time alert, IST")
    g.add_argument("--from-plan", action="store_true", help="stop, target and flat-by-close from the plan")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--config", default="trader/config.json", help="flat_by when the plan has none")
    p.add_argument("--label", help="what a time alert says, e.g. \"flat by close\"")
    p.add_argument("--before-close", action="store_true",
                   help="a time alert that shifts dynamically if the session closes at a non-standard time")
    p.add_argument("--date", help="watch this rule on this IST date only (YYYY-MM-DD)")
    p.add_argument("--direction", choices=["up", "down"])
    p.add_argument("--rearm", action="store_true")
    p.add_argument("--note")
    p.add_argument("--id")
    p = sub.add_parser("list", help="list the rules")
    p.add_argument("--rules", default="trader/alerts.json")
    p.add_argument("--state", default="trader/state/alerts.json")
    p = sub.add_parser("reset", help="re-arm a rule that rang")
    p.add_argument("id")
    p.add_argument("--state", default="trader/state/alerts.json")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"clock": cmd_clock, "quote": cmd_quote, "check": cmd_check, "add": cmd_add,
                "list": cmd_list, "reset": cmd_reset}[a.cmd](a)
    except AlertError as e:
        print("alerts.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
