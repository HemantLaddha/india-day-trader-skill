#!/usr/bin/env python3
"""News monitor for trader-news in the Indian market. Standard library only.

Watches headlines and exchange notices for the stocks you watch or hold and
prints only what is new since the last check, newest first, with how far each
stock has moved today and a flag on anything that touches your tickers.

    python3 news.py                                  # watchlist + plan + portfolio tickers
    python3 news.py --tickers RELIANCE TCS
    python3 news.py --tickers RELIANCE --all --hours 72
    python3 news.py --no-exchange --json
    python3 news.py --no-moves                       # skip the price line per ticker

Your tickers, when --tickers is not given: every hit in trader/watchlist.json
(trader-scanner), the symbol in trader/plan.json (trader-exit) and the
positions in trader/portfolio.json.

Sources, one request each per ticker:
  - Yahoo Finance headline RSS in India:
    https://feeds.finance.yahoo.com/rss/2.0/headline?s=RELIANCE.NS&region=IN&lang=en-IN
  - BSE/NSE exchange notice feed for the company (if configured), material
    announcements such as earnings, promoter actions, buybacks, rights issues,
    litigation, delisting, insolvency, and board changes.
  - The move: Yahoo Finance's chart endpoint (unofficial, can lag), the last
    price against yesterday's close:
    https://query2.finance.yahoo.com/v8/finance/chart/RELIANCE.NS?range=1d&interval=5m

Times print in India Standard Time (IST). State: trader/state/news.json
remembers what you have seen (30 days), so an item shows once. Offline:
--offline DIR reads yahoo-<TICKER>.xml, chart-<TICKER>.json,
exchange-<FORM>-<TICKER>.xml and company_tickers.json from DIR. The tests use it.

Headlines are leads, not facts: open the story before acting, and treat
nothing here as advice.
"""

import argparse
import datetime as _dt
import email.utils
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

YAHOO = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=IN&lang=en-IN"
CHART = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m"
PLACEHOLDER = "you@example.com"
BROWSER_UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
KEEP_DAYS = 30
MOVE_PCT = 3.0

