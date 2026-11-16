#!/usr/bin/env python3
"""Exit and plan stub for Indian market trading."""

import argparse
import json
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(description="Indian-market exit plan")
    ap.add_argument("--stop", type=float, default=0.0)
    ap.add_argument("--target", type=float, default=0.0)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    payload = {"stop": args.stop, "target": args.target, "market": "india"}
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print("exit: stop=%s target=%s" % (args.stop, args.target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
