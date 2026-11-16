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
import urllib.request

UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/HemantLaddha/india-day-trader-skill)"
PAUSE = 0.5
YAHOO_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

INDIA_MARKET_HOLIDAYS = {
    "2026-01-01": "New Year's Day",
    "2026-01-26": "Republic Day",
    "2026-03-03": "Mahashivratri",
    "2026-04-03": "Good Friday",
    "2026-05-01": "Maharashtra Day",
    "2026-06-19": "Bakrid / Eid ul-Adha",
    "2026-08-15": "Independence Day",
    "2026-08-27": "Ganesh Chaturthi",
    "2026-10-20": "Dussehra",
    "2026-11-12": "Diwali Laxmi Pujan",
    "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day",
    "2027-01-26": "Republic Day",
    "2027-03-26": "Good Friday",
    "2027-05-01": "Maharashtra Day",
    "2027-06-19": "Muharram",
    "2027-08-15": "Independence Day",
    "2027-09-01": "Ganesh Chaturthi",
    "2027-10-30": "Dussehra",
    "2027-11-07": "Diwali Laxmi Pujan",
    "2027-12-25": "Christmas Day",
}

SPECIAL_TRADING_DAYS = {
    "2026-11-08": "Diwali Laxmi Pujan (Muhurat Trading)",
    "2027-10-29": "Diwali Laxmi Pujan (Muhurat Trading)",
}

SPECIAL_SESSIONS = {
    "2026-11-08": (datetime.time(18, 0), datetime.time(19, 0)),
    "2027-10-29": (datetime.time(18, 0), datetime.time(19, 0)),
}

CALENDAR_YEARS = (2026, 2027)
OPEN = datetime.time(9, 15)
CLOSE = datetime.time(15, 30)
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


class AlertError(Exception):
    pass


def ist_offset(utc=None):
    return 5.5


def to_ist(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=5, minutes=30)


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
    return dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)


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
    s = str(sym or "").strip().upper()
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
        result = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise AlertError("Yahoo returned something unexpected for %s" % formatted_sym)
    if not result:
        raise AlertError("Yahoo has no data for %s" % formatted_sym)
    chart = result[0]
    meta = chart.get("meta", {})
    price = meta.get("regularMarketPrice")
    if price is None:
        quotes = (chart.get("indicators") or {}).get("quote", [{}])[0]
        close = (quotes.get("close") or [])
        if close:
            price = close[-1]
    if price is None:
        raise AlertError("Yahoo has no price for %s" % formatted_sym)
    return {
        "symbol": formatted_sym,
        "price": float(price),
        "prev_close": meta.get("previousClose") or meta.get("chartPreviousClose"),
        "time": datetime.datetime.fromtimestamp(meta.get("regularMarketTime", 0), datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if meta.get("regularMarketTime") else "",
        "currency": meta.get("currency"),
        "source": "yahoo",
    }


def _offline_text(folder, source, sym, exchange="NS"):
    sym = str(sym or "").strip().upper()
    if source in ("yahoo", "yfinance") and not sym.endswith((".NS", ".BO")):
        sym = f"{sym}.{exchange}"
    base = os.path.join(folder, f"{source}-{sym}.json")
    if os.path.exists(base):
        with open(base, encoding="utf-8") as fh:
            return fh.read()
    gz = base + ".gz"
    if os.path.exists(gz):
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            return fh.read()
    raise AlertError(f"no offline quote file {base}")


def get_quotes(symbols, source="yahoo", offline=None, pause=PAUSE):
    quotes, errors = {}, []
    for i, sym in enumerate(symbols):
        raw_sym = str(sym or "").strip().upper()
        if not raw_sym:
            continue
        query_sym = raw_sym if raw_sym.startswith("^") or "=" in raw_sym or raw_sym.endswith((".NS", ".BO")) else format_indian_yahoo_sym(raw_sym)
        try:
            if offline:
                text = _offline_text(offline, source, query_sym)
            else:
                if i and pause:
                    time.sleep(pause)
                url = yahoo_url(query_sym)
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    text = resp.read().decode("utf-8", "replace")
            quotes[raw_sym] = parse_yahoo(text, query_sym)
        except Exception as exc:
            errors.append(f"{raw_sym}: {exc}")
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
        raise AlertError("rule %s needs \"at\" as an IST time like \"15:30\"" % rule.get("id"))
    if rule.get("date") and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(rule["date"])):
        raise AlertError("rule %s: date must be YYYY-MM-DD" % rule.get("id"))


def _norm_indian_sym(raw):
    s = str(raw or "").strip().upper()
    if s.startswith("NSE:"):
        s = s[4:]
    if s.startswith("BSE:"):
        s = s[4:]
    if s.startswith("^") or "=" in s or s.endswith((".NS", ".BO")):
        return s
    return s + ".NS"


def _dedupe(items):
    out = []
    for item in items:
        item = item.strip() if isinstance(item, str) else item
        if item and item not in out:
            out.append(item)
    return out


def _n(x):
    s = "%.2f" % float(x)
    if s.endswith(".00"):
        return s[:-3]
    return s


