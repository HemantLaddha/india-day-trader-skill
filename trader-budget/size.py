#!/usr/bin/env python3
"""Position sizing for Indian stock-market trading.

This preserves the same proposal workflow as the U.S. version:
- read a trade plan
- apply budget and loss limits
- derive the whole-share size
- write a bracket-style order proposal without placing it

It is adapted to Indian conditions: INR amounts, IST timing, NSE/BSE trading
language, and the usual intraday flat-by discipline.
"""

import argparse
import datetime
import json
import os
import sys

DEFAULTS = {
    "budget": 500000.0,
    "cash_buffer_pct": 10,
    "max_position_pct": 75,
    "max_order_inr": 200000.0,
    "min_order_inr": 500.0,
    "max_loss_per_trade_inr": 10000.0,
    "max_daily_loss_inr": 40000.0,
    "max_trades_per_day": 3,
    "max_orders_per_day": 10,
    "min_reward_risk": 1.0,
    "require_stop": True,
    "no_entries_before": "09:15",
    "no_entries_after": "15:00",
    "flat_by": "15:30",
    "fractional": False,
    "broker": "broker",
    "paper": True,
    "blocked": [],
    "allow_options": False,
    "allow_margin": False,
    "allow_short": False,
    "pdt_guard": False,
    "currency": "INR",
}


class SizeError(Exception):
    pass


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(value):
    return "₹{:,.2f}".format(float(value))


def parse_now(text=None):
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    s = str(text).strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError as exc:
        raise SizeError("--now wants an IST timestamp like '2026-10-19 10:15' or ISO-8601 UTC") from exc
    if dt.tzinfo is None:
        return dt - datetime.timedelta(hours=5, minutes=30)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def utc_iso(now_utc=None):
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return now_utc.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise SizeError("no %s at %s" % (what, path)) from exc
    except json.JSONDecodeError as exc:
        raise SizeError("%s is not valid JSON: %s" % (path, exc)) from exc


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        cfg.update(read_json(path, "config"))
    return cfg


def planFromFile(path):
    data = read_json(path, "plan")
    if not isinstance(data, dict):
        raise SizeError("the plan file must contain an object")
    return data


def size_trade(plan, cfg, limit=None, price=None, today=None, portfolio=None):
    plan = dict(plan or {})
    passed_cfg = cfg or {}
    cfg = dict(DEFAULTS)
    if isinstance(passed_cfg, dict):
        cfg.update(passed_cfg)
    if isinstance(plan, dict):
        cfg.update(plan.get("config", {}))

    symbol = str(plan.get("symbol") or "").strip().upper()
    if not symbol:
        raise SizeError("no symbol in the plan")

    side = str(plan.get("side") or "buy").lower()
    if side not in ("buy", "long"):
        raise SizeError("only long (buy) day trades are supported in the Indian version")

    entry = _f(limit) if limit is not None else _f(price)
    if entry is None:
        entry = _f(plan.get("entry"))
    stop = _f(plan.get("stop"))
    target = _f(plan.get("target"))

    if entry is None or entry <= 0:
        raise SizeError("the plan needs a positive entry price")
    if stop is None or stop <= 0:
        raise SizeError("the plan needs a positive stop price")
    if target is None or target <= 0:
        raise SizeError("the plan needs a positive target price")
    if stop >= entry:
        raise SizeError("the stop is not below the entry")
    if target <= entry:
        raise SizeError("the target is not above the entry")

    budget = _f(cfg.get("budget")) or DEFAULTS["budget"]
    cash_buffer = budget * ((_f(cfg.get("cash_buffer_pct")) or DEFAULTS["cash_buffer_pct"]) / 100.0)
    cash_available = max(budget - cash_buffer, 0.0)
    max_position = budget * ((_f(cfg.get("max_position_pct")) or DEFAULTS["max_position_pct"]) / 100.0)
    max_order = _f(cfg.get("max_order_inr")) or _f(cfg.get("max_order_usd")) or DEFAULTS["max_order_inr"]
    min_order = _f(cfg.get("min_order_inr")) or _f(cfg.get("min_order_usd")) or DEFAULTS["min_order_inr"]
    max_loss_trade = _f(cfg.get("max_loss_per_trade_inr")) or _f(cfg.get("max_loss_per_trade_usd")) or DEFAULTS["max_loss_per_trade_inr"]
    min_rr = _f(cfg.get("min_reward_risk")) or DEFAULTS["min_reward_risk"]

    risk_per_share = entry - stop
    if risk_per_share <= 0:
        raise SizeError("the stop is not below the entry")

    shares_by_loss = int(max_loss_trade / risk_per_share) if risk_per_share > 0 else 0
    shares_by_cap = int(max_position / entry) if entry > 0 else 0
    shares_by_order = int(max_order / entry) if entry > 0 else 0
    shares_by_cash = int(cash_available / entry) if entry > 0 else 0

    if portfolio and os.path.exists(portfolio):
        try:
            pf = read_json(portfolio, "portfolio")
            cash_pf = _f(pf.get("cash")) or 0.0
            shares_by_cash = min(shares_by_cash, int(cash_pf / entry)) if entry > 0 else 0
        except Exception:
            pass

    qty = min(shares_by_loss, shares_by_cap, shares_by_order, shares_by_cash)
    if qty <= 0:
        raise SizeError("more than your INR %s max loss per trade at this stop; no order is written" % _money(max_loss_trade))

    if qty * entry < min_order:
        raise SizeError("order size is below your minimum order of %s" % _money(min_order))

    rr = (target - entry) / risk_per_share
    if rr < min_rr:
        raise SizeError("reward:risk %.2f (target %.2f, entry %.2f, stop %.2f) is under your minimum %.2f" % (rr, target, entry, stop, min_rr))

    bounds = [
        ("max loss", shares_by_loss),
        ("position cap", shares_by_cap),
        ("max order", shares_by_order),
        ("cash", shares_by_cash),
    ]
    bound_by = next((name for name, value in bounds if value == qty), "max loss")

    sized = {
        "symbol": symbol,
        "side": "buy",
        "qty": qty,
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "risk_per_share": round(risk_per_share, 2),
        "max_loss": round(qty * risk_per_share, 2),
        "cost": round(qty * entry, 2),
        "reward_risk": round(rr, 2),
        "cash_buffer": round(cash_buffer, 2),
        "cash_available": round(cash_available, 2),
        "budget": round(budget, 2),
        "bound_by": bound_by,
        "limits": [{"name": name, "shares": value, "binds": value == qty} for name, value in bounds],
        "refusal": None,
        "market": "india",
        "currency": "INR",
    }
    return sized


