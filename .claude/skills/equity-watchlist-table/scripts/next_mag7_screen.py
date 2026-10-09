#!/usr/bin/env python3
# ABOUTME: CLI wrapper for the "next Mag 7" large-cap screen.
# ABOUTME: Prints ranked JSON and saves timestamped CSV/JSON to sandbox/.

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_skills.next_mag7 import MIN_MCAP, UNIVERSE, WEIGHTS, screen
from trading_skills.utils import generated_at_str


def main():
    parser = argparse.ArgumentParser(description="Screen large caps for next-Mag-7 traits")
    parser.add_argument("--symbols", help="Comma-separated override of the built-in universe")
    parser.add_argument("--min-mcap-b", type=float, default=MIN_MCAP / 1e9,
                        help="Minimum market cap in $B (default: 100)")
    parser.add_argument("--top", type=int, default=25, help="Rows to print (default: 25)")
    parser.add_argument("--out-dir", default="sandbox", help="Output directory (default: sandbox)")
    args = parser.parse_args()

    universe = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else UNIVERSE
    df, bench = screen(universe, min_mcap=args.min_mcap_b * 1e9)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d_%H%M")
    base = out_dir / f"next_mag7_screen_{stamp}"
    df.to_csv(f"{base}.csv")

    output = {
        "generated_at": generated_at_str(),
        "data_delay": "15min",
        **bench,
        "passed_mcap_filter": len(df),
        "weights": WEIGHTS,
        "csv": f"{base}.csv",
        "results": json.loads(df.head(args.top).reset_index().to_json(orient="records")),
    }
    with open(f"{base}.json", "w") as f:
        json.dump(output, f, indent=1)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