ITEMS_NOTICE = {
    "1.01": "material agreement",
    "1.02": "agreement ended",
    "1.03": "bankruptcy or insolvency",
    "1.05": "cybersecurity incident",
    "2.01": "acquisition or sale of assets",
    "2.02": "earnings results",
    "2.03": "new debt",
    "2.04": "debt acceleration",
    "2.05": "restructuring costs",
    "2.06": "impairment",
    "3.01": "delisting notice",
    "3.02": "unregistered share sale",
    "3.03": "shareholder rights change",
    "4.01": "auditor change",
    "4.02": "past financials no longer reliable",
    "5.01": "change in control",
    "5.02": "director or officer change",
    "5.03": "bylaws or fiscal year change",
    "5.07": "shareholder vote results",
    "7.01": "Regulation FD disclosure",
    "8.01": "other events",
    "9.01": "exhibits",
}
IMPORTANT_ITEMS = {"1.03", "1.05", "2.02", "2.04", "2.06", "3.01", "4.02", "5.01", "5.02"}
KEYWORDS = [
    ("earnings", r"\bearnings\b|\bresults\b|\bEPS\b|\bguidance\b|\bforecast\b|\bQ[1-4]\b"),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|price target|outperform|underperform"),
    ("legal", r"\blawsuit\b|\bsued\b|\bprobe\b|\binvestigation\b|\bSEBI\b|\bSCN\b|\bED\b|\bcase\b|\bjudgement\b|\bcourt\b"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bbuyout\b|\btakeover\b|\bdeal\b|\bpartnership\b"),
    ("capital", r"\bdividend\b|\bbuyback\b|\brepurchase\b|\bstock split\b|\boffering\b|\brisks? issue\b|\bbond\b"),
    ("people", r"\bCEO\b|\bCFO\b|\bresign|\bsteps down\b|\bappoint|\bboard\b|\bpromoter\b"),
    ("risk", r"\brecall\b|\bbankrupt|\bdefault\b|\bdelist\b|\bhack\b|\bbreach\b|\boutage\b|\bfraud\b|\binsolvency\b"),
    ("halt", r"\bhalt(?:s|ed)?\b|\btrading (?:pause|suspen)\b|\btrading halt\b"),
    ("regulatory", r"\bSEBI\b|\bRBI\b|\bNSE\b|\bBSE\b|\bapproval\b|\bapproves\b|\bnotice\b|\bdisclosure\b"),
    ("macro", r"\bFed\b|\bRBI\b|\bCPI\b|\binflation\b|\bjobs report\b|\bpayrolls\b|\bindex\b|\bmarket breadth\b|\btrading session\b"),
    ("promoter", r"\bpromoter\b|\bshareholding\b|\bstake\b|\bownership\b|\bpledge\b|\bencumbrance\b"),
    ("corporate", r"\bbuyback\b|\bdividend\b|\bbonus issue\b|\brights issue\b|\bstock split\b|\bcorporate action\b"),
]


class NewsError(Exception):
    pass


def _nth_sunday(year, month, n):
    d = _dt.date(year, month, 1)
    d += _dt.timedelta(days=(6 - d.weekday()) % 7)
    return d + _dt.timedelta(weeks=n - 1)


def ist_offset(utc):
    return 5.5


def to_ist(utc):
    if utc.tzinfo is not None:
        utc = utc.astimezone(_dt.timezone.utc)
    return utc.replace(tzinfo=None) + _dt.timedelta(hours=5, minutes=30)


def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def watch_from_files(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json",
                     plan="trader/plan.json"):
    out = {}
    wl = load_json(watchlist) or {}
    for h in wl.get("hits", []):
        sym = h.get("symbol") or h.get("ticker")
        if sym:
            out[sym.upper()] = h.get("name")
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.setdefault(pl["symbol"].upper(), pl.get("name"))
    pf = load_json(portfolio) or {}
    for p in pf.get("positions", []):
        sym = p.get("ticker") or p.get("symbol")
        if sym:
            out[sym.upper()] = p.get("name") or out.get(sym.upper())
    return out


def exchange_user_agent(cli=None, config="trader/config.json"):
    ua = (cli or os.environ.get("EXCHANGE_USER_AGENT") or "").strip()
    if not ua:
        cfg = load_json(config) or {}
        ua = str(cfg.get("exchange_user_agent") or cfg.get("sec_user_agent") or "").strip()
    if not ua or "@" not in ua or PLACEHOLDER in ua:
        return None
    return ua


class Fetcher(object):
    def __init__(self, exchange_ua=None, offline=None, pause=0.15):
        self.exchange_ua = exchange_ua
        self.offline = offline
        self.pause = pause
        self._last = 0.0

    def get(self, url, name, exchange=False):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise NewsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        if exchange and not self.exchange_ua:
            raise NewsError("no exchange notice User-Agent set")
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        headers = {"User-Agent": self.exchange_ua if exchange else BROWSER_UA, "Accept-Encoding": "gzip"}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as exc:
            raise NewsError("HTTP %s for %s" % (exc.code, url))
        except urllib.error.URLError as exc:
            raise NewsError("could not reach %s: %s" % (url, exc.reason))


def yahoo_symbol(ticker):
    t = (ticker or "").strip().upper()
    if not t:
        return t
    if "." not in t:
        t += ".NS"
    elif not t.endswith(".NS"):
        t = t.split(".")[0] + ".NS"
    return t


def parse_time(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _text(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_rss(data, ticker):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("RSS for %s is not valid XML: %s" % (ticker, exc))
    out = []
    for it in root.iter("item"):
        title = _text(it, "title")
        link = _text(it, "link")
        guid = _text(it, "guid") or link
        out.append({
            "id": "rss:" + guid,
            "source": "Yahoo Finance",
            "kind": "headline",
            "ticker": ticker,
            "title": title,
            "summary": _text(it, "description"),
            "link": link,
            "time": parse_time(_text(it, "pubDate")),
        })
    return out


def parse_exchange_atom(data, ticker):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("exchange notice feed for %s is not valid XML: %s" % (ticker, exc))
    items = []
    company = ""
    for el in root.iter():
        if _local(el.tag) == "conformed-name":
            company = (el.text or "").strip()
            break
    for entry in root.iter():
        if _local(entry.tag) != "entry":
            continue
        form = _text(entry, "filing-type") or _text(entry, "form") or "notice"
        acc = _text(entry, "accession-number") or _text(entry, "id") or form
        items_text = re.findall(r"\d+\.\d+", _text(entry, "items-desc") or _text(entry, "title") or "")
        labels = [ITEMS_NOTICE.get(i, "item " + i) for i in items_text if i != "9.01"]
        link = ""
        for c in entry.iter():
            if _local(c.tag) == "link":
                link = c.get("href", "")
        title = "%s filed a %s" % (company or ticker, form)
        if labels:
            title += ": " + ", ".join(labels)
        items.append({
            "id": "exchange:" + acc,
            "source": "BSE/NSE",
            "kind": "filing",
            "form": form,
            "ticker": ticker,
            "title": title,
            "summary": _text(entry, "form-name") or _text(entry, "summary") or "",
            "items": items_text,
            "important": bool(set(items_text) & IMPORTANT_ITEMS),
            "link": link,
            "time": parse_time(_text(entry, "updated") or _text(entry, "published")),
        })
    return items


def parse_chart(data, ticker):
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        meta = doc["chart"]["result"][0]["meta"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise NewsError("chart for %s is not usable" % ticker)
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not price or not prev:
        raise NewsError("chart for %s has no price" % ticker)
    when = meta.get("regularMarketTime")
    return {
        "ticker": ticker,
        "price": round(float(price), 2),
        "prev_close": round(float(prev), 2),
        "pct": round((float(price) / float(prev) - 1) * 100, 2),
        "time": _dt.datetime.fromtimestamp(when, _dt.timezone.utc) if when else None,
    }


def mention_patterns(watch):
    pats = {}
    for t, name in watch.items():
        alts = [r"\(%s\)" % re.escape(t), r"\$%s\b" % re.escape(t), r"\b%s\b" % re.escape(t)]
        if name and len(name) >= 4:
            alts.append(r"\b%s\b" % re.escape(name).replace(r"\ ", r"[\s-]"))
        pats[t] = re.compile("|".join(alts))
    return pats


def tag(items, watch):
    pats = mention_patterns(watch)
    for it in items:
        hay = "%s %s" % (it["title"], it.get("summary") or "")
        touches = {it["ticker"]} if it["ticker"] in watch else set()
        for t, rx in pats.items():
            if rx.search(hay):
                touches.add(t)
        it["touches"] = sorted(touches)
        it["tags"] = [label for label, rx in KEYWORDS if re.search(rx, hay, re.I)]
        if it["kind"] == "filing" and "2.02" in it.get("items", []) and "earnings" not in it["tags"]:
            it["tags"].insert(0, "earnings")
    return items


def dedupe(items):
    seen, out = {}, []
    for it in items:
        keys = [it["id"], it["link"], "%s|%s" % (re.sub(r"\W+", " ", it["title"].lower()).strip(), it["time"].date() if it["time"] else "")]
        hit = next((seen[k] for k in keys if k and k in seen), None)
        if hit is not None:
            for t in it.get("touches", []):
                if t not in hit["touches"]:
                    hit["touches"].append(t)
            hit["touches"].sort()
            continue
        for k in keys:
            if k:
                seen[k] = it
        out.append(it)
    return out


def fingerprint(it):
    return hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:16]


def collect_moves(fetcher, watch, errors=None):
    errors = [] if errors is None else errors
    out = []
    for t in sorted(watch):
        sym = yahoo_symbol(t)
        name = "chart-%s.json" % t
        try:
            try:
                data = fetcher.get(CHART % ("query2", sym), name)
            except NewsError as exc:
                if fetcher.offline or not re.search(r"HTTP (429|5\d\d)", str(exc)):
                    raise
                data = fetcher.get(CHART % ("query1", sym), name)
            out.append(parse_chart(data, t))
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("price for %s: %s" % (t, exc))
    return out


def collect(fetcher, watch, state, exchange=True, forms=("8-K",), count=10, errors=None):
    errors = [] if errors is None else errors
    items = []
    for t in sorted(watch):
        try:
            items += parse_rss(fetcher.get(YAHOO % yahoo_symbol(t), "yahoo-%s.xml" % t), t)
        except NewsError as exc:
            errors.append("headlines for %s: %s" % (t, exc))
    if exchange:
        for t in sorted(watch):
            for form in forms:
                if fetcher.offline:
                    path = os.path.join(fetcher.offline, "exchange-%s-%s.xml" % (form, t))
                    if not os.path.exists(path):
                        continue
                    try:
                        data = fetcher.get(path, "exchange-%s-%s.xml" % (form, t), exchange=False)
                    except NewsError as exc:
                        errors.append("exchange %s for %s: %s" % (form, t, exc))
                        continue
                    items += parse_exchange_atom(data, t)
                else:
                    errors.append("exchange notices for %s skipped: no BSE/NSE notice feed configured for this run; headlines still work" % t)
                    break
    return items


def select(items, state, now, hours=48, show_all=False):
    seen = state.setdefault("seen", {})
    cutoff = now - _dt.timedelta(hours=hours)
    ahead = now + _dt.timedelta(minutes=10)
    out = []
    for it in items:
        if it["time"] is not None and (it["time"] < cutoff or it["time"] > ahead):
            continue
        fp = fingerprint(it)
        it["new"] = fp not in seen
        if it["new"] or show_all:
            out.append(it)
    out.sort(key=lambda i: (i["time"] or now), reverse=True)
    return out


def remember(items, state, now):
    seen = state.setdefault("seen", {})
    stamp = now.isoformat()
    for it in items:
        seen.setdefault(fingerprint(it), stamp)
    cutoff = (now - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["last_check"] = stamp


def render_moves(moves, move_pct=MOVE_PCT):
    out = []
    for m in moves:
        flag = "MOVING" if abs(m["pct"]) >= move_pct else ""
        when = (" at %s IST" % to_ist(m["time"]).strftime("%H:%M")) if m.get("time") else ""
        out.append("%-8s %s %+.2f%% vs yesterday's close %s%s  %s" % (
            m["ticker"], "{:,.2f}".format(m["price"]), m["pct"], "{:,.2f}".format(m["prev_close"]),
            when, flag))
    return out


def render(items, errors, now, moves=None, move_pct=MOVE_PCT):
    out = render_moves(moves or [], move_pct)
    if out:
        out.append("")
    if not items:
        out.append("Nothing new.")
    for it in items:
        when = to_ist(it["time"]).strftime("%Y-%m-%d %H:%M IST") if it["time"] else "time unknown"
        mark = "!" if it.get("important") else " "
        who = ",".join(it["touches"]) or it["ticker"]
        out.append("%s %s  %-11s %-13s %s" % (mark, when, who, it["source"], it["title"]))
        extra = []
        if it["tags"]:
            extra.append("tags: " + ", ".join(it["tags"]))
        extra.append(it["link"])
        out.append("      " + "  ".join(extra))
    for e in errors:
        out.append("note: %s" % e)
    out.append("Checked %s. Headlines are leads, not facts; open the story before acting. Not financial advice." % to_ist(now).strftime("%Y-%m-%d %H:%M IST"))
    return "\n".join(out) + "\n"


def _json_ready(items):
    out = []
    for it in items:
        d = dict(it)
        d["time"] = it["time"].isoformat() if it["time"] else None
        out.append(d)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tickers", nargs="*", help="default: watchlist + plan + portfolio")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--state", default="trader/state/news.json")
    ap.add_argument("--hours", type=float, default=48, help="ignore items older than this")
    ap.add_argument("--all", action="store_true", help="show seen items too")
    ap.add_argument("--forms", default="8-K", help="exchange forms to watch, comma separated")
    ap.add_argument("--no-exchange", action="store_true", help="headlines only")
    ap.add_argument("--no-sec", dest="no_exchange", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-moves", action="store_true", help="skip the price line per ticker")
    ap.add_argument("--move-pct", type=float, default=MOVE_PCT, help="flag a move this big (percent)")
    ap.add_argument("--user-agent", help="exchange user agent: \"Your Name you@example.com\"")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO time, for reproducible runs")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.tickers:
        watch = {t.upper(): None for t in args.tickers}
        known = watch_from_files(args.portfolio, args.watchlist, args.plan)
        watch.update({t: known[t] for t in watch if known.get(t)})
    else:
        watch = watch_from_files(args.portfolio, args.watchlist, args.plan)
    if not watch:
        print("news: no tickers. Pass --tickers, or run /trader-scanner first (it writes trader/watchlist.json).",
              file=sys.stderr)
        return 2
    now = parse_time(args.now) if args.now else _dt.datetime.now(_dt.timezone.utc)
    state = load_json(args.state) or {}
    errors = []
    ua = exchange_user_agent(args.user_agent, args.config)
    exchange = not args.no_exchange
    if not exchange and not args.offline:
        errors.append("exchange notices skipped: this run is headlines-only")
    fetcher = Fetcher(ua, offline=args.offline)
    forms = [f.strip().upper() for f in args.forms.split(",") if f.strip()]
    items = collect(fetcher, watch, state, exchange=exchange, forms=forms, errors=errors)
    items = dedupe(tag(items, watch))
    shown = select(items, state, now, hours=args.hours, show_all=args.all)
    moves = [] if args.no_moves else collect_moves(fetcher, watch, errors)
    if args.json:
        mv = [dict(m, time=m["time"].isoformat() if m.get("time") else None,
                   moving=abs(m["pct"]) >= args.move_pct) for m in moves]
        print(json.dumps({"checked": now.isoformat(), "moves": mv, "items": _json_ready(shown),
                          "notes": errors}, indent=2))
    else:
        sys.stdout.write(render(shown, errors, now, moves, args.move_pct))
    if not args.dry_run:
        remember(items, state, now)
        folder = os.path.dirname(args.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    return 0 if any(i["new"] for i in shown) else 1


if __name__ == "__main__":
    sys.exit(main())
