#!/usr/bin/env python3
"""Position sizing stub for Indian market accounts."""

import argparse
import json
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description="Indian position sizing")
    ap.add_argument("--capital", type=float, default=100000.0)
    ap.add_argument("--risk", type=float, default=1000.0)
    ap.add_argument("--price", type=float, default=100.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    payload = {"capital": args.capital, "risk": args.risk, "price": args.price, "shares": int(args.risk / max(args.price * 0.01, 1.0)), "market": "india"}
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print("budget: shares=%s" % payload["shares"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
