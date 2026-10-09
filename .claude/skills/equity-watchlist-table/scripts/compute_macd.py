#!/usr/bin/env python3
"""Compute MACD (12/26/9) from daily OHLCV.

Usage:
    python compute_macd.py prices.json
    python compute_macd.py --closes 70.1 71.4 72.0 ...

Input JSON format (from get_equity_historicals, one entry per symbol):
    {
      "AAPL": [{"begins_at": "...", "close_price": "190.1"}, ...],
      "MSFT": [...]
    }
Closes must be oldest-first. You need ~6+ months of daily bars so the 26-period
EMA (and therefore the 9-period signal EMA) is stable.

Output: per symbol, the latest MACD line, signal line, and histogram, plus a
one-word momentum read from the histogram sign.
"""
import json
import sys


def ema(values, period):
    """Standard EMA seeded with the simple average of the first `period` values."""
    if len(values) < period:
        raise ValueError(f"need at least {period} points, got {len(values)}")
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    out = [None] * (period - 1) + [seed]
    prev = seed
    for v in values[period:]:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def macd(closes, fast=12, slow=26, signal=9):
    """Return (macd_line, signal_line, histogram) series aligned to `closes`."""
    if len(closes) < slow + signal:
        raise ValueError(
            f"need >= {slow + signal} closes for a stable signal line, got {len(closes)}"
        )
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    macd_defined = [m for m in macd_line if m is not None]
    sig_defined = ema(macd_defined, signal)
    # re-align signal back onto the full timeline
    pad = len(macd_line) - len(sig_defined)
    signal_line = [None] * pad + sig_defined
    hist = [
        (m - s) if (m is not None and s is not None) else None
        for m, s in zip(macd_line, signal_line)
    ]
    return macd_line, signal_line, hist


def latest(closes):
    m, s, h = macd(closes)
    macd_v, sig_v, hist_v = m[-1], s[-1], h[-1]
    momentum = "bullish" if hist_v > 0 else "bearish" if hist_v < 0 else "flat"
    return {
        "macd": round(macd_v, 3),
        "signal": round(sig_v, 3),
        "histogram": round(hist_v, 3),
        "momentum": momentum,
    }


def closes_from_bars(bars):
    """Extract oldest-first close prices from get_equity_historicals rows."""
    out = []
    for b in bars:
        v = b.get("close_price") or b.get("close") or b.get("c")
        if v is not None:
            out.append(float(v))
    return out


def main(argv):
    if len(argv) >= 2 and argv[1] == "--closes":
        closes = [float(x) for x in argv[2:]]
        print(json.dumps(latest(closes), indent=2))
        return
    if len(argv) != 2:
        print(__doc__)
        sys.exit(1)
    with open(argv[1]) as f:
        data = json.load(f)
    results = {}
    for symbol, bars in data.items():
        try:
            results[symbol] = latest(closes_from_bars(bars))
        except ValueError as e:
            results[symbol] = {"error": str(e)}
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main(sys.argv)
