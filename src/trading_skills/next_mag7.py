# ABOUTME: Screens US large caps for "next Magnificent 7" traits using Yahoo Finance data.
# ABOUTME: Scores growth, margins, ROIC, FCF, R&D and relative strength vs QQQ as robust z-scores.

import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import yfinance as yf

MAG7 = frozenset({"AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA"})

UNIVERSE = """
AVGO TSM ORCL NFLX PLTR LLY V MA JPM BRK-B WMT COST UNH JNJ ABBV XOM AMD ASML
CRM ADBE NOW INTU UBER SHOP APP CRWD PANW ANET MU QCOM TXN AMAT LRCX KLAC INTC
IBM CSCO SAP ARM SNOW DDOG NET MELI SPOT ISRG BKNG ABNB DASH COIN HOOD NVO AZN
TMUS T VZ GE GEV RTX CAT DE HON LIN SCHW MS GS AXP BX KKR SPGI MCO ICE CME
HD LOW MCD SBUX NKE PG KO PEP PM TMO DHR AMGN GILD VRTX REGN BSX SYK
CEG VST ETN PWR DELL SMCI MRVL CDNS SNPS FTNT WDAY TTD RDDT ADP PYPL SONY BABA
TCEHY PDD SE NU RBLX ZS MSTR VRT
""".split()

MIN_MCAP = 100e9

WEIGHTS = {
    "rev_cagr_3y": 0.20,
    "rev_growth_yoy": 0.10,
    "op_margin": 0.10,
    "op_margin_trend": 0.10,
    "roic": 0.15,
    "fcf_margin": 0.15,
    "rd_intensity": 0.05,
    "rel_1y": 0.075,
    "rel_3y": 0.075,
}


def _row(df: pd.DataFrame | None, *names: str) -> pd.Series | None:
    """First matching statement row, NaNs dropped, oldest-first."""
    for n in names:
        if df is not None and n in df.index:
            s = df.loc[n].dropna().sort_index()
            if len(s):
                return s
    return None


def fetch_fundamentals(symbol: str) -> dict | None:
    """Pull the screen's fundamental inputs for one symbol; None on failure."""
    try:
        t = yf.Ticker(symbol)
        info = t.info
        fin, bs = t.financials, t.balance_sheet
        rev = _row(fin, "Total Revenue")
        opi = _row(fin, "Operating Income", "EBIT")
        rd = _row(fin, "Research And Development")
        tax = _row(fin, "Tax Rate For Calcs")
        eq = _row(bs, "Stockholders Equity", "Common Stock Equity")
        debt = _row(bs, "Total Debt")
        cash = _row(
            bs, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"
        )

        fcf, total_rev = info.get("freeCashflow"), info.get("totalRevenue")
        out = {
            "symbol": symbol,
            "name": info.get("shortName"),
            "sector": info.get("sector"),
            "mcap_b": (info.get("marketCap") or 0) / 1e9,
            "rev_ttm_b": (total_rev or np.nan) / 1e9,
            "rev_growth_yoy": info.get("revenueGrowth"),
            "gross_margin": info.get("grossMargins"),
            "op_margin": info.get("operatingMargins"),
            "fcf_margin": fcf / total_rev if fcf and total_rev else np.nan,
            "fwd_pe": info.get("forwardPE"),
            "ev_sales": info.get("enterpriseToRevenue"),
            "rd_intensity": 0.0,
        }
        if rev is not None and len(rev) >= 2:
            n = min(len(rev) - 1, 3)
            first, last = rev.iloc[-1 - n], rev.iloc[-1]
            out["rev_cagr_3y"] = (last / first) ** (1 / n) - 1 if first > 0 else np.nan
            if opi is not None:
                m = (opi / rev).dropna()
                out["op_margin_trend"] = m.iloc[-1] - m.iloc[0] if len(m) >= 2 else np.nan
            if rd is not None:
                out["rd_intensity"] = rd.iloc[-1] / rev.iloc[-1]
        if opi is not None and eq is not None:
            t_rate = tax.iloc[-1] if tax is not None else 0.21
            invested = (
                eq.iloc[-1]
                + (debt.iloc[-1] if debt is not None else 0)
                - (cash.iloc[-1] if cash is not None else 0)
            )
            out["roic"] = opi.iloc[-1] * (1 - t_rate) / invested if invested > 0 else np.nan
        return out
    except Exception as e:  # noqa: BLE001 - one bad ticker must not stop the screen
        print(f"  ! {symbol}: {e}", file=sys.stderr)
        return None


def trailing_return(prices: pd.Series, days: int) -> float:
    """Return over the last `days` bars; NaN if under 80% of that history exists."""
    s = prices.dropna()
    if len(s) <= days * 0.8:
        return np.nan
    return s.iloc[-1] / s.iloc[max(0, len(s) - days)] - 1


def score_universe(df: pd.DataFrame, weights: dict[str, float] = WEIGHTS) -> pd.DataFrame:
    """Add z_<metric> columns and a weighted `score`; return sorted best-first, 1-based rank.

    Each metric is winsorised at the 5th/95th percentile, scaled by median/MAD, and capped at
    ±3. Missing values are set to the 25th percentile so a gap is penalised rather than dropped.
    """
    df = df.copy()
    score = pd.Series(0.0, index=df.index)
    for col, w in weights.items():
        x = pd.to_numeric(df[col], errors="coerce")
        x = x.fillna(x.quantile(0.25)).clip(x.quantile(0.05), x.quantile(0.95))
        mad = (x - x.median()).abs().median() or x.std() or 1
        # Percentile winsorising can't trim a lone outlier in a small set, so also cap z at ±3
        df[f"z_{col}"] = ((x - x.median()) / (1.4826 * mad)).clip(-3, 3)
        score += w * df[f"z_{col}"]
    df["score"] = score
    # Growth-adjusted valuation: EV/Sales per point of 3y revenue CAGR (context only)
    if {"ev_sales", "rev_cagr_3y"} <= set(df.columns):
        growth = (df.rev_cagr_3y * 100).where(df.rev_cagr_3y > 0)
        df["ev_sales_per_growth"] = df.ev_sales / growth
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df.index += 1
    df.index.name = "rank"
    return df


def screen(
    universe: list[str] = UNIVERSE, min_mcap: float = MIN_MCAP, workers: int = 8
) -> tuple[pd.DataFrame, dict]:
    """Fetch, filter by market cap, add relative strength vs QQQ, and score.

    Returns (scored DataFrame, benchmark returns dict).
    """
    syms = [s for s in dict.fromkeys(universe) if s not in MAG7]
    with ThreadPoolExecutor(workers) as ex:
        rows = [r for r in ex.map(fetch_fundamentals, syms) if r]
    df = pd.DataFrame(rows)
    df = df[df.mcap_b * 1e9 >= min_mcap].copy()

    tickers = list(df.symbol) + ["QQQ"]
    px = yf.download(tickers, period="3y", auto_adjust=True, progress=False)["Close"]
    d1, d3 = 252, 252 * 3 - 5
    q1, q3 = trailing_return(px["QQQ"], d1), trailing_return(px["QQQ"], d3)
    df["ret_1y"] = df.symbol.map(lambda s: trailing_return(px[s], d1))
    df["ret_3y"] = df.symbol.map(lambda s: trailing_return(px[s], d3))
    df["rel_1y"], df["rel_3y"] = df.ret_1y - q1, df.ret_3y - q3

    bench = {"universe_size": len(syms), "qqq_ret_1y": q1, "qqq_ret_3y": q3}
    return score_universe(df), bench