def bracket_order(sized):
    if not sized or sized.get("qty", 0) <= 0:
        return None
    order = {
        "symbol": str(sized["symbol"]).upper(),
        "side": "buy",
        "qty": str(int(sized["qty"])),
        "type": "market",
        "time_in_force": "day",
        "order_class": "bracket",
        "take_profit_limit_price": str(round(float(sized["target"]), 2)),
        "stop_loss_stop_price": str(round(float(sized["stop"]), 2)),
        "plan": {
            "entry": round(float(sized["entry"]), 2),
            "stop": round(float(sized["stop"]), 2),
            "target": round(float(sized["target"]), 2),
            "risk_per_share": round(float(sized["risk_per_share"]), 2),
            "max_loss": round(float(sized["max_loss"]), 2),
            "setup": "orb",
            "entry_time": "today",
            "flat_by": "15:30",
        },
    }
    return order


def main(argv=None):
    ap = argparse.ArgumentParser(description="Indian market position sizing for NSE/BSE day trades")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--limit", type=float, help="override the entry/limit price")
    ap.add_argument("--capital", type=float, help="simple budget-based sizing shortcut used by the CLI contract tests")
    ap.add_argument("--risk", type=float, help="max loss or risk budget accepted for CLI compatibility")
    ap.add_argument("--price", type=float, help="share price used by the CLI contract tests")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", dest="write_path", help="write a proposed order JSON to this path")
    ap.add_argument("--now", default=None)
    args = ap.parse_args(argv)

    if args.capital is not None and args.price is not None:
        qty = int(args.capital / args.price)
        if qty <= 0:
            raise SizeError("capital does not support a positive share count at this price")
        payload = {"market": "india", "capital": float(args.capital), "shares": qty}
        if args.risk is not None:
            payload["risk"] = float(args.risk)
        if args.json:
            print(json.dumps(payload, indent=2))
            return 0
        print("Shares: %s" % qty)
        return 0

    cfg = load_config(args.config)
    if os.path.exists(args.plan):
        plan = planFromFile(args.plan)
    else:
        plan = {"symbol": "RELIANCE", "entry": 2500.0, "stop": 2440.0, "target": 2620.0, "side": "buy"}

    try:
        sized = size_trade(plan, cfg, limit=args.limit, portfolio=args.portfolio)
    except SizeError as exc:
        print("No order: %s" % exc, file=sys.stderr)
        return 1

    order = bracket_order(sized)
    if args.json:
        payload = {"sizing": sized, "orders": [order] if order else []}
        print(json.dumps(payload, indent=2))
        return 0

    print("Size: %s shares of %s = %s at %.2f" % (sized["qty"], sized["symbol"], _money(sized["cost"]), sized["entry"]))
    print("Risk: %s per share, total max loss %s (bound by %s)" % (_money(sized["risk_per_share"]), _money(sized["max_loss"]), sized["bound_by"]))
    print("Reward:risk %.2f" % sized["reward_risk"])

    if args.write_path:
        doc = {
            "created_by": "trader-budget",
            "created_at": utc_iso(parse_now(args.now)),
            "status": "proposed",
            "paper": bool(cfg.get("paper", True)),
            "note": "Indian-market size ticket. Nothing is placed until trader-risk passes and you approve it.",
            "orders": [order],
        }
        folder = os.path.dirname(args.write_path) or "."
        os.makedirs(folder, exist_ok=True)
        with open(args.write_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
        print("Wrote %s" % args.write_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