def rules_from_plan(plan, flat_by=None):
    if not isinstance(plan, dict):
        return []
    symbol = str(plan.get("symbol") or "").strip().upper()
    if not symbol:
        return []
    sym = _norm_indian_sym(symbol)
    out = []
    if plan.get("stop") is not None:
        out.append({
            "id": "%s-plan-stop" % sym.lower().replace(":", "-").replace(".", "-"),
            "type": "below",
            "symbol": sym,
            "price": float(plan["stop"]),
            "date": str(plan.get("date")),
        })
    if plan.get("target") is not None:
        out.append({
            "id": "%s-plan-target" % sym.lower().replace(":", "-").replace(".", "-"),
            "type": "above",
            "symbol": sym,
            "price": float(plan["target"]),
            "date": str(plan.get("date")),
        })
    flat = str(flat_by or plan.get("flat_by") or "15:30")
    out.append({
        "id": "%s-flat-by" % sym.lower().replace(":", "-").replace(".", "-"),
        "type": "time",
        "at": flat,
        "symbol": sym,
        "label": "flat by close",
        "before_close": True,
        "date": str(plan.get("date")),
    })
    return out


def active(rule, day):
    if not rule.get("date"):
        return True
    return str(rule["date"]) == str(day)


def evaluate(rules, quotes, status, state, now):
    state = json.loads(json.dumps(state or {}))
    state.setdefault("rung", {})
    rings = []
    local = to_ist(now)
    for rule in rules:
        if not active(rule, status["date"]):
            continue
        rid = rule.get("id")
        if rid and rid in state["rung"]:
            continue
        typ = rule.get("type")
        if typ == "opening_bell":
            if status.get("open"):
                rings.append({"id": rid, "message": "NSE/BSE OPEN: the market is open at %s IST." % status["now_ist"]})
                if rid:
                    state["rung"][rid] = local.strftime("%Y-%m-%dT%H:%M:%S")
        elif typ == "time":
            at = _hhmm(rule.get("at"))
            if at is not None and local.time() >= at:
                label = rule.get("label") or "time alert"
                rings.append({"id": rid, "message": "ALERT %s: it is %s IST (rule %s)." % (label, at.strftime("%H:%M"), rid)})
                if rid:
                    state["rung"][rid] = local.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            symbol = rule.get("symbol")
            q = quotes.get(symbol) if symbol else None
            if q is None:
                continue
            price = q["price"]
            if typ == "above" and price >= float(rule["price"]):
                message = "ALERT %s: %s is at or above ₹%.2f." % (rule.get("label") or "target", symbol, float(rule["price"]))
                rings.append({"id": rid, "message": message})
                if rid:
                    state["rung"][rid] = local.strftime("%Y-%m-%dT%H:%M:%S")
            elif typ == "below" and price <= float(rule["price"]):
                message = "ALERT %s: %s is at or below ₹%.2f." % (rule.get("label") or "stop", symbol, float(rule["price"]))
                rings.append({"id": rid, "message": message})
                if rid:
                    state["rung"][rid] = local.strftime("%Y-%m-%dT%H:%M:%S")
            elif typ == "stop" and price <= float(rule["price"]):
                rings.append({"id": rid, "message": "ALERT stop: %s is at or below ₹%.2f." % (symbol, float(rule["price"]))})
                if rid:
                    state["rung"][rid] = local.strftime("%Y-%m-%dT%H:%M:%S")
            elif typ == "target" and price >= float(rule["price"]):
                rings.append({"id": rid, "message": "ALERT target: %s is at or above ₹%.2f." % (symbol, float(rule["price"]))})
                if rid:
                    state["rung"][rid] = local.strftime("%Y-%m-%dT%H:%M:%S")
            elif typ == "pct_move":
                ref = float(rule.get("ref") or q.get("prev_close") or 1.0)
                move = (price / ref) - 1.0
                if rule.get("direction") in (None, "up") and move >= 0 and abs(move) * 100 >= float(rule["pct"]):
                    rings.append({"id": rid, "message": "ALERT %s: %s moved %.2f%% from the reference." % (rule.get("label") or "pct_move", symbol, 100.0 * move)})
                    if rid:
                        state["rung"][rid] = local.strftime("%Y-%m-%dT%H:%M:%S")
                elif rule.get("direction") in (None, "down") and move <= 0 and abs(move) * 100 >= float(rule["pct"]):
                    rings.append({"id": rid, "message": "ALERT %s: %s moved %.2f%% from the reference." % (rule.get("label") or "pct_move", symbol, 100.0 * move)})
                    if rid:
                        state["rung"][rid] = local.strftime("%Y-%m-%dT%H:%M:%S")
    return rings, state


def write_prices(path, quotes, now, source):
    payload = {
        "market": "india",
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "prices": {k: float(v["price"]) for k, v in quotes.items()},
    }
    _write(path, payload)


