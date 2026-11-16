#!/usr/bin/env python3
"""Broker instructions stub for Indian trading."""

import argparse
import json
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description="Broker ticket and execution review")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--symbol", default="RELIANCE")
    args = ap.parse_args(argv)
    payload = {"symbol": args.symbol.upper(), "paper": True, "market": "india", "status": "READY"}
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print("broker: READY for %s" % args.symbol.upper())
    return 0


if __name__ == "__main__":
    sys.exit(main())