def holdings(a):
    syms = []
    pf = _read(a.portfolio, {})
    for pos in pf.get("positions", []) if isinstance(pf, dict) else []:
        sym = pos.get("ticker") or pos.get("symbol") or ""
        if sym:
            syms.append(_norm_indian_sym(sym))
    plan = _read(a.plan, {})
    if isinstance(plan, dict) and plan.get("symbol"):
        syms.append(_norm_indian_sym(plan["symbol"]))
    return _dedupe(syms)


def cmd_clock(a):
    st = market_status(parse_now(a.now))
    if a.json:
        print(json.dumps(st, indent=2))
    else:
        print("IST %s (%s): NSE/BSE %s, %s." % (st["now_ist"], st["weekday"], "OPEN" if st["open"] else "closed", st["reason"]))
        if st.get("opens"):
            special = " (special session: %s)" % st["special_session"] if st.get("special_session") else ""
            print("Today's session: %s to %s IST%s." % (st["opens"], st["closes"], special))
        if not st["open"] and st.get("next_open"):
            print("Next open: %s IST." % st["next_open"])
        if not st["calendar_known"]:
            print("Holiday list covers %s only: check NSE/BSE calendars for this date." % " and ".join(map(str, sorted(CALENDAR_YEARS))))
    return 0 if st["open"] else 1


def cmd_quote(a):
    syms = _dedupe([_norm_indian_sym(s) for s in a.symbols] + (holdings(a) if a.holdings else []))
    if not syms:
        raise AlertError("which tickers? alerts.py quote RELIANCE TCS, or --holdings")
    now = parse_now(a.now)
    quotes, errors = get_quotes(syms, a.source, a.offline)
    if a.write and quotes:
        write_prices(a.write, quotes, now, a.source)
    if a.json:
        print(json.dumps({"quotes": quotes, "errors": errors}, indent=2))
    else:
        for s in syms:
            q = quotes.get(s) or quotes.get(s.upper())
            if q:
                chg = ""
                if q.get("prev_close"):
                    chg = " (%+.2f%% vs prev close ₹%.2f)" % (100.0 * (q["price"] / q["prev_close"] - 1), q["prev_close"])
                print("%-16s ₹%.2f%s  %s  [%s]" % (s, q["price"], chg, q.get("time", ""), q["source"]))
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
    syms = _dedupe([str(r.get("symbol", "")).upper() for r in watched if r.get("type") not in NO_QUOTE])
    quotes, errors = get_quotes(syms, a.source, a.offline) if syms else ({}, [])
    state = _read(a.state, {})
    rings, state = evaluate(rules, quotes, status, state, now)
    if not a.no_write:
        _write(a.state, state)
        if quotes:
            write_prices(a.prices_out, quotes, now, a.source)
    if a.json:
        print(json.dumps({"market": status, "rings": rings, "errors": errors,
                          "quotes": {s: q["price"] for s, q in quotes.items()}}, indent=2))
    else:
        print("NSE/BSE %s (%s IST, %s)." % ("OPEN" if status["open"] else "closed", status["now_ist"], status["reason"]))
        for r in rings:
            print("ALERT " + r["message"])
        if not rings:
            price_list = ", " + ", ".join("%s ₹%.2f" % (s, quotes[s]["price"]) for s in syms if s in quotes) if quotes else ""
            print("Nothing hit. %d rule(s) watched today%s." % (len(watched), price_list))
        for e in errors:
            print("error: " + e)
        if rings:
            print("An alert is information, not an order. A bracket's stop-loss and take-profit already sit at the broker: check get_open_position and record any fill (ticket.py fill). To close a position yourself: ticket.py flatten, then trader-risk and your yes.")
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
        print("Run alerts.py check every few minutes while the trade is open (a scheduled task or /loop). Free quotes are delayed; the broker's bracket orders are what actually stop you out.")
        return 0
    if a.opening_bell:
        rule = {"id": a.id or "opening-bell", "type": "opening_bell"}
    elif a.at:
        if _hhmm(a.at) is None:
            raise AlertError("--at wants an IST time like 15:30")
        rule = {"id": a.id or ("time-%s" % a.at.replace(":", "")), "type": "time", "at": a.at, "label": a.label or "time alert"}
        if a.symbol:
            rule["symbol"] = _norm_indian_sym(a.symbol)
        if a.before_close:
            rule["before_close"] = True
    else:
        if not a.symbol:
            raise AlertError("--symbol is required (or --from-plan, --at, --opening-bell)")
        sym = _norm_indian_sym(a.symbol)
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
        rule = dict({"id": a.id or ("%s-%s-%s" % (sym.lower().replace(":", "-").replace(".", "-"), rule["type"], _n(val)))}, symbol=sym, **rule)
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
        print("%-24s %s%s" % (rid, json.dumps({k: v for k, v in r.items() if k != "id"}), ("  (rang %s)" % rung) if rung else ""))
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
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print(json.dumps({"status": "ok", "market": "india"}, indent=2))
        return 0
    if argv[0] == "--json":
        print(json.dumps({"status": "ok", "market": "india"}, indent=2))
        return 0
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
    p.add_argument("--before-close", action="store_true", help="a time alert that moves earlier for early closes")
    p.add_argument("--date", help="watch this rule on this India date only (YYYY-MM-DD)")
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
